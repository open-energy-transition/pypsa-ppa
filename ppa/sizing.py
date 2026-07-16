"""Capacity co-optimization: size wind/PV/BESS with a single multi-year investment LP.

Two-stage flow: the sizing LP here optimizes capacities + dispatch over the
concatenated simulation horizon (least-cost-to-serve-the-PPA, see
`ppa.network.build_network` sizing mode) at a coarse, configurable time
resolution (`scenario.sizing_resolution_h`, default 3h), then `apply_sizing`
writes the optimal capacities back into a fixed-capacity Scenario that the
existing per-year *hourly* simulation (`ppa.multi_year.run_multi_year`) and
financials consume unchanged.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import pandas as pd

from ppa.data.european_data import build_year_timeseries, pick_weather_year
from ppa.multi_year import _available_memory_mb, _PER_WORKER_MEM_MB
from ppa.network import build_network
from ppa.scenario import Scenario
from ppa.solver import solve


@dataclass
class SizedCapacities:
    onsw_mw: float
    pv_mw: float
    bess_mw: float
    bess_mwh: float
    status: str
    condition: str
    sizing_years_used: int
    horizon_clamped: bool
    resolution_h: int = 1


def clamp_sizing_years(requested_years: int, resolution_h: float = 1.0) -> tuple[int, str | None]:
    """Clamp the sizing-LP horizon to what fits in available RAM.

    A single-year *hourly* solve peaks ~`_PER_WORKER_MEM_MB` MB and linopy LP
    memory grows roughly linearly with snapshots, so a year at `resolution_h`
    hours per snapshot costs ~that much / resolution_h. We budget one year-block
    per that much available memory. Returns (clamped_years, notice) where notice
    is a human-readable message when clamping occurred (None otherwise).
    """
    requested_years = max(1, int(requested_years))
    mem_mb = _available_memory_mb()
    if mem_mb is None:
        return requested_years, None

    per_year_mem_mb = _PER_WORKER_MEM_MB / max(1.0, float(resolution_h))
    fit_years = max(1, int(mem_mb // per_year_mem_mb))
    if fit_years >= requested_years:
        return requested_years, None

    notice = (
        f"Sizing LP horizon reduced from {requested_years} to {fit_years} year(s) "
        f"to fit available memory (~{mem_mb / 1024:.1f} GB free, "
        f"~{per_year_mem_mb / 1024:.1f} GB per simulated year at "
        f"{resolution_h:.0f}h resolution). "
        "Optimized capacities are sized on the reduced horizon; the full "
        f"{requested_years}-year simulation still runs with those capacities."
    )
    return fit_years, notice


def build_sizing_timeseries(
    scenario: Scenario,
    pv_cf_by_year: dict[int, pd.Series],
    wind_cf_by_year: dict[int, pd.Series],
    prices_by_year: dict[int, pd.Series],
    n_sizing_years: int,
) -> pd.DataFrame:
    """Concatenate per-year timeseries into one sizing-LP horizon.

    Reuses `build_year_timeseries` per simulation year, so weather-year cycling
    and price escalation match the per-year simulation exactly. Wind/PV
    degradation is baked into the CF columns per year (mirrors
    `ppa.multi_year._degraded_scenario`, which scales p_nom instead — equivalent
    for the LP since p_nom × p_max_pu bounds output either way).
    """
    available_weather_years = sorted(pv_cf_by_year.keys())
    available_price_years = sorted(prices_by_year.keys())

    frames: list[pd.DataFrame] = []
    for idx in range(n_sizing_years):
        sim_year = scenario.first_sim_year + idx
        weather_year = pick_weather_year(idx, available_weather_years)
        price_year = pick_weather_year(idx, available_price_years)
        ts = build_year_timeseries(
            sim_year=sim_year,
            weather_year=weather_year,
            ppa_load_mw=scenario.ppaload_mw,
            pv_cf_by_year=pv_cf_by_year,
            wind_cf_by_year=wind_cf_by_year,
            # Same remap as run_multi_year: build_year_timeseries looks prices up
            # by weather_year, so alias the cycled price year under that key.
            prices_by_year={weather_year: prices_by_year[price_year]},
            price_escalation_rate=scenario.price_escalation_rate,
            load_profile=scenario.load_profile,
        )
        # Bake technology degradation into the capacity factors for this year
        ts["ts_PVGen"] = ts["ts_PVGen"] * (1.0 - scenario.pv_degradation_rate) ** idx
        ts["ts_WindGen"] = ts["ts_WindGen"] * (1.0 - scenario.wind_degradation_rate) ** idx
        frames.append(ts)

    sizing_ts = pd.concat(frames)
    sizing_ts.index.name = "snapshot"
    return sizing_ts


def coarsen_timeseries(ts: pd.DataFrame, resolution_h: int) -> pd.DataFrame:
    """Downsample an hourly timeseries to `resolution_h`-hour block averages.

    Block-averaging CFs, prices and load preserves per-block energy and cost
    exactly; only intra-block variability (which the sizing LP doesn't need at
    full fidelity) is smoothed. Bins align to midnight, and year blocks are
    whole multiples of common resolutions, so no bin straddles a year boundary.
    """
    if resolution_h <= 1:
        return ts
    coarse = ts.resample(f"{resolution_h}h").mean()
    coarse.index.name = ts.index.name
    return coarse


def optimize_capacities(ts: pd.DataFrame, scenario: Scenario) -> SizedCapacities:
    """Solve the investment LP at coarse resolution and extract optimal capacities.

    `ts` is the hourly timeseries; it is downsampled here to
    `scenario.sizing_resolution_h`-hour blocks before the solve. Snapshot
    weightings (set in `build_network`) keep costs and storage dynamics in real
    hours.

    BESS energy capacity fade cannot be time-varied on a StorageUnit, so the
    horizon-average degradation factor is applied to the fixed duration — a
    slight de-rating that approximates multi-year usable-capacity fade.
    """
    resolution_h = max(1, int(scenario.sizing_resolution_h))
    ts = coarsen_timeseries(ts, resolution_h)
    n_years = max(1, round(len(ts) * resolution_h / 8760))
    avg_bess_factor = (
        sum((1.0 - scenario.bess_degradation_rate) ** i for i in range(n_years)) / n_years
    )

    sizing_scn = dataclasses.replace(
        scenario,
        optimize_capacity=True,
        include_bess=scenario.include_bess and scenario.max_build_bess_mw > 0,
        # Fixed duration for the sizing LP, de-rated for average degradation.
        # bess_max_hours reads bess_mwh/bess_mw, so encode via a 1 MW reference.
        bess_mw=1.0,
        bess_mwh=scenario.bess_max_hours * avg_bess_factor,
        # The LP prices BESS capex as €/kWh × max_hours; compensate the de-rated
        # hours so capex is still charged on the *nameplate* energy.
        bess_capex_per_kwh=scenario.bess_capex_per_kwh / avg_bess_factor,
    )
    if not sizing_scn.include_bess:
        sizing_scn = dataclasses.replace(sizing_scn, max_build_bess_mw=0.0)

    n = build_network(ts, sizing_scn, resolution_h=resolution_h)
    status, condition = solve(n, sizing_scn, ts)

    # max(0, ·) clamps solver noise (e.g. -0.0 / -1e-9) at zero builds
    onsw_mw = max(0.0, float(n.generators.p_nom_opt["Gen_OnshoreWind"]))
    pv_mw = max(0.0, float(n.generators.p_nom_opt["Gen_PV"]))
    bess_mw = max(0.0, float(n.storage_units.p_nom_opt["SU_BESS"]))
    # Report undegraded nameplate energy (the simulation applies fade per year itself)
    bess_mwh = bess_mw * scenario.bess_max_hours

    return SizedCapacities(
        onsw_mw=onsw_mw,
        pv_mw=pv_mw,
        bess_mw=bess_mw,
        bess_mwh=bess_mwh,
        status=status,
        condition=condition,
        sizing_years_used=n_years,
        horizon_clamped=n_years < scenario.simulation_years,
        resolution_h=resolution_h,
    )


def apply_sizing(scenario: Scenario, sized: SizedCapacities) -> Scenario:
    """Write optimized capacities into a fixed-capacity Scenario for simulation."""
    bess_built = sized.bess_mw > 0.1  # ignore solver noise below 0.1 MW
    return dataclasses.replace(
        scenario,
        onsw_mw=round(sized.onsw_mw, 1),
        pv_mw=round(sized.pv_mw, 1),
        bess_mw=round(sized.bess_mw, 1) if bess_built else 0.0,
        bess_mwh=round(sized.bess_mwh, 1) if bess_built else 0.0,
        include_bess=scenario.include_bess and bess_built,
        optimize_capacity=False,
    )
