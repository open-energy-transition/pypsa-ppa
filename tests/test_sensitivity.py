from __future__ import annotations

import dataclasses

import pytest

from ppa.financial_model import EnergyInputs, ProjectFinanceInputs, run_project_finance
from ppa.sensitivity import PARAM_BY_FIELD, PARAMS, run_tornado, run_what_if, tornado_to_dataframe


@pytest.fixture
def base_energy() -> EnergyInputs:
    return EnergyInputs(
        onsw_mw=100.0, pv_mw=100.0, bess_mw=20.0, bess_mwh=80.0, load_mw=100.0,
        ppa_gwh=600.0, excess_solar_gwh=50.0, excess_nonsolar_gwh=30.0, penalty_gwh=10.0,
        total_solar_gwh=300.0, total_nonsolar_gwh=400.0,
        sell_solar_price=40.0, sell_nonsolar_price=60.0,
    )


@pytest.fixture
def base_finance() -> ProjectFinanceInputs:
    return ProjectFinanceInputs(model_duration=15, operating_life=10, debt_tenor=8, ppa_tenor=8)


def test_run_what_if_overrides_a_single_field(base_energy, base_finance):
    result = run_what_if(base_energy, base_finance, ppa_tariff=200.0)
    baseline = run_project_finance(base_finance, base_energy)
    assert result.project_irr != baseline.project_irr


def test_run_what_if_does_not_mutate_base_inputs(base_energy, base_finance):
    original_tariff = base_finance.ppa_tariff
    run_what_if(base_energy, base_finance, ppa_tariff=999.0)
    assert base_finance.ppa_tariff == original_tariff


def test_param_catalogue_fields_all_exist_on_inputs(base_finance):
    for p in PARAMS:
        assert hasattr(base_finance, p.field), f"{p.field} missing from ProjectFinanceInputs"


def test_param_by_field_is_indexed_consistently():
    for p in PARAMS:
        assert PARAM_BY_FIELD[p.field] is p


def test_run_tornado_small_subset_returns_rows_sorted_by_swing_descending(base_energy, base_finance):
    subset = [PARAM_BY_FIELD["ppa_tariff"], PARAM_BY_FIELD["corp_tax_rate"], PARAM_BY_FIELD["debt_rate"]]
    rows, base_val, zero_rows = run_tornado(base_energy, base_finance, params=subset)

    swings = [r.swing for r in rows]
    assert swings == sorted(swings, reverse=True)
    assert all(r.swing >= 0 for r in rows)
    assert len(rows) + len(zero_rows) == len(subset)


def test_run_tornado_int_field_stays_integer_at_low_and_high(base_energy, base_finance):
    subset = [PARAM_BY_FIELD["debt_tenor"]]
    rows, _, zero_rows = run_tornado(base_energy, base_finance, params=subset)
    all_rows = rows + zero_rows
    assert len(all_rows) == 1
    row = all_rows[0]
    assert float(row.low_val).is_integer()
    assert float(row.high_val).is_integer()
    assert row.low_val >= 1


def test_run_tornado_base_val_matches_direct_run(base_energy, base_finance):
    subset = [PARAM_BY_FIELD["ppa_tariff"]]
    _, base_val, _ = run_tornado(base_energy, base_finance, params=subset, metric="project_irr")
    direct = run_project_finance(base_finance, base_energy)
    assert base_val == pytest.approx(direct.project_irr)


def test_tornado_to_dataframe_scales_percent_metrics(base_energy, base_finance):
    subset = [PARAM_BY_FIELD["ppa_tariff"]]
    rows, base_val, _ = run_tornado(base_energy, base_finance, params=subset, metric="project_irr")
    df = tornado_to_dataframe(rows, base_val, metric="project_irr")
    if len(df) == 0:
        pytest.skip("ppa_tariff swing below threshold for this fixture")
    assert "Parameter" in df.columns
    assert any("%" in c for c in df.columns)
