"""Multi-year parallel simulation runner."""
from __future__ import annotations

import dataclasses
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Callable

import pandas as pd

from ppa.data.european_data import build_year_timeseries, pick_weather_year
from ppa.network import build_network
from ppa.results import OptimizationResult, extract_results
from ppa.scenario import Scenario
from ppa.solver import solve

import streamlit as st

# Peak RSS of a single full-year EU solve, measured at ~735 MB with io_api="direct".
# Each parallel worker is its own process and pays this in full, so we budget one
# worker per this much *available* RAM. Override via PPA_WORKER_MEM_MB for other
# model sizes.
_PER_WORKER_MEM_MB = int(os.environ.get("PPA_WORKER_MEM_MB", "1200"))


def _available_memory_mb() -> float | None:
    """Best-effort RAM headroom in MB, honouring cgroup limits (containers).

    Returns the min of the cgroup memory headroom and host MemAvailable, or None
    if nothing could be read. Streamlit Community Cloud caps memory via cgroups at
    ~1 GB, well below the host's reported free memory, so cgroup awareness is what
    makes the cloud fall back to serial.
    """
    candidates: list[float] = []

    # cgroup v2 (Streamlit Cloud, most modern containers)
    try:
        with open("/sys/fs/cgroup/memory.max") as fh:
            raw = fh.read().strip()
        if raw != "max":
            limit = int(raw)
            with open("/sys/fs/cgroup/memory.current") as fh:
                used = int(fh.read().strip())
            candidates.append((limit - used) / 1024 / 1024)
    except (OSError, ValueError):
        pass

    # cgroup v1 fallback
    try:
        with open("/sys/fs/cgroup/memory/memory.limit_in_bytes") as fh:
            limit = int(fh.read().strip())
        with open("/sys/fs/cgroup/memory/memory.usage_in_bytes") as fh:
            used = int(fh.read().strip())
        if limit < (1 << 62):  # sentinel "unlimited" values are huge
            candidates.append((limit - used) / 1024 / 1024)
    except (OSError, ValueError):
        pass

    # Host-level available memory
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    candidates.append(int(line.split()[1]) / 1024)  # kB → MB
                    break
    except OSError:
        pass

    return min(candidates) if candidates else None


def _usable_cpu_count() -> int:
    """CPU count honouring cgroup/affinity limits, falling back to os.cpu_count()."""
    try:
        return max(1, len(os.sched_getaffinity(0)))  # respects cpuset affinity
    except AttributeError:  # pragma: no cover - non-Linux
        return max(1, os.cpu_count() or 1)


def _safe_worker_count(requested: int, n_years: int) -> int:
    """Clamp the requested worker count to what this machine can actually run.

    Bounded by: years to solve, usable CPUs, and (crucially) available RAM at
    ~0.9 GB/worker. On a memory-constrained host (e.g. Streamlit Community Cloud)
    this collapses to 1, forcing the memory-safe serial path.
    """
    workers = max(1, min(requested, n_years, _usable_cpu_count()))

    mem_mb = _available_memory_mb()
    if mem_mb is not None:
        mem_cap = max(1, int(mem_mb // _PER_WORKER_MEM_MB))
        workers = min(workers, mem_cap)
    return workers


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
    scenario_fields: dict,
) -> tuple[int, OptimizationResult]:
    """Solve a single year's LP. Returns (sim_year_idx, result).

    Takes the scenario as a plain dict, not a Scenario instance, and rebuilds it
    here. Sending a Scenario across the process boundary pickles the class *by
    reference*; if Streamlit's file watcher has reloaded ppa.scenario, the stale
    class held by a session_state Scenario no longer matches sys.modules and
    pickling dies with "it is not the same object as ppa.scenario.Scenario". A
    dict is a builtin type with no such identity check; rebuilding from the
    module-level Scenario class sidesteps the whole problem.
    """
    scenario = Scenario(**scenario_fields)
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
    if scenario.optimize_capacity:
        raise ValueError(
            "run_multi_year received a scenario with optimize_capacity=True — "
            "the dispatch simulation needs fixed capacities. Run the sizing LP "
            "first (ppa.sizing.optimize_capacities) and pass the scenario "
            "returned by ppa.sizing.apply_sizing."
        )

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

    def _record(year_idx: int, result: OptimizationResult) -> None:
        nonlocal completed
        results[year_idx] = result
        completed += 1
        if progress_callback is not None:
            progress_callback(completed, n_years, first_sim_year + year_idx)

    workers = _safe_worker_count(max_workers, n_years)
    st.caption(f"Based on available RAM running {n_years} year-simulations with {workers} parallel worker(s) ...")

    if workers <= 1:
        # Serial, in-process. Required on memory-constrained hosts (e.g. Streamlit
        # Community Cloud, ~1 GB): a single solve peaks ~735 MB, so two would not
        # fit and even one *forked* worker would cost parent + child RAM at once
        # and OOM (the "Oh no. Error running app." crash). Running in-process
        # reuses the parent's memory, and single-threaded execution has no
        # shared-heap corruption.
        for idx in range(n_years):
            year_idx, result = _solve_one_year(
                idx,
                first_sim_year + idx,
                timeseries_by_idx[idx],
                dataclasses.asdict(scenario_by_idx[idx]),
            )
            _record(year_idx, result)
        return results  # type: ignore[return-value]

    # ProcessPoolExecutor, not threads: PyPSA/linopy/HiGHS run non-thread-safe C
    # extensions (model build via pandas/xarray, then the HiGHS solver). Running
    # them concurrently in one process corrupts the shared heap — manifesting as
    # `free(): invalid next size` core dumps and stray ArrowStringArray errors.
    # Separate processes = separate heaps = safe true parallelism. The years are
    # independent; the scenario crosses as a plain dict (see _solve_one_year) and
    # the DataFrame/OptimizationResult pickle cleanly.
    #
    # "fork" specifically: spawn/forkserver re-import the __main__ module, which
    # blows up under Streamlit (it runs the app script as __main__, so each worker
    # would re-execute the whole app). fork inherits the interpreter as-is and
    # still isolates each solve in its own process/heap. Windows has no fork, so
    # fall back to spawn there (requires a `if __name__ == "__main__"` guard).
    try:
        mp_context = multiprocessing.get_context("fork")
    except ValueError:  # pragma: no cover - Windows only
        mp_context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp_context) as executor:
        futures = {
            executor.submit(
                _solve_one_year,
                idx,
                first_sim_year + idx,
                timeseries_by_idx[idx],
                dataclasses.asdict(scenario_by_idx[idx]),
            ): idx
            for idx in range(n_years)
        }

        for future in as_completed(futures):
            year_idx, result = future.result()  # propagates exceptions
            _record(year_idx, result)

    return results  # type: ignore[return-value]
