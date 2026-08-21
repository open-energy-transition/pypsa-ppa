from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from ppa.financial_model import (
    EnergyInputs,
    ProjectFinanceInputs,
    energy_inputs_from_result,
    energy_inputs_from_results,
    project_finance_inputs_from_scenario,
    run_project_finance,
)
from ppa.scenario import Scenario


@pytest.fixture
def simple_energy() -> EnergyInputs:
    return EnergyInputs(
        onsw_mw=100.0,
        pv_mw=100.0,
        bess_mw=20.0,
        bess_mwh=80.0,
        load_mw=100.0,
        ppa_gwh=600.0,
        excess_solar_gwh=50.0,
        excess_nonsolar_gwh=30.0,
        penalty_gwh=10.0,
        total_solar_gwh=300.0,
        total_nonsolar_gwh=400.0,
        sell_solar_price=40.0,
        sell_nonsolar_price=60.0,
    )


def test_run_project_finance_balance_sheet_reconciles(simple_energy, pf_inputs):
    result = run_project_finance(pf_inputs, simple_energy)
    # assets = liabilities + equity in every period, to numerical tolerance.
    assert result.max_bs_check < 1e-6


def test_run_project_finance_gearing_within_bounds(simple_energy, pf_inputs):
    result = run_project_finance(pf_inputs, simple_energy)
    assert 0.0 <= result.gearing <= 1.0


def test_run_project_finance_dscr_meets_or_exceeds_target(simple_energy, pf_inputs):
    result = run_project_finance(pf_inputs, simple_energy)
    if not np.isnan(result.min_dscr):
        # DSCR sculpting targets debt service = CFADS/DSCR, so min DSCR should
        # sit at or above the more conservative (uncontracted) target, allowing
        # for the min() across contracted/uncontracted blending.
        assert (
            result.min_dscr
            >= min(pf_inputs.dscr_contracted, pf_inputs.dscr_uncontracted) - 0.05
        )


def test_run_project_finance_devex_is_equity_funded_only(simple_energy, pf_inputs):
    result = run_project_finance(pf_inputs, simple_energy)
    fid_idx = pf_inputs.fid_period - 1
    devex_at_fid = result.schedule["devex"][fid_idx]
    debt_draw_at_fid = result.schedule["debt_draw"][fid_idx]
    assert devex_at_fid > 0.0
    # Devex is never funded by debt: whatever debt is drawn at FID funds capex only.
    capex_at_fid = result.schedule["capex"][fid_idx]
    assert debt_draw_at_fid <= capex_at_fid + 1e-6


def test_run_project_finance_zero_capacity_gives_nan_or_zero_metrics():
    zero_energy = EnergyInputs(
        onsw_mw=0.0,
        pv_mw=0.0,
        bess_mw=0.0,
        bess_mwh=0.0,
        load_mw=0.0,
        ppa_gwh=0.0,
        excess_solar_gwh=0.0,
        excess_nonsolar_gwh=0.0,
        penalty_gwh=0.0,
        total_solar_gwh=0.0,
        total_nonsolar_gwh=0.0,
        sell_solar_price=0.0,
        sell_nonsolar_price=0.0,
    )
    inputs = ProjectFinanceInputs(
        model_duration=10, operating_life=5, debt_tenor=5, ppa_tenor=5
    )
    result = run_project_finance(inputs, zero_energy)
    assert result.total_capex == pytest.approx(0.0)
    assert result.max_bs_check < 1e-6


def test_run_project_finance_higher_ppa_tariff_improves_irr(simple_energy, pf_inputs):
    low = run_project_finance(
        dataclasses.replace(pf_inputs, ppa_tariff=80.0), simple_energy
    )
    high = run_project_finance(
        dataclasses.replace(pf_inputs, ppa_tariff=150.0), simple_energy
    )
    assert high.project_irr > low.project_irr


def test_run_project_finance_skip_merchant_escalation_when_disabled(
    simple_energy, pf_inputs
):
    inputs = dataclasses.replace(pf_inputs, escalate_merchant_prices=False)
    result = run_project_finance(inputs, simple_energy)
    merchant_solar_prices = result.schedule["price_merchant_solar"]
    ops_mask = result.schedule["ops_flag"] > 0
    # With escalation disabled, the merchant price should be flat across all
    # operating periods (no solar_price_inflation compounding).
    active = merchant_solar_prices[ops_mask]
    assert np.allclose(active, active[0])


def test_project_finance_inputs_from_scenario_carries_over_costs():
    scenario = Scenario(
        wind_capex_per_kw=1500.0,
        pv_capex_per_kw=800.0,
        bess_capex_per_kwh=400.0,
        ppa_price=110.0,
        pen_mult=1.8,
        discount_rate=0.07,
    )
    pf = project_finance_inputs_from_scenario(scenario)
    assert pf.onsw_build_cost == pytest.approx(1.5)
    assert pf.pv_build_cost == pytest.approx(0.8)
    assert pf.bess_build_cost == pytest.approx(0.4)
    assert pf.ppa_tariff == pytest.approx(110.0)
    assert pf.penalty_multiple == pytest.approx(1.8)
    assert pf.discount_rate == pytest.approx(0.07)


def test_energy_inputs_from_result_splits_solar_and_nonsolar_hours(solved_result):
    e = energy_inputs_from_result(solved_result, annualise=False)
    assert e.onsw_mw == solved_result.scenario.onsw_mw
    assert e.pv_mw == solved_result.scenario.pv_mw
    assert e.ppa_gwh >= 0.0
    assert e.total_solar_gwh >= 0.0
    assert e.total_nonsolar_gwh >= 0.0


def test_energy_inputs_from_result_annualises_by_default(solved_result):
    not_annualised = energy_inputs_from_result(solved_result, annualise=False)
    annualised = energy_inputs_from_result(solved_result, annualise=True)
    scale = 8760.0 / solved_result.n_period_hours
    assert annualised.ppa_gwh == pytest.approx(not_annualised.ppa_gwh * scale, rel=1e-6)


def test_energy_inputs_from_results_averages_across_years(solved_result):
    combined = energy_inputs_from_results([solved_result, solved_result])
    single = energy_inputs_from_result(solved_result)
    # Averaging the same result with itself must reproduce it exactly.
    assert combined.ppa_gwh == pytest.approx(single.ppa_gwh)
    assert combined.total_solar_gwh == pytest.approx(single.total_solar_gwh)


def test_energy_inputs_from_results_raises_on_empty_list():
    with pytest.raises(ValueError):
        energy_inputs_from_results([])
