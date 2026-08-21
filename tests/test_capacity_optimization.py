from __future__ import annotations


import numpy as np
import pandas as pd
import pytest

from ppa.scenario import Scenario
from ppa.sizing import (
    apply_sizing,
    clamp_sizing_years,
    coarsen_timeseries,
    optimize_capacities,
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
