from __future__ import annotations


import pytest

from ppa.multi_year import (
    _degraded_scenario,
    _safe_worker_count,
    _usable_cpu_count,
    run_multi_year,
)
from ppa.scenario import Scenario


def test_degraded_scenario_applies_half_year_head_start():
    scenario = Scenario(
        pv_mw=100.0,
        onsw_mw=100.0,
        bess_mwh=100.0,
        pv_degradation_rate=0.01,
        wind_degradation_rate=0.02,
        bess_degradation_rate=0.03,
    )
    degraded_0 = _degraded_scenario(scenario, year_idx=0)
    # Even "year 0" carries half a year of degradation, per the docstring.
    assert degraded_0.pv_mw == pytest.approx(100.0 * (1 - 0.01) ** 0.5)
    assert degraded_0.onsw_mw == pytest.approx(100.0 * (1 - 0.02) ** 0.5)
    assert degraded_0.bess_mwh == pytest.approx(100.0 * (1 - 0.03) ** 0.5)


def test_degraded_scenario_is_monotonically_decreasing_over_years():
    scenario = Scenario(pv_mw=100.0, pv_degradation_rate=0.01)
    values = [_degraded_scenario(scenario, i).pv_mw for i in range(5)]
    assert values == sorted(values, reverse=True)


def test_usable_cpu_count_is_at_least_one():
    assert _usable_cpu_count() >= 1


def test_safe_worker_count_never_exceeds_years_to_solve():
    workers = _safe_worker_count(requested=8, n_years=2)
    assert workers <= 2


def test_safe_worker_count_never_exceeds_cpu_count():
    workers = _safe_worker_count(requested=1000, n_years=1000)
    assert workers <= _usable_cpu_count()


def test_safe_worker_count_is_at_least_one():
    assert _safe_worker_count(requested=1, n_years=1) >= 1


def test_run_multi_year_rejects_optimize_capacity_scenario(tiny_ts):
    scenario = Scenario(optimize_capacity=True, simulation_years=1)
    with pytest.raises(ValueError, match="optimize_capacity"):
        run_multi_year(
            scenario,
            pv_cf_by_year={2023: tiny_ts["ts_PVGen"]},
            wind_cf_by_year={2023: tiny_ts["ts_WindGen"]},
            prices_by_year={2023: tiny_ts["ts_MktPrice"]},
        )


def test_run_multi_year_serial_two_years_returns_one_result_per_year(
    tiny_ts, monkeypatch
):
    """Exercises run_multi_year's own orchestration (degradation, serial dispatch,
    progress callback) using the tiny 48h fixture in place of a real full-year
    timeseries: build_year_timeseries is stubbed out so each per-year LP solve
    stays fast, since run_multi_year always requests a full 8760h year otherwise."""
    monkeypatch.setattr(
        "ppa.multi_year.build_year_timeseries", lambda **kwargs: tiny_ts
    )

    scenario = Scenario(
        onsw_mw=120.0,
        pv_mw=100.0,
        bess_mw=20.0,
        bess_mwh=80.0,
        ppaload_mw=100.0,
        simulation_years=2,
        first_sim_year=2025,
    )
    pv_cf = tiny_ts["ts_PVGen"]
    wind_cf = tiny_ts["ts_WindGen"]
    prices = tiny_ts["ts_MktPrice"]

    progress_calls = []
    results = run_multi_year(
        scenario,
        pv_cf_by_year={2023: pv_cf},
        wind_cf_by_year={2023: wind_cf},
        prices_by_year={2023: prices},
        first_sim_year=2025,
        max_workers=1,  # force the serial, in-process path
        progress_callback=lambda done, total, year: progress_calls.append(
            (done, total, year)
        ),
    )

    assert len(results) == 2
    assert all(r is not None for r in results)
    assert all(r.solver_status == "ok" for r in results)
    assert len(progress_calls) == 2
    assert progress_calls[-1][0] == 2  # final callback reports both years done
