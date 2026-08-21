from __future__ import annotations

import dataclasses

import pytest

from ppa.counterfactuals import compute_counterfactuals


def test_compute_counterfactuals_ppa_cost_covers_full_load(solved_result, tiny_ts):
    scenario = solved_result.scenario
    result = compute_counterfactuals(tiny_ts, scenario, solved_result)
    assert result.total_load_mwh == pytest.approx(float(tiny_ts["ppaload_mw"].sum()))


def test_compute_counterfactuals_fully_hedged_cal_cost_matches_forward_price(solved_result, tiny_ts):
    scenario = dataclasses.replace(solved_result.scenario, cal_hedge_fraction=1.0)
    result = compute_counterfactuals(tiny_ts, scenario, solved_result)
    assert result.blended_cost == pytest.approx(result.cal_cost)
    assert result.cal_avg_price == pytest.approx(scenario.cal_forward_price)


def test_compute_counterfactuals_zero_hedge_fraction_equals_spot(solved_result, tiny_ts):
    scenario = dataclasses.replace(solved_result.scenario, cal_hedge_fraction=0.0)
    result = compute_counterfactuals(tiny_ts, scenario, solved_result)
    assert result.blended_cost == pytest.approx(result.spot_cost)


def test_compute_counterfactuals_savings_are_internally_consistent(solved_result, tiny_ts):
    result = compute_counterfactuals(tiny_ts, solved_result.scenario, solved_result)
    assert result.ppa_saving_vs_spot == pytest.approx(result.spot_cost - result.ppa_offtaker_cost)
    assert result.ppa_saving_vs_blended == pytest.approx(result.blended_cost - result.ppa_offtaker_cost)


def test_compute_counterfactuals_cumulative_series_end_at_total_cost(solved_result, tiny_ts):
    result = compute_counterfactuals(tiny_ts, solved_result.scenario, solved_result)
    assert result.cumulative_spot.iloc[-1] == pytest.approx(result.spot_cost)
    assert result.cumulative_ppa.iloc[-1] == pytest.approx(result.ppa_offtaker_cost)
    assert result.cumulative_cal.iloc[-1] == pytest.approx(result.cal_cost)


def test_compute_counterfactuals_effective_prices_are_cost_over_volume(solved_result, tiny_ts):
    result = compute_counterfactuals(tiny_ts, solved_result.scenario, solved_result)
    assert result.spot_avg_price == pytest.approx(result.spot_cost / result.total_load_mwh)
    assert result.ppa_effective_price == pytest.approx(
        result.ppa_offtaker_cost / result.total_load_mwh
    )
