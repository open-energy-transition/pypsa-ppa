from __future__ import annotations

from typing import TYPE_CHECKING

import streamlit as st

if TYPE_CHECKING:
    import pandas as pd
    from ppa.scenario import Scenario
    from ppa.results import OptimizationResult
    from ppa.financials import FinancialResult, MultiYearFinancialResult
    from ppa.counterfactuals import CounterfactualResult

SCENARIO_KEY = "scenario"
RESULT_KEY = "optimization_result"
FINANCIAL_KEY = "financial_result"
COUNTERFACTUAL_KEY = "counterfactual_result"
TIMESERIES_KEY = "timeseries"
ACTIVE_CASE_STUDY_KEY = "active_case_study_id"
MULTI_YEAR_RESULTS_KEY = "multi_year_results"
MULTI_YEAR_FINANCIAL_KEY = "multi_year_financial"
PROJECT_FINANCE_KEY = "project_finance_result"
OPTIMIZED_SIZES_KEY = "optimized_sizes"
CUSTOM_TIMESERIES_KEY = "custom_timeseries"


def get_scenario() -> "Scenario | None":
    s = st.session_state.get(SCENARIO_KEY)
    if s is None:
        return None

    from ppa.scenario import Scenario as _Scenario

    if s.__class__ is not _Scenario:
        # The stored instance predates a code reload (Streamlit's file watcher
        # re-imports ppa.scenario when it changes on disk): it may lack newly
        # added fields (AttributeError on access) and its stale class identity
        # breaks pickling into worker processes. Rebuild it from the current
        # class, dropping removed fields and filling new ones with defaults.
        import dataclasses as _dc

        current_fields = {f.name for f in _dc.fields(_Scenario)}
        data = {k: v for k, v in _dc.asdict(s).items() if k in current_fields}
        s = _Scenario(**data)
        st.session_state[SCENARIO_KEY] = s
    return s


_SCENARIO_FORM_KEYS = [
    "sf_include_bess",
    "sf_enable_market_buy",
    "sf_enable_market_sell",
    "sf_enable_shortfall",
    "sf_enable_penalty",
    "sf_run_financial_analysis",
    "sf_enable_counterfactual",
    "sf_onsw_mw",
    "sf_pv_mw",
    "sf_bess_mw",
    "sf_bess_mwh",
    "sf_ppaload_mw",
    "sf_ppa_price",
    "sf_required_delivery_share",
    "sf_pen_mult",
    "sf_market_buy_share",
    "sf_market_spread",
    "sf_wind_capex",
    "sf_pv_capex",
    "sf_bess_capex",
    "sf_opex_rate",
    "sf_discount_rate",
    "sf_target_irr",
    "sf_project_life",
    "sf_cal_forward_price",
    "sf_cal_hedge_fraction",
    "sf_chosen_day",
    "sf_lat",
    "sf_lon",
    "sf_sim_years",
    "sf_first_sim_year",
    "sf_escalation",
    "sf_pv_deg",
    "sf_wind_deg",
    "sf_bess_deg",
    "sf_sizing_mode",
    "sf_max_build_wind",
    "sf_max_build_pv",
    "sf_max_build_bess",
    "sf_sizing_resolution",
]


def get_effective_scenario() -> "Scenario | None":
    """The scenario as actually simulated: optimized capacities applied.

    After a capacity-sizing run the session scenario deliberately keeps the
    user's slider values and `optimize_capacity=True` (so re-runs re-size),
    while the dispatch results were produced with the sized fleet. Any tab that
    combines scenario capacities with result-derived values (capacity factors,
    BESS SoC/cycles, CAPEX breakdowns) must read this accessor, not
    `get_scenario`, or the numbers won't match the dispatch.
    """
    s = get_scenario()
    if s is None or not s.optimize_capacity:
        return s
    sized = get_optimized_sizes()
    if sized is None:
        return s
    from ppa.sizing import apply_sizing

    return apply_sizing(s, sized)


def set_scenario(s: "Scenario") -> None:
    st.session_state[SCENARIO_KEY] = s
    # Reset form widget keys so the form re-initialises from the new scenario values
    for key in _SCENARIO_FORM_KEYS:
        st.session_state.pop(key, None)


def has_scenario() -> bool:
    return SCENARIO_KEY in st.session_state


def get_result() -> "OptimizationResult | None":
    return st.session_state.get(RESULT_KEY)


def set_result(r: "OptimizationResult") -> None:
    st.session_state[RESULT_KEY] = r
    st.session_state.pop(FINANCIAL_KEY, None)
    st.session_state.pop(COUNTERFACTUAL_KEY, None)


def has_result() -> bool:
    return RESULT_KEY in st.session_state


def clear_result() -> None:
    st.session_state.pop(RESULT_KEY, None)
    st.session_state.pop(FINANCIAL_KEY, None)
    st.session_state.pop(COUNTERFACTUAL_KEY, None)


def get_financial() -> "FinancialResult | None":
    return st.session_state.get(FINANCIAL_KEY)


def set_financial(f: "FinancialResult") -> None:
    st.session_state[FINANCIAL_KEY] = f


def has_financial() -> bool:
    return FINANCIAL_KEY in st.session_state


def get_counterfactual() -> "CounterfactualResult | None":
    return st.session_state.get(COUNTERFACTUAL_KEY)


def set_counterfactual(cf: "CounterfactualResult") -> None:
    st.session_state[COUNTERFACTUAL_KEY] = cf


def has_counterfactual() -> bool:
    return COUNTERFACTUAL_KEY in st.session_state


def get_timeseries() -> "pd.DataFrame | None":
    return st.session_state.get(TIMESERIES_KEY)


def set_timeseries(ts: "pd.DataFrame") -> None:
    st.session_state[TIMESERIES_KEY] = ts


def has_timeseries() -> bool:
    return TIMESERIES_KEY in st.session_state


def get_active_case_study_id() -> str | None:
    return st.session_state.get(ACTIVE_CASE_STUDY_KEY)


def set_active_case_study_id(cs_id: str) -> None:
    st.session_state[ACTIVE_CASE_STUDY_KEY] = cs_id


def get_multi_year_results() -> "list | None":
    return st.session_state.get(MULTI_YEAR_RESULTS_KEY)


def set_multi_year_results(results: list) -> None:
    st.session_state[MULTI_YEAR_RESULTS_KEY] = results


def has_multi_year_results() -> bool:
    return MULTI_YEAR_RESULTS_KEY in st.session_state


def get_multi_year_financial() -> "MultiYearFinancialResult | None":
    return st.session_state.get(MULTI_YEAR_FINANCIAL_KEY)


def set_multi_year_financial(fin: "MultiYearFinancialResult") -> None:
    st.session_state[MULTI_YEAR_FINANCIAL_KEY] = fin


def has_multi_year_financial() -> bool:
    return MULTI_YEAR_FINANCIAL_KEY in st.session_state


def get_optimized_sizes() -> "object | None":
    return st.session_state.get(OPTIMIZED_SIZES_KEY)


def set_optimized_sizes(sized: "object") -> None:
    st.session_state[OPTIMIZED_SIZES_KEY] = sized


def has_optimized_sizes() -> bool:
    return OPTIMIZED_SIZES_KEY in st.session_state


def get_custom_timeseries() -> "dict[str, dict[int, pd.Series]] | None":
    """User-uploaded price/PV-CF/wind-CF overrides, keyed by weather year.

    Shape: ``{"price": {year: Series}, "pv_cf": {year: Series}, "wind_cf": {year: Series}}``.
    Only years present here override the downloaded/cached data for that series;
    other years keep using cache as usual. Session-only: never written to disk.
    """
    return st.session_state.get(CUSTOM_TIMESERIES_KEY)


def set_custom_timeseries(data: "dict[str, dict[int, pd.Series]]") -> None:
    st.session_state[CUSTOM_TIMESERIES_KEY] = data


def has_custom_timeseries() -> bool:
    return bool(st.session_state.get(CUSTOM_TIMESERIES_KEY))


def clear_custom_timeseries() -> None:
    st.session_state.pop(CUSTOM_TIMESERIES_KEY, None)


def get_project_finance() -> "object | None":
    return st.session_state.get(PROJECT_FINANCE_KEY)


def set_project_finance(r: "object") -> None:
    st.session_state[PROJECT_FINANCE_KEY] = r


def has_project_finance() -> bool:
    return PROJECT_FINANCE_KEY in st.session_state
