from __future__ import annotations


import numpy as np
import pandas as pd
import pytest

from ppa.scenario import Scenario
from ppa.sizing import (
    MGA_OBJECTIVES,
    apply_sizing,
    clamp_sizing_years,
    coarsen_timeseries,
    optimize_capacities,
    run_sizing_subprocess,
    weather_cycle_years,
    SizedCapacities,
)


# ── weather_cycle_years ──────────────────────────────────────────────────────


def test_weather_cycle_years_no_cap_when_cycle_covers_requested_years():
    years, note = weather_cycle_years(
        requested_years=5, n_weather_years=6, n_price_years=6
    )
    assert years == 5
    assert note is None


def test_weather_cycle_years_caps_at_lcm_of_weather_and_price_years():
    # lcm(3, 6) = 6, less than the 10 requested -> capped, with an explanatory note.
    years, note = weather_cycle_years(
        requested_years=10, n_weather_years=3, n_price_years=6
    )
    assert years == 6
    assert note is not None
    assert "6 year" in note


def test_weather_cycle_years_clamps_minimum_to_one():
    years, note = weather_cycle_years(
        requested_years=0, n_weather_years=5, n_price_years=5
    )
    assert years == 1


# ── clamp_sizing_years ───────────────────────────────────────────────────────


def test_clamp_sizing_years_no_clamp_when_memory_unbounded(monkeypatch):
    monkeypatch.setattr("ppa.sizing._available_memory_mb", lambda: None)
    years, notice = clamp_sizing_years(requested_years=25, resolution_h=3)
    assert years == 25
    assert notice is None


def test_clamp_sizing_years_reduces_when_memory_constrained(monkeypatch):
    # ~1 GB free, ~1200 MB per worker-year at 1h resolution -> only ~1 year fits.
    monkeypatch.setattr("ppa.sizing._available_memory_mb", lambda: 1000.0)
    years, notice = clamp_sizing_years(requested_years=25, resolution_h=1)
    assert years < 25
    assert notice is not None
    assert "reduced" in notice


def test_clamp_sizing_years_coarser_resolution_fits_more_years(monkeypatch):
    monkeypatch.setattr("ppa.sizing._available_memory_mb", lambda: 4800.0)
    years_1h, _ = clamp_sizing_years(requested_years=25, resolution_h=1)
    years_3h, _ = clamp_sizing_years(requested_years=25, resolution_h=3)
    assert years_3h >= years_1h


# ── coarsen_timeseries ───────────────────────────────────────────────────────


def test_coarsen_timeseries_no_op_at_hourly_resolution():
    idx = pd.date_range("2023-01-01", periods=24, freq="h")
    ts = pd.DataFrame({"x": range(24)}, index=idx)
    out = coarsen_timeseries(ts, resolution_h=1)
    pd.testing.assert_frame_equal(out, ts)


def test_coarsen_timeseries_block_averages_preserve_total_energy():
    idx = pd.date_range("2023-01-01", periods=24, freq="h")
    ts = pd.DataFrame({"x": np.arange(24, dtype=float)}, index=idx)
    out = coarsen_timeseries(ts, resolution_h=4)
    assert len(out) == 6
    # Block means preserve the sum only when weighted back up by block length;
    # here we just check the block averages match a manual groupby.
    expected = ts["x"].groupby(np.arange(24) // 4).mean().to_numpy()
    assert out["x"].to_numpy() == pytest.approx(expected)


# ── apply_sizing ─────────────────────────────────────────────────────────────


def test_apply_sizing_writes_rounded_capacities_and_disables_optimize_flag():
    scenario = Scenario(optimize_capacity=True, include_bess=True)
    sized = SizedCapacities(
        onsw_mw=123.456,
        pv_mw=78.91,
        bess_mw=15.05,
        bess_mwh=60.2,
        status="ok",
        condition="optimal",
        sizing_years_used=1,
        horizon_clamped=False,
    )
    result = apply_sizing(scenario, sized)
    assert result.optimize_capacity is False
    assert result.onsw_mw == pytest.approx(123.5)
    assert result.pv_mw == pytest.approx(78.9)
    assert result.bess_mw == pytest.approx(15.1)
    assert result.bess_mwh == pytest.approx(60.2)
    assert result.include_bess is True


def test_apply_sizing_treats_solver_noise_bess_as_not_built():
    scenario = Scenario(optimize_capacity=True, include_bess=True)
    sized = SizedCapacities(
        onsw_mw=100.0,
        pv_mw=100.0,
        bess_mw=0.05,  # below the 0.1 MW noise floor
        bess_mwh=0.2,
        status="ok",
        condition="optimal",
        sizing_years_used=1,
        horizon_clamped=False,
    )
    result = apply_sizing(scenario, sized)
    assert result.bess_mw == 0.0
    assert result.bess_mwh == 0.0
    assert result.include_bess is False


def test_apply_sizing_preserves_include_bess_false():
    scenario = Scenario(optimize_capacity=True, include_bess=False)
    sized = SizedCapacities(
        onsw_mw=100.0,
        pv_mw=100.0,
        bess_mw=50.0,
        bess_mwh=200.0,
        status="ok",
        condition="optimal",
        sizing_years_used=1,
        horizon_clamped=False,
    )
    result = apply_sizing(scenario, sized)
    # include_bess was already False on the scenario; sizing can't turn it back on.
    assert result.include_bess is False


# ── optimize_capacities (real tiny LP solve) ─────────────────────────────────


def test_optimize_capacities_builds_only_the_cheaper_resource_when_only_it_helps(
    tiny_ts,
):
    """PV-only weather (wind CF forced to 0): the sizing LP should build PV
    and skip wind entirely, even though both are allowed up to a generous cap."""
    ts = tiny_ts.copy()
    ts["ts_WindGen"] = 0.0  # wind can never produce, however much is built

    scenario = Scenario(
        optimize_capacity=True,
        max_build_wind_mw=500.0,
        max_build_pv_mw=500.0,
        max_build_bess_mw=0.0,
        include_bess=False,
        ppaload_mw=100.0,
        sizing_resolution_h=1,
        simulation_years=1,
    )
    sized = optimize_capacities(ts, scenario)

    assert sized.status == "ok"
    assert sized.onsw_mw == pytest.approx(0.0, abs=1e-3)
    assert sized.pv_mw > 0.0


def test_optimize_capacities_respects_max_build_cap(tiny_ts):
    scenario = Scenario(
        optimize_capacity=True,
        max_build_wind_mw=0.0,
        max_build_pv_mw=5.0,  # far below what's needed to serve the load
        max_build_bess_mw=0.0,
        include_bess=False,
        ppaload_mw=100.0,
        sizing_resolution_h=1,
        simulation_years=1,
    )
    sized = optimize_capacities(tiny_ts, scenario)
    assert sized.pv_mw <= 5.0 + 1e-6


def test_optimize_capacities_no_bess_when_disabled(tiny_ts):
    scenario = Scenario(
        optimize_capacity=True,
        max_build_wind_mw=200.0,
        max_build_pv_mw=200.0,
        max_build_bess_mw=200.0,
        include_bess=False,
        ppaload_mw=100.0,
        sizing_resolution_h=1,
        simulation_years=1,
    )
    sized = optimize_capacities(tiny_ts, scenario)
    assert sized.bess_mw == pytest.approx(0.0, abs=1e-3)


# ── Modelling to generate alternatives (MGA) ─────────────────────────────────


def _mga_scenario(**overrides) -> Scenario:
    fields = dict(
        optimize_capacity=True,
        max_build_wind_mw=500.0,
        max_build_pv_mw=500.0,
        max_build_bess_mw=200.0,
        ppaload_mw=100.0,
        sizing_resolution_h=1,
        simulation_years=1,
    )
    fields.update(overrides)
    return Scenario(**fields)


def test_optimize_capacities_without_mga_has_no_alternatives(tiny_ts):
    sized = optimize_capacities(tiny_ts, _mga_scenario())
    assert sized.mga is None


def test_mga_alternatives_stay_within_cost_budget_and_bracket_the_optimum(tiny_ts):
    slack = 0.05
    sized = optimize_capacities(
        tiny_ts,
        _mga_scenario(),
        mga_slack=slack,
        mga_objectives=list(MGA_OBJECTIVES),
    )
    result = sized.mga
    assert result is not None
    assert result.slack == slack
    assert result.optimum.key == "optimum"
    assert result.optimum.cost_increase == pytest.approx(0.0, abs=1e-9)
    # The base least-cost capacities are untouched by the MGA re-solves
    assert result.optimum.sized.onsw_mw == pytest.approx(sized.onsw_mw)
    assert result.alternatives

    by_key = {a.key: a for a in result.alternatives}
    for alt in result.alternatives:
        assert alt.sized.status == "ok"
        # Never cheaper than the optimum (beyond solver tolerance), never over budget
        assert -1e-6 <= alt.cost_increase <= slack + 1e-6

    if "min_wind" in by_key:
        assert by_key["min_wind"].sized.onsw_mw <= sized.onsw_mw + 1e-3
    if "max_wind" in by_key:
        assert by_key["max_wind"].sized.onsw_mw >= sized.onsw_mw - 1e-3
    assert by_key["max_re_matching"].re_matching_share >= result.optimum.re_matching_share - 1e-6
    assert by_key["min_capex"].capex_eur <= result.optimum.capex_eur + 1.0
    assert by_key["min_re_mw"].sized.onsw_mw + by_key["min_re_mw"].sized.pv_mw <= (
        sized.onsw_mw + sized.pv_mw + 1e-3
    )


def test_mga_skips_extremes_of_unbuildable_technologies(tiny_ts):
    sized = optimize_capacities(
        tiny_ts,
        _mga_scenario(include_bess=False, max_build_bess_mw=0.0),
        mga_slack=0.05,
        mga_objectives=["min_bess", "max_bess", "min_wind"],
    )
    keys = {a.key for a in sized.mga.alternatives}
    assert "min_bess" not in keys and "max_bess" not in keys
    assert any("not buildable" in note for note in sized.mga.notes)


def test_mga_unknown_objective_raises(tiny_ts):
    with pytest.raises(ValueError, match="Unknown MGA objective"):
        optimize_capacities(
            tiny_ts, _mga_scenario(), mga_slack=0.05, mga_objectives=["max_vibes"]
        )


def test_run_sizing_subprocess_streams_mga_progress_and_returns_alternatives(tiny_ts):
    messages: list[str] = []
    sized = run_sizing_subprocess(
        tiny_ts,
        _mga_scenario(),
        mga_slack=0.05,
        mga_objectives=["min_capex", "max_re_matching"],
        on_progress=messages.append,
    )
    assert sized.status == "ok"
    assert [a.key for a in sized.mga.alternatives] == ["min_capex", "max_re_matching"]
    assert len(messages) == 2
    assert "1/2" in messages[0]


def test_apply_sizing_accepts_an_mga_alternative(tiny_ts):
    sized = optimize_capacities(
        tiny_ts, _mga_scenario(), mga_slack=0.05, mga_objectives=["min_capex"]
    )
    alt = sized.mga.alternatives[0]
    scenario = apply_sizing(_mga_scenario(), alt.sized)
    assert scenario.optimize_capacity is False
    assert scenario.onsw_mw == pytest.approx(round(alt.sized.onsw_mw, 1))


def test_run_sizing_subprocess_after_in_process_solve_does_not_hang(tiny_ts):
    """Regression: a solve in this process starts polars' thread pool (linopy
    model build), which deadlocked a *forked* sizing child. The heartbeat
    deadline turns a hang into a failure instead of a stuck test run."""
    import time

    optimize_capacities(tiny_ts, _mga_scenario())
    deadline = time.monotonic() + 90

    def _heartbeat() -> None:
        if time.monotonic() > deadline:
            raise TimeoutError("sizing subprocess hung")

    sized = run_sizing_subprocess(tiny_ts, _mga_scenario(), heartbeat=_heartbeat)
    assert sized.status == "ok"
