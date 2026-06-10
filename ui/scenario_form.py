from __future__ import annotations

import dataclasses

import pandas as pd
import streamlit as st

from ppa.data_loader import get_available_days
from ppa.industrial_profiles import PROFILE_INFO, PROFILE_KEYS
from ppa.scenario import Scenario
from ui import state

max_cap_per_technology = 500
max_bes_hours = 8

def render_scenario_form(initial: Scenario) -> Scenario:
    """Render all scenario controls and return a new Scenario from widget values."""
    st.subheader("Feature toggles")
    cols = st.columns(4)
    include_bess = cols[0].toggle("Include BESS", value=initial.include_bess, key="sf_include_bess")
    enable_market_buy = cols[1].toggle("Enable market buy", value=initial.enable_market_buy, key="sf_enable_market_buy")
    enable_market_sell = cols[2].toggle("Enable market sell", value=initial.enable_market_sell, key="sf_enable_market_sell")
    enable_shortfall = cols[3].toggle("Enable shortfall allowance", value=initial.enable_shortfall, key="sf_enable_shortfall")
    cols = st.columns(4)
    enable_penalty = cols[0].toggle("Enable penalty regime", value=initial.enable_penalty, key="sf_enable_penalty")
    run_financial_analysis = cols[1].toggle("Run financial analysis", value=initial.run_financial_analysis, key="sf_run_financial_analysis")

    with st.expander("Portfolio assets", expanded=True):
        cols = st.columns(4)
        onsw_mw = cols[0].slider("Onshore wind (MW)", 0, max_cap_per_technology, int(initial.onsw_mw), step=10, key="sf_onsw_mw")
        pv_mw = cols[1].slider("Solar PV (MWac)", 0, max_cap_per_technology, int(initial.pv_mw), step=10, key="sf_pv_mw")
        bess_mw = cols[2].slider(
            "BESS power (MW)", 0, max_cap_per_technology, int(initial.bess_mw), step=10,
            key="sf_bess_mw"
        )
        bess_mwh = cols[3].slider(
            "BESS energy (MWh)", 0, max_cap_per_technology*max_bes_hours, int(initial.bess_mwh), step=20,
            key="sf_bess_mwh"
        )

    with st.expander("PPA contract terms", expanded=True):
        cols = st.columns(4)
        ppaload_mw = cols[0].number_input("PPA offtake load (MW)", min_value=1.0, max_value=1000.0,
                                           value=float(initial.ppaload_mw), step=10.0, key="sf_ppaload_mw",
                                           help="Peak rated MW. The load profile shapes how much of this is demanded each hour.")
        ppa_price = cols[1].number_input("PPA tariff ($/MWh)", min_value=1.0, max_value=500.0,
                                          value=float(initial.ppa_price), step=5.0, key="sf_ppa_price")

        # ── Load profile selector ─────────────────────────────────────────────
        st.markdown("**Offtaker load profile**")
        _profile_labels = [f"{PROFILE_INFO[k]['icon']} {PROFILE_INFO[k]['label']}" for k in PROFILE_KEYS]
        _current_idx = PROFILE_KEYS.index(initial.load_profile) if initial.load_profile in PROFILE_KEYS else 0
        cols = st.columns([1, 3])
        _selected_label = cols[0].selectbox(
            "Profile type",
            options=_profile_labels,
            index=_current_idx,
            key="sf_load_profile",
            label_visibility="collapsed",
        )
        load_profile = PROFILE_KEYS[_profile_labels.index(_selected_label)]
        _info = PROFILE_INFO[load_profile]
        cols[1].caption(
            f"**Typical load factor: {_info['typical_lf']}** — {_info['description']}"
        )
        required_delivery_share = cols[2].slider(
            "Required delivery share (%)", 50, 100, int(initial.required_delivery_share * 100),
            step=5, format="%d%%",
            help="Fraction of total contracted load that must be delivered on average.",
            key="sf_required_delivery_share",
        ) / 100.0
        pen_mult = cols[3].number_input(
            "Penalty multiplier (×tariff)", min_value=1.0, max_value=5.0,
            value=float(initial.pen_mult), step=0.1,
            key="sf_pen_mult",
        )

    with st.expander("Market interaction", expanded=True):
        cols = st.columns(4)
        market_buy_share = cols[0].slider(
            "Market buy cap (% of delivery)", 0, 100,
            int(initial.market_buy_share * 100), step=1, format="%d%%",
            key="sf_market_buy_share",
        ) / 100.0
        market_spread = cols[1].number_input(
            "Bid-offer spread ($/MWh)", min_value=0.0, max_value=10.0,
            value=float(initial.market_spread), step=0.05, key="sf_market_spread",
        )

    with st.expander("Financial assumptions", expanded=True):
        cols = st.columns(4)
        wind_capex_per_kw = cols[0].number_input("Wind CAPEX ($/kW)", 500.0, 5000.0,
                                                   float(initial.wind_capex_per_kw), 50.0, key="sf_wind_capex")
        pv_capex_per_kw = cols[1].number_input("PV CAPEX ($/kW)", 200.0, 3000.0,
                                              float(initial.pv_capex_per_kw), 50.0, key="sf_pv_capex")
        bess_capex_per_kwh = cols[2].number_input("BESS CAPEX ($/kWh)", 100.0, 2000.0,
                                                float(initial.bess_capex_per_kwh), 25.0,
                                                key="sf_bess_capex")
        opex_rate = cols[3].number_input("Annual OPEX (% of CAPEX)", 0.5, 10.0,
                                       float(initial.opex_rate * 100), 0.1, format="%.1f",
                                       key="sf_opex_rate") / 100.0
        cols = st.columns(4)
        discount_rate = cols[0].number_input("Discount rate / WACC (%)", 1.0, 30.0,
                                           float(initial.discount_rate * 100), 0.5, format="%.1f",
                                           key="sf_discount_rate") / 100.0
        target_irr = cols[1].number_input("Target IRR (%)", 1.0, 40.0,
                                        float(initial.target_irr * 100), 0.5, format="%.1f",
                                        key="sf_target_irr") / 100.0
        project_life_yrs = cols[3].number_input("Project life (years)", 5, 40,
                                            int(initial.project_life_yrs), 1, key="sf_project_life")

    with st.expander("Project Location", expanded=True):
        cols = st.columns([1, 1, 2])
        lat = cols[0].number_input(
            "Latitude", -90.0, 90.0, float(initial.lat), 0.01, format="%.2f", key="sf_lat",
            help="Decimal degrees N. Used to fetch renewables.ninja CF profiles.",
        )
        lon = cols[1].number_input(
            "Longitude", -180.0, 180.0, float(initial.lon), 0.01, format="%.2f", key="sf_lon",
            help="Decimal degrees E.",
        )
        loc_df = pd.DataFrame({"lat": [lat], "lon": [lon]})
        cols[2].map(loc_df, zoom=4)

    with st.expander("Simulation", expanded=True):
        cols = st.columns(4)
        simulation_years = int(cols[0].number_input(
            "Simulation years", 1, 40, int(initial.simulation_years), 1, key="sf_sim_years",
            help="1 = single full-year run; >1 = multi-year parallel simulation.",
        ))
        first_sim_year = int(cols[1].number_input(
            "First simulation year", 2024, 2040, int(initial.first_sim_year), 1,
            key="sf_first_sim_year",
        ))
        price_escalation_rate = cols[2].number_input(
            "Price escalation (%/yr)", 0.0, 10.0,
            float(initial.price_escalation_rate * 100), 0.1, format="%.1f",
            key="sf_escalation",
            help="Annual compound escalation applied to 2024 ENTSO-E base prices.",
        ) / 100.0

        st.caption("Technology degradation (compound annual, applied from year 2 onward)")
        cols = st.columns(4)
        pv_degradation_rate = cols[0].number_input(
            "PV (%/yr)", 0.0, 5.0, float(initial.pv_degradation_rate * 100),
            0.05, format="%.2f", key="sf_pv_deg",
        ) / 100.0
        wind_degradation_rate = cols[1].number_input(
            "Wind (%/yr)", 0.0, 5.0, float(initial.wind_degradation_rate * 100),
            0.05, format="%.2f", key="sf_wind_deg",
        ) / 100.0
        bess_degradation_rate = cols[2].number_input(
            "BESS (%/yr)", 0.0, 10.0, float(initial.bess_degradation_rate * 100),
            0.1, format="%.1f", key="sf_bess_deg",
        ) / 100.0

    with st.expander("Counterfactual sourcing", expanded=True):
        cols = st.columns(4)
        enable_counterfactual = cols[0].toggle(
            "Compare to counterfactual strategies",
            value=initial.enable_counterfactual,
            key="sf_enable_counterfactual",
            help="Compute spot-only and CAL Y+1 forward costs for the offtaker after each run.",
        )
        cal_forward_price = cols[1].number_input(
            "CAL Y+1 forward price ($/MWh)",
            min_value=0.0, max_value=500.0,
            value=float(initial.cal_forward_price), step=5.0,
            key="sf_cal_forward_price",
            help="Flat baseload forward price for the next calendar year (e.g. ASX Cal 26 Base NSW).",
        )
        cal_hedge_fraction = cols[2].slider(
            "Hedge fraction (%)", 0, 100,
            int(initial.cal_hedge_fraction * 100),
            step=5, format="%d%%",
            key="sf_cal_hedge_fraction",
            help="Share of load hedged at CAL Y+1; remainder sourced at spot.",
        ) / 100.0

    with st.expander("Reference day selection", expanded=True):
        cols = st.columns(4)
        # Chosen day selector (use available days from loaded timeseries)
        ts = state.get_timeseries()
        if ts is not None:
            available_days = get_available_days(ts)
            chosen_day_idx = available_days.index(initial.chosen_day) if initial.chosen_day in available_days else 14
            chosen_day = cols[0].selectbox(
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
        load_profile=load_profile,
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
        lat=float(lat),
        lon=float(lon),
        simulation_years=simulation_years,
        first_sim_year=first_sim_year,
        price_escalation_rate=float(price_escalation_rate),
        pv_degradation_rate=float(pv_degradation_rate),
        wind_degradation_rate=float(wind_degradation_rate),
        bess_degradation_rate=float(bess_degradation_rate),
    )
