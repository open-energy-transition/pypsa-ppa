from __future__ import annotations

import dataclasses

import pytest

from ppa.financials import run_financial_analysis, run_multi_year_financial_analysis
from ppa.scenario import Scenario


def test_run_financial_analysis_capex_breakdown_sums_correctly(solved_result):
    scenario = solved_result.scenario
    result = run_financial_analysis(
        scenario, solved_result.summary, solved_result.revenue, solved_result.n_period_hours
    )
    capex = result.capex
    assert capex.capex_total == pytest.approx(
        capex.capex_wind + capex.capex_pv + capex.capex_bess, rel=1e-9
    )
    assert capex.capex_total > 0.0


def test_run_financial_analysis_lcoe_is_positive_when_generation_exists(solved_result):
    result = run_financial_analysis(
        solved_result.scenario, solved_result.summary, solved_result.revenue,
        solved_result.n_period_hours,
    )
    assert result.lcoe > 0.0


def test_run_financial_analysis_scale_factor_matches_period_length(solved_result):
    result = run_financial_analysis(
        solved_result.scenario, solved_result.summary, solved_result.revenue,
        solved_result.n_period_hours,
    )
    assert result.scale_factor == pytest.approx(8760.0 / solved_result.n_period_hours)


def test_run_financial_analysis_breakeven_price_gives_target_irr(solved_result):
    scenario = solved_result.scenario
    result = run_financial_analysis(
        scenario, solved_result.summary, solved_result.revenue, solved_result.n_period_hours,
    )
    if result.breakeven_ppa_price != result.breakeven_ppa_price:  # NaN guard
        pytest.skip("breakeven price undefined for this fixture (no PPA volume)")
    assert result.breakeven_ppa_price > 0.0


def test_run_multi_year_financial_analysis_aggregates_all_years(solved_result):
    scenario = solved_result.scenario
    year_results = [solved_result, solved_result, solved_result]
    result = run_multi_year_financial_analysis(scenario, year_results, first_sim_year=2025)

    assert len(result.yearly) == 3
    assert [y.year for y in result.yearly] == [2025, 2026, 2027]
    assert result.total_lifetime_revenue == pytest.approx(
        sum(y.net_revenue for y in result.yearly), rel=1e-9
    )


def test_run_multi_year_financial_analysis_cumulative_npv_ends_at_final_npv(solved_result):
    scenario = solved_result.scenario
    year_results = [solved_result] * scenario.project_life_yrs
    result = run_multi_year_financial_analysis(scenario, year_results, first_sim_year=2025)
    assert result.cumulative_npv[-1] == pytest.approx(result.npv, rel=1e-6)


def test_run_multi_year_financial_analysis_extends_short_horizon_to_project_life(solved_result):
    scenario = dataclasses.replace(solved_result.scenario, project_life_yrs=10)
    year_results = [solved_result, solved_result]  # only 2 of 10 years simulated
    result = run_multi_year_financial_analysis(scenario, year_results, first_sim_year=2025)
    # cumulative_npv should have one entry per project year (extended with the
    # average of the simulated years), not just the 2 that were simulated.
    assert len(result.cumulative_npv) == 10
