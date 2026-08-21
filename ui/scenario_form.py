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
    st.subheader("Capacity sizing approach")
    sizing_mode = st.radio(
        "How should asset capacities be determined?",
        options=["Specify asset capacities manually", "Optimize asset capacities"],
        index=1 if initial.optimize_capacity else 0,
        key="sf_sizing_mode",
        horizontal=True,
        help=(
            "Optimize: let PyPSA size wind, solar and BESS together with dispatch "
            "(least-cost portfolio to serve the PPA), up to the max build limits "
            "you set below. BESS duration is fixed at the MWh/MW ratio you choose."
        ),
    )
    optimize_capacity = sizing_mode == "Optimize asset capacities"

    st.subheader("Feature toggles")

    cols = st.columns(4)

    include_bess = cols[0].toggle(
        "Include BESS", value=initial.include_bess, key="sf_include_bess"
    )
    enable_market_buy = cols[1].toggle(
        "Enable market buy", value=initial.enable_market_buy, key="sf_enable_market_buy"
    )
    enable_market_sell = cols[2].toggle(
        "Enable market sell",
        value=initial.enable_market_sell,
        key="sf_enable_market_sell",
    )
    enable_shortfall = cols[3].toggle(
        "Enable shortfall allowance",
        value=initial.enable_shortfall,
        key="sf_enable_shortfall",
    )

    cols = st.columns(4)
    enable_penalty = cols[0].toggle(
        "Enable penalty regime", value=initial.enable_penalty, key="sf_enable_penalty"
    )
    run_financial_analysis = cols[1].toggle(
        "Run financial analysis",
        value=initial.run_financial_analysis,
        key="sf_run_financial_analysis",
    )

    if optimize_capacity:
        with st.expander("Capacity optimization settings", expanded=True):
            st.info(
                "⚡ **Capacity optimization is ON**: the optimizer sizes each "
                "technology up to its max build limit below; BESS duration is "
                "fixed at the MWh/MW ratio you set."
            )
            cols = st.columns(4)
            max_build_wind_mw = cols[0].number_input(
                "Max wind build (MW)",
                0.0,
                10_000.0,
                float(initial.max_build_wind_mw),
                50.0,
                key="sf_max_build_wind",
            )
            max_build_pv_mw = cols[1].number_input(
                "Max solar build (MW)",
                0.0,
                10_000.0,
                float(initial.max_build_pv_mw),
                50.0,
                key="sf_max_build_pv",
            )
            max_build_bess_mw = cols[2].number_input(
                "Max BESS build (MW)",
                0.0,
                10_000.0,
                float(initial.max_build_bess_mw),
                50.0,
                key="sf_max_build_bess",
            )
            _res_options = [1, 2, 3, 4, 6]
            _res_idx = (
                _res_options.index(int(initial.sizing_resolution_h))
                if int(initial.sizing_resolution_h) in _res_options
                else _res_options.index(3)
            )
            sizing_resolution_h = cols[3].selectbox(
                "Sizing LP resolution (h)",
                _res_options,
                index=_res_idx,
                key="sf_sizing_resolution",
                help=(
                    "Time resolution of the capacity-sizing LP only. Coarser "
                    "blocks (e.g. 3h) solve much faster and use less memory; the "
                    "sized portfolio is then always re-simulated at hourly "
                    "resolution for dispatch and financials."
                ),
            )
            bess_mwh = st.slider(
                "BESS energy (MWh)",
                0,
                max_cap_per_technology * max_bes_hours,
                int(initial.bess_mwh),
                step=20,
                key="sf_bess_mwh",
                help="Only the MWh/MW ratio (duration) is used by the optimizer.",
            )
        onsw_mw = initial.onsw_mw
        pv_mw = initial.pv_mw
        bess_mw = initial.bess_mw
    else:
        max_build_wind_mw = initial.max_build_wind_mw
        max_build_pv_mw = initial.max_build_pv_mw
        max_build_bess_mw = initial.max_build_bess_mw
        sizing_resolution_h = initial.sizing_resolution_h

        with st.expander("Portfolio assets", expanded=True):
            cols = st.columns(4)
            onsw_mw = cols[0].slider(
                "Onshore wind (MW)",
                0,
                max_cap_per_technology,
                int(initial.onsw_mw),
                step=10,
                key="sf_onsw_mw",
            )
            pv_mw = cols[1].slider(
                "Solar PV (MWac)",
                0,
                max_cap_per_technology,
                int(initial.pv_mw),
                step=10,
                key="sf_pv_mw",
            )
            bess_mw = cols[2].slider(
                "BESS power (MW)",
                0,
                max_cap_per_technology,
                int(initial.bess_mw),
                step=10,
                key="sf_bess_mw",
            )
            bess_mwh = cols[3].slider(
                "BESS energy (MWh)",
                0,
                max_cap_per_technology * max_bes_hours,
                int(initial.bess_mwh),
                step=20,
                key="sf_bess_mwh",
            )

    with st.expander("PPA contract terms", expanded=True):
        cols = st.columns(4)
        ppaload_mw = cols[0].number_input(
            "PPA offtake load (MW)",
            min_value=1.0,
            max_value=1000.0,
            value=float(initial.ppaload_mw),
            step=10.0,
            key="sf_ppaload_mw",
            help="Peak rated MW. The load profile shapes how much of this is demanded each hour.",
        )
        ppa_price = cols[1].number_input(
            "PPA tariff (€/MWh)",
            min_value=1.0,
            max_value=500.0,
            value=float(initial.ppa_price),
            step=5.0,
            key="sf_ppa_price",
        )
        required_delivery_share = (
            cols[2].slider(
                "Required delivery share (%)",
                50,
                100,
                int(initial.required_delivery_share * 100),
                step=1,
                format="%d%%",
                help="Fraction of total contracted load that must be delivered on average.",
                key="sf_required_delivery_share",
            )
            / 100.0
        )
        pen_mult = cols[3].number_input(
            "Penalty multiplier (×tariff)",
            min_value=1.0,
            max_value=5.0,
            value=float(initial.pen_mult),
            step=0.1,
            key="sf_pen_mult",
        )

        # ── Load profile selector ─────────────────────────────────────────────
        st.markdown("**Offtaker load profile**")
        _profile_labels = [
            f"{PROFILE_INFO[k]['icon']} {PROFILE_INFO[k]['label']}"
            for k in PROFILE_KEYS
        ]
        _current_idx = (
            PROFILE_KEYS.index(initial.load_profile)
            if initial.load_profile in PROFILE_KEYS
            else 0
        )

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
            f"**Typical load factor: {_info['typical_lf']}**: {_info['description']}"
        )

    with st.expander("Advanced options", expanded=False):
        st.markdown("#### Market interaction")
        cols = st.columns(4)
        market_buy_share = (
            cols[0].slider(
                "Market buy cap (% of delivery)",
                0,
                100,
                int(initial.market_buy_share * 100),
                step=1,
                format="%d%%",
                key="sf_market_buy_share",
            )
            / 100.0
        )
        market_spread = cols[1].number_input(
            "Bid-offer spread (€/MWh)",
            min_value=0.0,
            max_value=10.0,
            value=float(initial.market_spread),
            step=0.05,
            key="sf_market_spread",
        )

        st.divider()
        st.markdown("#### Financial assumptions")
        cols = st.columns(4)
        wind_capex_per_kw = cols[0].number_input(
            "Wind CAPEX ($/kW)",
            500.0,
            5000.0,
            float(initial.wind_capex_per_kw),
            50.0,
            key="sf_wind_capex",
        )
        pv_capex_per_kw = cols[1].number_input(
            "PV CAPEX ($/kW)",
            200.0,
            3000.0,
            float(initial.pv_capex_per_kw),
            50.0,
            key="sf_pv_capex",
        )
        bess_capex_per_kwh = cols[2].number_input(
            "BESS CAPEX ($/kWh)",
            100.0,
            2000.0,
            float(initial.bess_capex_per_kwh),
            25.0,
            key="sf_bess_capex",
        )
        opex_rate = (
            cols[3].number_input(
                "Annual OPEX (% of CAPEX)",
                0.5,
                10.0,
                float(initial.opex_rate * 100),
                0.1,
                format="%.1f",
                key="sf_opex_rate",
            )
            / 100.0
        )
        cols = st.columns(4)
        discount_rate = (
            cols[0].number_input(
                "Discount rate / WACC (%)",
                1.0,
                30.0,
                float(initial.discount_rate * 100),
                0.5,
                format="%.1f",
                key="sf_discount_rate",
            )
            / 100.0
        )
        target_irr = (
            cols[1].number_input(
                "Target IRR (%)",
                1.0,
                40.0,
                float(initial.target_irr * 100),
                0.5,
                format="%.1f",
                key="sf_target_irr",
            )
            / 100.0
        )
        project_life_yrs = cols[3].number_input(
            "Project life (years)",
            5,
            40,
            int(initial.project_life_yrs),
            1,
            key="sf_project_life",
        )

        st.divider()
        st.markdown("#### Project Locations & Market Zone")
        from ppa.data.bidding_zones import SUPPORTED_ZONES, bidding_zone_for, zone_label

        # Seed the coordinate widgets once from the scenario; afterwards their
        # session-state keys are the single source of truth so a map click can
        # update them (widget state must be written BEFORE the widget renders).
        _seed = {
            "sf_lat": float(initial.lat),
            "sf_lon": float(initial.lon),
            "sf_pv_lat": float(
                initial.pv_lat if initial.pv_lat is not None else initial.lat
            ),
            "sf_pv_lon": float(
                initial.pv_lon if initial.pv_lon is not None else initial.lon
            ),
            "sf_wind_lat": float(
                initial.wind_lat if initial.wind_lat is not None else initial.lat
            ),
            "sf_wind_lon": float(
                initial.wind_lon if initial.wind_lon is not None else initial.lon
            ),
        }
        for _k, _v in _seed.items():
            st.session_state.setdefault(_k, _v)

        # Apply a map click from the previous rerun (st_folium stores its state
        # under its widget key). Rounded to 0.01°: the CF cache granularity.
        _click = (st.session_state.get("sf_loc_map") or {}).get("last_clicked")
        if _click:
            _sig = (round(_click["lat"], 6), round(_click["lng"], 6))
            if st.session_state.get("_sf_handled_click") != _sig:
                st.session_state["_sf_handled_click"] = _sig
                _target = st.session_state.get("sf_map_target", "🔵 Offtaker")
                # A stale PV/Wind target (its "own location" toggle since
                # switched off) falls back to placing the offtaker.
                if _target == "🟡 PV" and not st.session_state.get(
                    "sf_pv_separate", False
                ):
                    _target = "🔵 Offtaker"
                if _target == "🟢 Wind" and not st.session_state.get(
                    "sf_wind_separate", False
                ):
                    _target = "🔵 Offtaker"
                _target_keys = {
                    "🔵 Offtaker": ("sf_lat", "sf_lon"),
                    "🟡 PV": ("sf_pv_lat", "sf_pv_lon"),
                    "🟢 Wind": ("sf_wind_lat", "sf_wind_lon"),
                }[_target]
                st.session_state[_target_keys[0]] = round(_click["lat"], 2)
                st.session_state[_target_keys[1]] = round(_click["lng"], 2)

        cols = st.columns([1, 1, 2])
        with cols[0]:
            st.markdown("**Offtaker (consumer)**")
            lat = st.number_input(
                "Latitude",
                -90.0,
                90.0,
                step=0.01,
                format="%.2f",
                key="sf_lat",
                help="Decimal degrees N. The offtaker location sets the bidding zone "
                "whose ENTSO-E day-ahead prices are used.",
            )
            lon = st.number_input(
                "Longitude",
                -180.0,
                180.0,
                step=0.01,
                format="%.2f",
                key="sf_lon",
                help="Decimal degrees E.",
            )
            auto_zone = bidding_zone_for(lat, lon)
            _zone_options = ["auto"] + SUPPORTED_ZONES
            _initial_zone = initial.bidding_zone_override or "auto"
            _zone_idx = (
                _zone_options.index(_initial_zone)
                if _initial_zone in _zone_options
                else 0
            )
            zone_choice = st.selectbox(
                "Bidding zone (prices)",
                options=_zone_options,
                index=_zone_idx,
                format_func=lambda z: (
                    f"Auto: {auto_zone} ({zone_label(auto_zone)})"
                    if z == "auto"
                    else f"{z} ({zone_label(z)})"
                ),
                key="sf_bidding_zone",
                help="Derived from the offtaker location (nearest-zone approximation): "
                "override it if the site is close to a zone border.",
            )
            bidding_zone_override = "" if zone_choice == "auto" else zone_choice

            transmission_cost_eur_mwh = st.number_input(
                "Transmission cost (€/MWh delivered)",
                0.0,
                200.0,
                float(initial.transmission_cost_eur_mwh),
                0.5,
                format="%.1f",
                key="sf_transmission_cost",
                help="Combined transmission / grid-use charge across all network levels between "
                "the generation sites and the offtaker, applied to every MWh delivered under "
                "the PPA. Enter the total (combined) value. It's charged regardless of "
                "whether assets and offtaker are in the same bidding zone or different ones.",
            )

        with cols[1]:
            st.markdown("**Generation assets**")
            pv_separate = st.toggle(
                "PV at its own location",
                value=initial.pv_lat is not None,
                key="sf_pv_separate",
            )
            if pv_separate:
                pv_lat = st.number_input(
                    "PV latitude",
                    -90.0,
                    90.0,
                    step=0.01,
                    format="%.2f",
                    key="sf_pv_lat",
                    value=st.session_state.get(
                        "sf_pv_lat",
                        initial.pv_lat if initial.pv_lat is not None else lat,
                    ),
                )
                pv_lon = st.number_input(
                    "PV longitude",
                    -180.0,
                    180.0,
                    step=0.01,
                    format="%.2f",
                    key="sf_pv_lon",
                    value=st.session_state.get(
                        "sf_pv_lon",
                        initial.pv_lon if initial.pv_lon is not None else lon,
                    ),
                )
            else:
                pv_lat, pv_lon = None, None

            wind_separate = st.toggle(
                "Wind at its own location",
                value=initial.wind_lat is not None,
                key="sf_wind_separate",
            )
            if wind_separate:
                wind_lat = st.number_input(
                    "Wind latitude",
                    -90.0,
                    90.0,
                    step=0.01,
                    format="%.2f",
                    key="sf_wind_lat",
                    value=st.session_state.get(
                        "sf_wind_lat",
                        initial.wind_lat if initial.wind_lat is not None else lat,
                    ),
                )
                wind_lon = st.number_input(
                    "Wind longitude",
                    -180.0,
                    180.0,
                    step=0.01,
                    format="%.2f",
                    key="sf_wind_lon",
                    value=st.session_state.get(
                        "sf_wind_lon",
                        initial.wind_lon if initial.wind_lon is not None else lon,
                    ),
                )
            else:
                wind_lat, wind_lon = None, None

        with cols[2]:
            _markers = [("🔵 Offtaker", lat, lon, "#1565C0")]
            if pv_separate:
                _markers.append(("🟡 PV", pv_lat, pv_lon, "#F9A825"))
            if wind_separate:
                _markers.append(("🟢 Wind", wind_lat, wind_lon, "#2E7D32"))

            try:
                import folium
                from streamlit_folium import st_folium
            except ImportError:
                st.map(
                    pd.DataFrame(
                        [
                            {"lat": la, "lon": lo, "color": c}
                            for _, la, lo, c in _markers
                        ]
                    ),
                    zoom=5,
                    height=300,
                    color="color",
                )
                st.caption(
                    "🔵 Offtaker · 🟡 PV · 🟢 Wind. Install `streamlit-folium` "
                    "to place locations by clicking the map."
                )
            else:
                _target_options = [name for name, *_ in _markers]
                if st.session_state.get("sf_map_target") not in _target_options:
                    st.session_state["sf_map_target"] = _target_options[0]
                st.radio(
                    "Clicking the map places:",
                    _target_options,
                    horizontal=True,
                    key="sf_map_target",
                    help="Choose which location a map click sets, then click the map. "
                    "Coordinates snap to 0.01°.",
                )
                fmap = folium.Map(
                    location=(lat, lon), zoom_start=5, tiles="CartoDB positron"
                )
                for name, la, lo, color in _markers:
                    folium.CircleMarker(
                        (la, lo),
                        radius=9,
                        color=color,
                        fill=True,
                        fill_color=color,
                        fill_opacity=0.9,
                        tooltip=name,
                    ).add_to(fmap)
                st_folium(
                    fmap,
                    height=320,
                    use_container_width=True,
                    key="sf_loc_map",
                    returned_objects=["last_clicked"],
                )

        st.divider()
        st.markdown("#### Simulation")
        cols = st.columns(4)
        simulation_years = int(
            cols[0].number_input(
                "Simulation years",
                1,
                40,
                int(initial.simulation_years),
                1,
                key="sf_sim_years",
                help="1 = single full-year run; >1 = multi-year parallel simulation.",
            )
        )
        first_sim_year = int(
            cols[1].number_input(
                "First simulation year",
                2024,
                2040,
                int(initial.first_sim_year),
                1,
                key="sf_first_sim_year",
            )
        )
        price_escalation_rate = (
            cols[2].number_input(
                "Price escalation (%/yr)",
                0.0,
                10.0,
                float(initial.price_escalation_rate * 100),
                0.1,
                format="%.1f",
                key="sf_escalation",
                help="Annual compound escalation applied to 2024 ENTSO-E base prices.",
            )
            / 100.0
        )

        st.caption(
            "Technology degradation (compound annual, applied from year 2 onward)"
        )
        cols = st.columns(4)
        pv_degradation_rate = (
            cols[0].number_input(
                "PV (%/yr)",
                0.0,
                5.0,
                float(initial.pv_degradation_rate * 100),
                0.05,
                format="%.2f",
                key="sf_pv_deg",
            )
            / 100.0
        )
        wind_degradation_rate = (
            cols[1].number_input(
                "Wind (%/yr)",
                0.0,
                5.0,
                float(initial.wind_degradation_rate * 100),
                0.05,
                format="%.2f",
                key="sf_wind_deg",
            )
            / 100.0
        )
        bess_degradation_rate = (
            cols[2].number_input(
                "BESS (%/yr)",
                0.0,
                10.0,
                float(initial.bess_degradation_rate * 100),
                0.1,
                format="%.1f",
                key="sf_bess_deg",
            )
            / 100.0
        )

        st.divider()
        st.markdown("#### Counterfactual sourcing")
        cols = st.columns(4)
        enable_counterfactual = cols[0].toggle(
            "Compare to counterfactual strategies",
            value=initial.enable_counterfactual,
            key="sf_enable_counterfactual",
            help="Compute spot-only and CAL Y+1 forward costs for the offtaker after each run.",
        )
        cal_forward_price = cols[1].number_input(
            "CAL Y+1 forward price (€/MWh)",
            min_value=0.0,
            max_value=500.0,
            value=float(initial.cal_forward_price),
            step=5.0,
            key="sf_cal_forward_price",
            help="Flat baseload forward price for the next calendar year (e.g. EEX German Cal Base).",
        )
        cal_hedge_fraction = (
            cols[2].slider(
                "Hedge fraction (%)",
                0,
                100,
                int(initial.cal_hedge_fraction * 100),
                step=5,
                format="%d%%",
                key="sf_cal_hedge_fraction",
                help="Share of load hedged at CAL Y+1; remainder sourced at spot.",
            )
            / 100.0
        )

        st.divider()
        st.markdown("#### Reference day selection")
        cols = st.columns(4)
        # Chosen day selector (use available days from loaded timeseries)
        ts = state.get_timeseries()
        if ts is not None:
            available_days = get_available_days(ts)
            chosen_day_idx = (
                available_days.index(initial.chosen_day)
                if initial.chosen_day in available_days
                else 14
            )
            chosen_day = cols[0].selectbox(
                "Reference day for daily charts",
                available_days,
                index=chosen_day_idx,
                key="sf_chosen_day",
            )
        else:
            chosen_day = initial.chosen_day
            cols[0].write(f"Day: {chosen_day}")

    return dataclasses.replace(
        initial,
        optimize_capacity=optimize_capacity,
        max_build_wind_mw=float(max_build_wind_mw),
        max_build_pv_mw=float(max_build_pv_mw),
        max_build_bess_mw=float(max_build_bess_mw),
        sizing_resolution_h=int(sizing_resolution_h),
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
        pv_lat=float(pv_lat) if pv_lat is not None else None,
        pv_lon=float(pv_lon) if pv_lon is not None else None,
        wind_lat=float(wind_lat) if wind_lat is not None else None,
        wind_lon=float(wind_lon) if wind_lon is not None else None,
        bidding_zone_override=bidding_zone_override,
        transmission_cost_eur_mwh=float(transmission_cost_eur_mwh),
        simulation_years=simulation_years,
        first_sim_year=first_sim_year,
        price_escalation_rate=float(price_escalation_rate),
        pv_degradation_rate=float(pv_degradation_rate),
        wind_degradation_rate=float(wind_degradation_rate),
        bess_degradation_rate=float(bess_degradation_rate),
    )
