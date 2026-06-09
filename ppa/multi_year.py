"""Multi-year parallel simulation runner."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

import pandas as pd

from ppa.data.european_data import build_year_timeseries, pick_weather_year
from ppa.network import build_network
from ppa.results import OptimizationResult, extract_results
from ppa.scenario import Scenario
from ppa.solver import solve


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
    base_prices: pd.Series,
    base_price_year: int = 2024,
    first_sim_year: int = 2025,
    max_workers: int = 4,
    progress_callback: Callable[[int, int, int], None] | None = None,
) -> list[OptimizationResult]:
    """
    Run `scenario.simulation_years` independent year-simulations in parallel.

    Weather years are cycled from the keys of `pv_cf_by_year`.
    Market prices are escalated from `base_price_year` using `scenario.price_escalation_rate`.

    Args:
        progress_callback: called as (completed_count, total, sim_year) after each year finishes.

    Returns:
        List of OptimizationResult ordered by simulation year (index 0 = first sim year).
    """
    n_years = scenario.simulation_years
    available_weather_years = sorted(pv_cf_by_year.keys())

    # Pre-build all timeseries on the main thread (fast, avoids pickling large DataFrames)
    timeseries_by_idx: dict[int, pd.DataFrame] = {}
    for idx in range(n_years):
        sim_year = first_sim_year + idx
        weather_year = pick_weather_year(idx, available_weather_years)
        ts = build_year_timeseries(
            sim_year=sim_year,
            weather_year=weather_year,
            ppa_load_mw=scenario.ppaload_mw,
            pv_cf_by_year=pv_cf_by_year,
            wind_cf_by_year=wind_cf_by_year,
            base_prices=base_prices,
            base_price_year=base_price_year,
            price_escalation_rate=scenario.price_escalation_rate,
        )
        timeseries_by_idx[idx] = ts

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
                scenario,
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
