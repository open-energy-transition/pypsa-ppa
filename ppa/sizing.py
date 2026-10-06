"""Capacity co-optimization: size wind/PV/BESS with a single multi-year investment LP.

Two-stage flow: the sizing LP here optimizes capacities + dispatch over the
concatenated simulation horizon (least-cost-to-serve-the-PPA, see
`ppa.network.build_network` sizing mode) at a coarse, configurable time
resolution (`scenario.sizing_resolution_h`, default 3h), then `apply_sizing`
writes the optimal capacities back into a fixed-capacity Scenario that the
existing per-year *hourly* simulation (`ppa.multi_year.run_multi_year`) and
financials consume unchanged.

Optionally, the same LP model is re-solved for modelling-to-generate-
alternatives (MGA, `run_mga`): a cost-budget constraint keeps every alternative
within a slack of the least-cost optimum while the objective is swapped to
explore technology extremes and stakeholder-oriented designs.
"""

from __future__ import annotations

import dataclasses
import math
import traceback
from dataclasses import dataclass, field
from typing import Callable, Sequence

import pandas as pd

from ppa.data.european_data import build_year_timeseries, pick_weather_year
from ppa.multi_year import _available_memory_mb, _PER_WORKER_MEM_MB
from ppa.network import build_network
from ppa.scenario import Scenario
from ppa.solver import solve
from ppa.subprocesses import main_module_hidden, spawn_context


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
    # Near-optimal alternatives, set when the sizing LP ran with MGA enabled
    mga: "MGAResult | None" = None


def weather_cycle_years(
    requested_years: int, n_weather_years: int, n_price_years: int
) -> tuple[int, str | None]:
    """Cap the sizing horizon at one full cycle of the historical input years.

    The simulation cycles CF and price years from the cached historical sets
    (`pick_weather_year`), so beyond one least-common-multiple cycle the sizing
    LP re-solves near-copies of the same profiles (only slow degradation /
    price-escalation drift differs). Capping there keeps all weather diversity
    at a fraction of the LP size. Returns (capped_years, note) with a
    human-readable note when the cap bites (None otherwise).
    """
    requested_years = max(1, int(requested_years))
    cycle = math.lcm(max(1, int(n_weather_years)), max(1, int(n_price_years)))
    if cycle >= requested_years:
        return requested_years, None

    note = (
        f"Sizing LP horizon set to {cycle} year(s): one full cycle of the "
        f"{n_weather_years} cached weather year(s) and {n_price_years} price "
        f"year(s). Later years repeat the same profiles, so a "
        f"{requested_years}-year sizing LP would add cost but almost no new "
        "information. The full simulation still runs all "
        f"{requested_years} year(s) hourly with the sized capacities."
    )
    return cycle, note


def clamp_sizing_years(
    requested_years: int, resolution_h: float = 1.0
) -> tuple[int, str | None]:
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
    `ppa.multi_year._degraded_scenario`, which scales p_nom instead: equivalent
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
        ts["ts_WindGen"] = (
            ts["ts_WindGen"] * (1.0 - scenario.wind_degradation_rate) ** idx
        )
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


def optimize_capacities(
    ts: pd.DataFrame,
    scenario: Scenario,
    mga_slack: float | None = None,
    mga_objectives: Sequence[str] = (),
    progress: Callable[[str], None] | None = None,
) -> SizedCapacities:
    """Solve the investment LP at coarse resolution and extract optimal capacities.

    `ts` is the hourly timeseries; it is downsampled here to
    `scenario.sizing_resolution_h`-hour blocks before the solve. Snapshot
    weightings (set in `build_network`) keep costs and storage dynamics in real
    hours.

    BESS energy capacity fade cannot be time-varied on a StorageUnit, so the
    horizon-average degradation factor is applied to the fixed duration: a
    slight de-rating that approximates multi-year usable-capacity fade.

    With `mga_slack` and `mga_objectives` set, the solved model is re-used for
    near-optimal alternatives (`run_mga`), returned on `SizedCapacities.mga`.
    `progress` receives a short status line before each alternative solve.
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

    sized = _extract_sized(n, scenario, status, condition, n_years, resolution_h)
    if status == "ok" and mga_slack is not None and mga_objectives:
        sized.mga = run_mga(
            n, sizing_scn, scenario, sized, mga_slack, mga_objectives, progress
        )
    return sized


def _extract_sized(
    n, scenario: Scenario, status: str, condition: str, n_years: int, resolution_h: int
) -> SizedCapacities:
    """Read the optimal capacities of a solved sizing network."""
    # max(0, ·) clamps solver noise (e.g. -0.0 / -1e-9) at zero builds
    if "p_nom_opt" in n.generators.static.columns:
        onsw_mw = max(0.0, float(n.generators.static.p_nom_opt["Gen_OnshoreWind"]))
        pv_mw = max(0.0, float(n.generators.static.p_nom_opt["Gen_PV"]))
        bess_mw = max(0.0, float(n.storage_units.static.p_nom_opt["SU_BESS"]))
    else:
        onsw_mw = 0.0
        pv_mw = 0.0
        bess_mw = 0.0

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


# ── Modelling to generate alternatives (MGA) ──────────────────────────────────


@dataclass(frozen=True)
class MGAObjective:
    key: str
    label: str
    stakeholder: str
    description: str


MGA_OBJECTIVES: dict[str, MGAObjective] = {
    o.key: o
    for o in [
        MGAObjective("min_wind", "Min wind", "Technology range", "Least onshore wind MW within the cost budget."),
        MGAObjective("max_wind", "Max wind", "Technology range", "Most onshore wind MW within the cost budget."),
        MGAObjective("min_pv", "Min solar", "Technology range", "Least solar PV MW within the cost budget."),
        MGAObjective("max_pv", "Max solar", "Technology range", "Most solar PV MW within the cost budget."),
        MGAObjective("min_bess", "Min BESS", "Technology range", "Least battery power (fixed duration) within the cost budget."),
        MGAObjective("max_bess", "Max BESS", "Technology range", "Most battery power (fixed duration) within the cost budget."),
        MGAObjective(
            "min_re_mw",
            "Smallest RE fleet",
            "Landowners & permitting",
            "Least wind + solar MW: smallest land footprint and fewest permits.",
        ),
        MGAObjective(
            "max_re_matching",
            "Max hourly RE matching",
            "Offtaker (24/7 green claims)",
            "Serve the most PPA load hour-by-hour from own wind/solar/BESS: least "
            "market buying, penalty and shortfall.",
        ),
        MGAObjective(
            "min_capex",
            "Lowest upfront capex",
            "Lenders & equity",
            "Least overnight capital at risk, accepting more market buying / shortfall.",
        ),
        MGAObjective(
            "min_surplus",
            "Least surplus energy",
            "Grid operator / resource efficiency",
            "Least curtailed or exported surplus: a fleet closely matched to the PPA.",
        ),
    ]
}
TECH_RANGE_OBJECTIVES = ("min_wind", "max_wind", "min_pv", "max_pv", "min_bess", "max_bess")
STAKEHOLDER_OBJECTIVES = ("min_re_mw", "max_re_matching", "min_capex", "min_surplus")

# Tech suffix of a min_/max_ objective key -> (component, name) it targets
_TECH_ASSETS = {
    "wind": ("Generator", "Gen_OnshoreWind"),
    "pv": ("Generator", "Gen_PV"),
    "bess": ("StorageUnit", "SU_BESS"),
}
_RE_GENERATORS = ["Gen_OnshoreWind", "Gen_PV"]
_NON_RE_SUPPLY = ["Gen_BuyFromMarket", "Gen_Penalty", "Gen_AllowedShortfall"]


@dataclass
class MGAAlternative:
    key: str
    label: str
    stakeholder: str
    sized: SizedCapacities
    # Net cost increase over the least-cost optimum, as a fraction of the
    # optimum's total cost (bounded by the MGA slack)
    cost_increase: float
    total_cost_eur_per_yr: float
    capex_eur: float
    re_matching_share: float
    market_buy_share: float
    surplus_share: float


@dataclass
class MGAResult:
    slack: float
    optimum: MGAAlternative
    alternatives: list[MGAAlternative]
    notes: list[str] = field(default_factory=list)

    @property
    def all(self) -> list[MGAAlternative]:
        return [self.optimum, *self.alternatives]


def _mga_expression(m, n, key: str):
    """Linear expression for an MGA objective; always minimized (max = negated)."""
    p_nom = {
        "Generator": m.variables["Generator-p_nom"],
        "StorageUnit": m.variables["StorageUnit-p_nom"],
    }
    gen_p = m.variables["Generator-p"]
    sense, target = key.split("_", 1)

    if target in _TECH_ASSETS:
        component, name = _TECH_ASSETS[target]
        expr = 1.0 * p_nom[component].loc[name]
    elif key == "min_re_mw":
        expr = p_nom["Generator"].loc[_RE_GENERATORS].sum()
    elif key == "max_re_matching":
        # Maximize own-RE matching == minimize energy served by anything else
        return gen_p.loc[:, _NON_RE_SUPPLY].sum()
    elif key == "min_capex":
        # capital_cost is overnight capex × (crf + opex) × horizon for every
        # technology, so this ranks fleets exactly as overnight capex does
        cc_gen = n.generators.static.capital_cost
        cc_su = float(n.storage_units.static.capital_cost["SU_BESS"])
        expr = (
            p_nom["Generator"].loc["Gen_OnshoreWind"] * float(cc_gen["Gen_OnshoreWind"])
            + p_nom["Generator"].loc["Gen_PV"] * float(cc_gen["Gen_PV"])
            + p_nom["StorageUnit"].loc["SU_BESS"] * cc_su
        )
    elif key == "min_surplus":
        # Curtailment (available − generated) plus energy dumped to market.
        # Snapshot weightings are uniform, so unweighted sums rank identically.
        cf_sum = n.generators.dynamic.p_max_pu[_RE_GENERATORS].sum()
        expr = (
            p_nom["Generator"].loc["Gen_OnshoreWind"] * float(cf_sum["Gen_OnshoreWind"])
            + p_nom["Generator"].loc["Gen_PV"] * float(cf_sum["Gen_PV"])
            - gen_p.loc[:, _RE_GENERATORS].sum()
            + gen_p.loc[:, "Gen_SellToMarket"].sum()
        )
    else:
        raise ValueError(f"Unknown MGA objective: {key}")
    return -expr if sense == "max" else expr


def _lp_energy_metrics(n) -> dict[str, float]:
    """Weighted energy totals (MWh over the LP horizon) of a solved sizing network."""
    w = n.snapshot_weightings.generators
    p = n.generators.dynamic.p.mul(w, axis=0).sum()
    p_nom = n.generators.static.p_nom_opt
    available = sum(
        float((n.generators.dynamic.p_max_pu[g] * w).sum()) * max(0.0, float(p_nom[g]))
        for g in _RE_GENERATORS
    )
    generated = float(p[_RE_GENERATORS].sum())
    return {
        "load": float((n.loads.dynamic.p_set["Load_PPAOfftake"] * w).sum()),
        "delivery": float((n.links.dynamic.p0["IPPGen_to_PPAOfftake"] * w).sum()),
        "buy": float(p["Gen_BuyFromMarket"]),
        "non_re": float(p[_NON_RE_SUPPLY].sum()),
        "available": available,
        "surplus": available - generated + float(p["Gen_SellToMarket"]),
    }


def run_mga(
    n,
    sizing_scn: Scenario,
    scenario: Scenario,
    optimum: SizedCapacities,
    slack: float,
    objectives: Sequence[str],
    progress: Callable[[str], None] | None = None,
) -> MGAResult:
    """Re-solve a solved sizing LP for near-optimal alternatives.

    Adds a budget constraint `objective ≤ obj* + slack · C*` and swaps in each
    requested objective in turn, reusing the built linopy model (custom
    shortfall/buy-cap constraints included). The sizing objective is *net* of
    PPA revenue (often negative), so the slack is taken on the optimum's gross
    total cost C* = obj* + PPA revenue — i.e. every alternative's cost of
    serving the PPA, counting any lost PPA revenue as a cost, stays within
    `slack` × the least-cost total cost.
    """
    m = n.model
    base_expr = m.objective.expression
    obj_opt = float(m.objective.value)
    horizon_years = len(n.snapshots) * optimum.resolution_h / 8760.0
    opt_energy = _lp_energy_metrics(n)
    # transmission_cost is a genuine cost and stays in C*; only the tariff is revenue
    ppa_revenue_opt = scenario.ppa_price * opt_energy["delivery"]
    total_cost_opt = max(0.0, obj_opt + ppa_revenue_opt)

    def _alternative(key: str, label: str, stakeholder: str, sized: SizedCapacities, obj: float) -> MGAAlternative:
        e = _lp_energy_metrics(n)
        load = e["load"] or 1.0
        capex = (
            sized.onsw_mw * scenario.wind_capex_per_kw * 1_000
            + sized.pv_mw * scenario.pv_capex_per_kw * 1_000
            + sized.bess_mwh * scenario.bess_capex_per_kwh * 1_000
        )
        return MGAAlternative(
            key=key,
            label=label,
            stakeholder=stakeholder,
            sized=sized,
            cost_increase=(obj - obj_opt) / total_cost_opt if total_cost_opt > 0 else 0.0,
            total_cost_eur_per_yr=(total_cost_opt + obj - obj_opt) / horizon_years,
            capex_eur=capex,
            re_matching_share=1.0 - e["non_re"] / load,
            market_buy_share=e["buy"] / load,
            surplus_share=e["surplus"] / e["available"] if e["available"] > 0 else 0.0,
        )

    result = MGAResult(
        slack=slack,
        optimum=_alternative("optimum", "Least-cost optimum", "Least cost to serve the PPA", optimum, obj_opt),
        alternatives=[],
    )

    caps = {
        "wind": sizing_scn.max_build_wind_mw,
        "pv": sizing_scn.max_build_pv_mw,
        "bess": sizing_scn.max_build_bess_mw,
    }
    opt_mw = {"wind": optimum.onsw_mw, "pv": optimum.pv_mw, "bess": optimum.bess_mw}
    todo: list[str] = []
    for key in objectives:
        if key not in MGA_OBJECTIVES:
            raise ValueError(f"Unknown MGA objective: {key}")
        sense, target = key.split("_", 1)
        if target in caps:
            label = MGA_OBJECTIVES[key].label
            if caps[target] <= 0:
                result.notes.append(f"{label}: skipped, technology not buildable.")
                continue
            if sense == "min" and opt_mw[target] < 0.1:
                result.notes.append(f"{label}: skipped, already zero at the optimum.")
                continue
            if sense == "max" and opt_mw[target] >= caps[target] - 0.1:
                result.notes.append(f"{label}: skipped, already at the build cap at the optimum.")
                continue
        todo.append(key)

    if not todo:
        return result

    m.add_constraints(
        base_expr <= obj_opt + slack * total_cost_opt, name="MGA_CostBudget"
    )
    for i, key in enumerate(todo, start=1):
        obj = MGA_OBJECTIVES[key]
        if progress is not None:
            progress(f"Near-optimal alternative {i}/{len(todo)}: {obj.label}")
        m.objective = _mga_expression(m, n, key)
        status, condition = n.optimize.solve_model(solver_name="highs", io_api="direct")
        if status != "ok":
            result.notes.append(f"{obj.label}: solve failed ({status} / {condition}).")
            continue
        sized = _extract_sized(
            n, scenario, status, condition, optimum.sizing_years_used, optimum.resolution_h
        )
        sized.horizon_clamped = optimum.horizon_clamped
        result.alternatives.append(
            _alternative(key, obj.label, obj.stakeholder, sized, float(base_expr.solution.sum()))
        )
    return result


def _sizing_worker(
    conn,
    ts: pd.DataFrame,
    scenario_fields: dict,
    mga_slack: float | None = None,
    mga_objectives: Sequence[str] = (),
) -> None:
    """Child-process entry point: solve the sizing LP and send the result back.

    Takes the scenario as a plain dict for the same Streamlit class-reload
    pickling reason as `ppa.multi_year._solve_one_year`. MGA progress lines are
    streamed as ("progress", text) messages before the final ("ok"/"err", ·).
    """
    try:
        sized = optimize_capacities(
            ts,
            Scenario(**scenario_fields),
            mga_slack=mga_slack,
            mga_objectives=mga_objectives,
            progress=lambda text: conn.send(("progress", text)),
        )
        conn.send(("ok", sized))
    except BaseException:
        conn.send(("err", traceback.format_exc()))
    finally:
        conn.close()


def _recv_result(conn, on_progress: Callable[[str], None] | None):
    """Receive one message; progress lines are forwarded and yield (None, None)."""
    kind, payload = conn.recv()
    if kind == "progress":
        if on_progress is not None:
            on_progress(payload)
        return None, None
    return kind, payload


def run_sizing_subprocess(
    ts: pd.DataFrame,
    scenario: Scenario,
    heartbeat: Callable[[], None] | None = None,
    poll_interval: float = 0.5,
    mga_slack: float | None = None,
    mga_objectives: Sequence[str] = (),
    on_progress: Callable[[str], None] | None = None,
) -> SizedCapacities:
    """Run `optimize_capacities` in a killable child process.

    The solve is one blocking native HiGHS call, so it cannot be interrupted
    in-process (Streamlit's Stop button, Ctrl+C and SIGTERM are all deferred
    until the solver returns). Running it in a child process makes it
    cancellable: `heartbeat` is invoked every `poll_interval` seconds and may
    raise (e.g. a Streamlit StopException); the child is then killed by the
    finally block. Killing the child also returns the LP's multi-GB memory to
    the OS immediately instead of leaving it in the app process.

    `mga_slack`/`mga_objectives` are forwarded to `optimize_capacities`;
    `on_progress` receives the child's MGA progress lines.
    """
    mp_context = spawn_context()  # not fork: see ppa.subprocesses

    parent_conn, child_conn = mp_context.Pipe(duplex=False)
    proc = mp_context.Process(
        target=_sizing_worker,
        args=(
            child_conn,
            ts,
            dataclasses.asdict(scenario),
            mga_slack,
            tuple(mga_objectives),
        ),
        daemon=True,
    )
    with main_module_hidden():
        proc.start()
    child_conn.close()

    try:
        kind = None
        while kind is None:
            if parent_conn.poll(poll_interval):
                kind, payload = _recv_result(parent_conn, on_progress)
                continue
            if not proc.is_alive():
                # Drain a result sent just before exit, else it truly crashed
                while kind is None and parent_conn.poll(0):
                    kind, payload = _recv_result(parent_conn, on_progress)
                if kind is not None:
                    break
                raise RuntimeError(
                    "Sizing subprocess died without returning a result "
                    "(likely killed by the OS: out of memory?)."
                )
            if heartbeat is not None:
                heartbeat()  # may raise (user cancelled) → finally kills child
    finally:
        if proc.is_alive():
            proc.kill()
        proc.join(timeout=5)
        parent_conn.close()

    if kind == "err":
        raise RuntimeError(f"Capacity sizing LP failed in subprocess:\n{payload}")
    return payload


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
