from __future__ import annotations

import dataclasses

import streamlit as st

from ppa.data_loader import get_available_days
from ppa.scenario import Scenario
from ui import state


def render_scenario_form(initial: Scenario) -> Scenario:
    """Render all scenario controls and return a new Scenario from widget values."""
    st.subheader("Feature toggles")
    c1, c2, c3 = st.columns(3)
    include_bess = c1.toggle("Include BESS", value=initial.include_bess, key="sf_include_bess")
    enable_market_buy = c2.toggle("Enable market buy", value=initial.enable_market_buy, key="sf_enable_market_buy")
    enable_market_sell = c3.toggle("Enable market sell", value=initial.enable_market_sell, key="sf_enable_market_sell")
    c4, c5, c6 = st.columns(3)
    enable_shortfall = c4.toggle("Enable shortfall allowance", value=initial.enable_shortfall, key="sf_enable_shortfall")
    enable_penalty = c5.toggle("Enable penalty regime", value=initial.enable_penalty, key="sf_enable_penalty")
    run_financial_analysis = c6.toggle("Run financial analysis", value=initial.run_financial_analysis, key="sf_run_financial_analysis")

    with st.expander("Portfolio assets", expanded=True):
        col1, col2 = st.columns(2)
        onsw_mw = col1.slider("Onshore wind (MW)", 0, 500, int(initial.onsw_mw), step=10, key="sf_onsw_mw")
        pv_mw = col2.slider("Solar PV (MWac)", 0, 500, int(initial.pv_mw), step=10, key="sf_pv_mw")
        col3, col4 = st.columns(2)
        bess_mw = col3.slider(
            "BESS power (MW)", 0, 300, int(initial.bess_mw), step=10,
            disabled=not include_bess, key="sf_bess_mw"
        )
        bess_mwh = col4.slider(
            "BESS energy (MWh)", 0, 1200, int(initial.bess_mwh), step=20,
            disabled=not include_bess, key="sf_bess_mwh"
        )

    with st.expander("PPA contract terms", expanded=True):
        col1, col2 = st.columns(2)
        ppaload_mw = col1.number_input("PPA offtake load (MW)", min_value=1.0, max_value=1000.0,
                                        value=float(initial.ppaload_mw), step=10.0, key="sf_ppaload_mw")
        ppa_price = col2.number_input("PPA tariff ($/MWh)", min_value=1.0, max_value=500.0,
                                       value=float(initial.ppa_price), step=5.0, key="sf_ppa_price")
        col3, col4 = st.columns(2)
        required_delivery_share = col3.slider(
            "Required delivery share (%)", 50, 100, int(initial.required_delivery_share * 100),
            step=5, format="%d%%",
            help="Fraction of total contracted load that must be delivered on average.",
            key="sf_required_delivery_share",
        ) / 100.0
        pen_mult = col4.number_input(
            "Penalty multiplier (×tariff)", min_value=1.0, max_value=5.0,
            value=float(initial.pen_mult), step=0.1,
            disabled=not enable_penalty, key="sf_pen_mult",
        )

    with st.expander("Market interaction"):
        col1, col2 = st.columns(2)
        market_buy_share = col1.slider(
            "Market buy cap (% of delivery)", 0, 100,
            int(initial.market_buy_share * 100), step=1, format="%d%%",
            disabled=not enable_market_buy, key="sf_market_buy_share",
        ) / 100.0
        market_spread = col2.number_input(
            "Bid-offer spread ($/MWh)", min_value=0.0, max_value=10.0,
            value=float(initial.market_spread), step=0.05, key="sf_market_spread",
        )

    with st.expander("Financial assumptions"):
        col1, col2, col3 = st.columns(3)
        wind_capex_per_kw = col1.number_input("Wind CAPEX ($/kW)", 500.0, 5000.0,
                                               float(initial.wind_capex_per_kw), 50.0, key="sf_wind_capex")
        pv_capex_per_kw = col2.number_input("PV CAPEX ($/kW)", 200.0, 3000.0,
                                              float(initial.pv_capex_per_kw), 50.0, key="sf_pv_capex")
        bess_capex_per_kwh = col3.number_input("BESS CAPEX ($/kWh)", 100.0, 2000.0,
                                                float(initial.bess_capex_per_kwh), 25.0,
                                                disabled=not include_bess, key="sf_bess_capex")
        col4, col5, col6 = st.columns(3)
        opex_rate = col4.number_input("Annual OPEX (% of CAPEX)", 0.5, 10.0,
                                       float(initial.opex_rate * 100), 0.1, format="%.1f",
                                       key="sf_opex_rate") / 100.0
        discount_rate = col5.number_input("Discount rate / WACC (%)", 1.0, 30.0,
                                           float(initial.discount_rate * 100), 0.5, format="%.1f",
                                           key="sf_discount_rate") / 100.0
        target_irr = col6.number_input("Target IRR (%)", 1.0, 40.0,
                                        float(initial.target_irr * 100), 0.5, format="%.1f",
                                        key="sf_target_irr") / 100.0
        project_life_yrs = st.number_input("Project life (years)", 5, 40,
                                            int(initial.project_life_yrs), 1, key="sf_project_life")

    with st.expander("Counterfactual sourcing"):
        enable_counterfactual = st.toggle(
            "Compare to counterfactual strategies",
            value=initial.enable_counterfactual,
            key="sf_enable_counterfactual",
            help="Compute spot-only and CAL Y+1 forward costs for the offtaker after each run.",
        )
        col1, col2 = st.columns(2)
        cal_forward_price = col1.number_input(
            "CAL Y+1 forward price ($/MWh)",
            min_value=0.0, max_value=500.0,
            value=float(initial.cal_forward_price), step=5.0,
            disabled=not enable_counterfactual, key="sf_cal_forward_price",
            help="Flat baseload forward price for the next calendar year (e.g. ASX Cal 26 Base NSW).",
        )
        cal_hedge_fraction = col2.slider(
            "Hedge fraction (%)", 0, 100,
            int(initial.cal_hedge_fraction * 100),
            step=5, format="%d%%",
            disabled=not enable_counterfactual, key="sf_cal_hedge_fraction",
            help="Share of load hedged at CAL Y+1; remainder sourced at spot.",
        ) / 100.0

    # Chosen day selector (use available days from loaded timeseries)
    ts = state.get_timeseries()
    if ts is not None:
        available_days = get_available_days(ts)
        chosen_day_idx = available_days.index(initial.chosen_day) if initial.chosen_day in available_days else 14
        chosen_day = st.selectbox(
            "Reference day for daily charts", available_days,
            index=chosen_day_idx, key="sf_chosen_day",
        )
    else:
        chosen_day = initial.chosen_day

    return dataclasses.replace(
        initial,
        include_bess=include_bess,
        enable_market_buy=enable_market_buy,
        enable_market_sell=enable_market_sell,
        enable_shortfall=enable_shortfall,
        enable_penalty=enable_penalty,
        run_financial_analysis=run_financial_analysis,
        enable_counterfactual=enable_counterfactual,
        cal_forward_price=float(cal_forward_price),
        cal_hedge_fraction=float(cal_hedge_fraction),
        onsw_mw=float(onsw_mw),
        pv_mw=float(pv_mw),
        bess_mw=float(bess_mw) if include_bess else 0.0,
        bess_mwh=float(bess_mwh) if include_bess else 0.0,
        ppaload_mw=float(ppaload_mw),
        ppa_price=float(ppa_price),
        required_delivery_share=float(required_delivery_share),
        pen_mult=float(pen_mult),
        market_buy_share=float(market_buy_share),
        market_spread=float(market_spread),
        wind_capex_per_kw=float(wind_capex_per_kw),
        pv_capex_per_kw=float(pv_capex_per_kw),
        bess_capex_per_kwh=float(bess_capex_per_kwh),
        opex_rate=float(opex_rate),
        discount_rate=float(discount_rate),
        target_irr=float(target_irr),
        project_life_yrs=int(project_life_yrs),
        chosen_day=str(chosen_day),
    )
