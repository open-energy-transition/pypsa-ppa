"""Multi-year parallel simulation runner."""
from __future__ import annotations

import dataclasses
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

import pandas as pd

from ppa.data.european_data import build_year_timeseries, pick_weather_year
from ppa.network import build_network
from ppa.results import OptimizationResult, extract_results
from ppa.scenario import Scenario
from ppa.solver import solve


def _degraded_scenario(scenario: Scenario, year_idx: int) -> Scenario:
    """
    Return a copy of `scenario` with technology degradation applied for simulation year `year_idx`.

    year_idx is 0-based (year_idx=0 → no degradation, year_idx=1 → one year of degradation, …).
    Wind/solar degradation scales the effective CF via p_nom reduction; BESS degradation
    reduces usable energy capacity.
    """
    if year_idx == 0:
        return scenario

    pv_factor = (1.0 - scenario.pv_degradation_rate) ** year_idx
    wind_factor = (1.0 - scenario.wind_degradation_rate) ** year_idx
    bess_factor = (1.0 - scenario.bess_degradation_rate) ** year_idx

    return dataclasses.replace(
        scenario,
        pv_mw=scenario.pv_mw * pv_factor,
        onsw_mw=scenario.onsw_mw * wind_factor,
        bess_mwh=scenario.bess_mwh * bess_factor,
    )


def _solve_one_year(
    sim_year_idx: int,
    sim_year: int,
    ts: pd.DataFrame,
    scenario: Scenario,
) -> tuple[int, OptimizationResult]:
    """Solve a single year's LP. Returns (sim_year_idx, result)."""
    n = build_network(ts, scenario)
    status, condition = solve(n, scenario, ts)
    result = extract_results(n, scenario, ts, status, condition)
    return sim_year_idx, result


def run_multi_year(
    scenario: Scenario,
    pv_cf_by_year: dict[int, pd.Series],
    wind_cf_by_year: dict[int, pd.Series],
    prices_by_year: dict[int, pd.Series],
    first_sim_year: int = 2025,
    max_workers: int = 4,
    progress_callback: Callable[[int, int, int], None] | None = None,
) -> list[OptimizationResult]:
    """
    Run `scenario.simulation_years` independent year-simulations in parallel.

    Weather years (CF + prices) are cycled from the available historical keys.
    Using the same historical year for both CF and prices preserves correlations
    (e.g. 2021: high prices + low wind).  Prices are then escalated from that
    historical base year to the simulation year via `scenario.price_escalation_rate`.
    Technology degradation is applied per-year via `scenario.*_degradation_rate`.
    """
    n_years = scenario.simulation_years
    available_weather_years = sorted(pv_cf_by_year.keys())
    available_price_years = sorted(prices_by_year.keys())

    # Pre-build all timeseries and per-year scenarios on the main thread
    timeseries_by_idx: dict[int, pd.DataFrame] = {}
    scenario_by_idx: dict[int, Scenario] = {}
    for idx in range(n_years):
        sim_year = first_sim_year + idx
        weather_year = pick_weather_year(idx, available_weather_years)
        # Cycle price years independently if they don't fully overlap with CF years
        price_year = pick_weather_year(idx, available_price_years)
        degraded = _degraded_scenario(scenario, idx)
        ts = build_year_timeseries(
            sim_year=sim_year,
            weather_year=weather_year,
            ppa_load_mw=degraded.ppaload_mw,
            pv_cf_by_year=pv_cf_by_year,
            wind_cf_by_year=wind_cf_by_year,
            prices_by_year={weather_year: prices_by_year[price_year]},
            price_escalation_rate=scenario.price_escalation_rate,
            load_profile=scenario.load_profile,
        )
        timeseries_by_idx[idx] = ts
        scenario_by_idx[idx] = degraded

    results: list[OptimizationResult | None] = [None] * n_years
    completed = 0

    # ThreadPoolExecutor: HiGHS releases the GIL during solve, so threads get real parallelism
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _solve_one_year,
                idx,
                first_sim_year + idx,
                timeseries_by_idx[idx],
                scenario_by_idx[idx],
            ): idx
            for idx in range(n_years)
        }

        for future in as_completed(futures):
            idx = futures[future]
            sim_year = first_sim_year + idx
            year_idx, result = future.result()  # propagates exceptions
            results[year_idx] = result
            completed += 1
            if progress_callback is not None:
                progress_callback(completed, n_years, sim_year)

    return results  # type: ignore[return-value]
