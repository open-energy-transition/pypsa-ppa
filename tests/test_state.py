"""Tests for ui/state.py session-state accessors.

`st.session_state` works outside a running Streamlit server (backed by a plain
dict, with a harmless warning), which is what makes these testable at all.
"""
from __future__ import annotations

import dataclasses

import pytest
import streamlit as st

from ppa.scenario import Scenario
from ppa.sizing import SizedCapacities
from ui import state


@pytest.fixture(autouse=True)
def clear_session_state():
    st.session_state.clear()
    yield
    st.session_state.clear()


def test_scenario_round_trip():
    assert state.get_scenario() is None
    assert not state.has_scenario()

    scenario = Scenario(onsw_mw=42.0)
    state.set_scenario(scenario)
    assert state.has_scenario()
    assert state.get_scenario() == scenario


def test_set_scenario_resets_form_widget_keys():
    st.session_state["sf_onsw_mw"] = 999.0
    state.set_scenario(Scenario())
    assert "sf_onsw_mw" not in st.session_state


def test_result_lifecycle_clears_dependent_financial_and_counterfactual():
    st.session_state[state.FINANCIAL_KEY] = "stale-financial"
    st.session_state[state.COUNTERFACTUAL_KEY] = "stale-counterfactual"

    state.set_result("some-result")
    assert state.get_result() == "some-result"
    assert not state.has_financial()
    assert not state.has_counterfactual()


def test_clear_result_removes_result_and_dependents():
    state.set_result("r")
    state.set_financial("f")
    state.set_counterfactual("cf")

    state.clear_result()
    assert not state.has_result()
    assert not state.has_financial()
    assert not state.has_counterfactual()


def test_get_effective_scenario_returns_plain_scenario_when_not_sizing():
    scenario = Scenario(optimize_capacity=False, onsw_mw=50.0)
    state.set_scenario(scenario)
    assert state.get_effective_scenario() == scenario


def test_get_effective_scenario_returns_plain_scenario_when_no_sizing_result_yet():
    scenario = Scenario(optimize_capacity=True)
    state.set_scenario(scenario)
    assert state.get_effective_scenario() == scenario


def test_get_effective_scenario_applies_sized_capacities():
    scenario = Scenario(optimize_capacity=True, include_bess=True)
    state.set_scenario(scenario)
    sized = SizedCapacities(
        onsw_mw=123.0, pv_mw=45.0, bess_mw=10.0, bess_mwh=40.0,
        status="ok", condition="optimal", sizing_years_used=1, horizon_clamped=False,
    )
    state.set_optimized_sizes(sized)

    effective = state.get_effective_scenario()
    assert effective.optimize_capacity is False
    assert effective.onsw_mw == pytest.approx(123.0)
    assert effective.pv_mw == pytest.approx(45.0)


def test_get_scenario_rebuilds_stale_class_instance():
    """Simulates a Streamlit file-watcher reload: a stored instance whose class
    is no longer `is` the current ppa.scenario.Scenario must be rebuilt rather
    than returned as-is (see state.py's docstring on this)."""

    @dataclasses.dataclass
    class _StaleScenario:
        onsw_mw: float = 77.0
        pv_mw: float = 33.0

    st.session_state[state.SCENARIO_KEY] = _StaleScenario()
    rebuilt = state.get_scenario()
    assert type(rebuilt) is Scenario
    assert rebuilt.onsw_mw == 77.0
    assert rebuilt.pv_mw == 33.0
    # The rebuilt instance should now be stored back in session state.
    assert type(st.session_state[state.SCENARIO_KEY]) is Scenario


def test_timeseries_and_case_study_and_multi_year_accessors():
    assert not state.has_timeseries()
    state.set_timeseries("ts-object")
    assert state.get_timeseries() == "ts-object"

    assert state.get_active_case_study_id() is None
    state.set_active_case_study_id("foundation_deal")
    assert state.get_active_case_study_id() == "foundation_deal"

    assert not state.has_multi_year_results()
    state.set_multi_year_results([1, 2, 3])
    assert state.get_multi_year_results() == [1, 2, 3]

    assert not state.has_multi_year_financial()
    state.set_multi_year_financial("myf")
    assert state.get_multi_year_financial() == "myf"

    assert not state.has_project_finance()
    state.set_project_finance("pf")
    assert state.get_project_finance() == "pf"


def test_custom_timeseries_accessors_and_clear():
    assert not state.has_custom_timeseries()
    data = {"price": {2020: "series"}, "pv_cf": {}, "wind_cf": {}}
    state.set_custom_timeseries(data)
    assert state.has_custom_timeseries()
    assert state.get_custom_timeseries() == data

    state.clear_custom_timeseries()
    assert not state.has_custom_timeseries()
    assert state.get_custom_timeseries() is None
