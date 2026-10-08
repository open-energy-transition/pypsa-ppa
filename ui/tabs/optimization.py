"""Optimization tab: run simulation or single-day reference optimization."""

from __future__ import annotations

import dataclasses

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ppa.scenario import BASE_SCENARIO, validate_scenario
from ui import state


# ── timeseries loader (European reference-month path) ──────────────────────────


@st.cache_data
def _cached_reference_ts(
    pv_lat: float, pv_lon: float, wind_lat: float, wind_lon: float, zone: str
):
    from ppa.data.european_data import load_reference_month_ts

    return load_reference_month_ts(
        lat=pv_lat, lon=pv_lon, zone=zone, wind_lat=wind_lat, wind_lon=wind_lon
    )


def _get_timeseries(scenario):
    if state.has_timeseries():
        return state.get_timeseries()
    pv_lat, pv_lon = scenario.pv_location
    wind_lat, wind_lon = scenario.wind_location
    ts = _cached_reference_ts(pv_lat, pv_lon, wind_lat, wind_lon, scenario.bidding_zone)
    if ts is None:
        # Fall back to the default German reference cache so the single-day
        # illustration keeps working before location-specific data is fetched.
        ts = _cached_reference_ts(51.5, 10.0, 51.5, 10.0, "DE_LU")
    if ts is None:
        return None
    state.set_timeseries(ts)
    return ts


# ── scenario summary ──────────────────────────────────────────────────────────


def _render_scenario_summary(s) -> None:
    with st.expander("Scenario summary", expanded=False):
        cols = st.columns(4)
        with cols[0]:
            st.markdown("**Portfolio**")
            if s.optimize_capacity:
                st.markdown("- Mode: **co-optimized sizing** ⚡")
                st.markdown(
                    f"- Max build: wind **{s.max_build_wind_mw:.0f}** / "
                    f"solar **{s.max_build_pv_mw:.0f}** / "
                    f"BESS **{s.max_build_bess_mw:.0f} MW**"
                )
                st.markdown(f"- Sizing LP resolution: **{s.sizing_resolution_h}h**")
                if s.mga_enabled:
                    st.markdown(
                        f"- Near-optimal alternatives: **on** (+{s.mga_slack:.0%} cost slack)"
                    )
                if s.include_bess:
                    st.markdown(
                        f"- BESS duration: **{s.bess_max_hours:.1f} h** (fixed)"
                    )
                else:
                    st.markdown("- BESS: *disabled*")
            else:
                st.markdown(f"- Wind: **{s.onsw_mw:.0f} MW**")
                st.markdown(f"- Solar: **{s.pv_mw:.0f} MWac**")
                if s.include_bess:
                    st.markdown(
                        f"- BESS: **{s.effective_bess_mw:.0f} MW / {s.effective_bess_mwh:.0f} MWh**"
                    )
                else:
                    st.markdown("- BESS: *disabled*")

        with cols[1]:
            st.markdown("**PPA contract**")
            st.markdown(f"- Offtake: **{s.ppaload_mw:.0f} MW** flat")
            st.markdown(f"- Tariff: **€{s.ppa_price:.0f}/MWh**")
            st.markdown(f"- Required delivery: **{s.required_delivery_share:.0%}**")
            st.markdown(f"- Matching: **{s.matching_period}**")
            if s.enable_penalty:
                st.markdown(
                    f"- Penalty: **{s.pen_mult:.1f}×** = €{s.penalty_price:.0f}/MWh"
                )
            else:
                st.markdown("- Penalty: *disabled*")

        with cols[2]:
            st.markdown("**Market interaction**")
            if s.enable_market_buy:
                st.markdown(f"- Buy cap: **{s.market_buy_share:.0%}** of delivery")
            else:
                st.markdown("- Market buy: *disabled*")
            if s.enable_market_sell:
                st.markdown(f"- Sell: enabled (max {s.maxsell_mw:.0f} MW)")
            else:
                st.markdown("- Market sell: *disabled*")
            if s.enable_shortfall:
                st.markdown(f"- Shortfall: **{s.allowed_shortfall_share:.0%}** of load")
            else:
                st.markdown("- Shortfall: *disabled*")

        with cols[3]:
            st.markdown("**Simulation**")
            st.markdown(
                f"- Offtaker: **{s.lat:.2f}°N, {s.lon:.2f}°E**: zone **{s.bidding_zone}**"
            )
            if s.pv_location != (s.lat, s.lon):
                st.markdown(
                    f"- PV site: **{s.pv_location[0]:.2f}°N, {s.pv_location[1]:.2f}°E**"
                )
            if s.wind_location != (s.lat, s.lon):
                st.markdown(
                    f"- Wind site: **{s.wind_location[0]:.2f}°N, {s.wind_location[1]:.2f}°E**"
                )
            if s.transmission_cost_eur_mwh > 0:
                st.markdown(
                    f"- Transmission: **€{s.transmission_cost_eur_mwh:.1f}/MWh** delivered"
                )
            if s.simulation_years == 1:
                st.markdown(f"- Mode: **1-year** ({s.first_sim_year})")
            else:
                st.markdown(
                    f"- Mode: **{s.simulation_years}-year** "
                    f"({s.first_sim_year}–{s.first_sim_year + s.simulation_years - 1})"
                )
            st.markdown(f"- Price escalation: **{s.price_escalation_rate:.1%}/yr**")
            st.markdown(
                f"- Degradation: PV {s.pv_degradation_rate:.1%} | "
                f"Wind {s.wind_degradation_rate:.1%} | "
                f"BESS {s.bess_degradation_rate:.1%}"
            )


# ── data status (compact) ─────────────────────────────────────────────────────


def _render_data_status(s) -> tuple[bool, bool]:
    from ppa.data.entsoe_client import (
        list_cached_years as list_cached_price_years,
        AVAILABLE_YEARS as PRICE_YEARS,
    )
    from ppa.data.renewables_ninja import (
        list_cached_pv_years,
        list_cached_wind_years,
        AVAILABLE_YEARS,
    )

    zone = s.bidding_zone
    pv_lat, pv_lon = s.pv_location
    wind_lat, wind_lon = s.wind_location

    custom = state.get_custom_timeseries() or {}

    cached_price_years = list_cached_price_years(country_code=zone)
    prices_ok = len(cached_price_years) > 0 or bool(custom.get("price"))
    cached_cf_years = sorted(
        set(list_cached_pv_years(lat=pv_lat, lon=pv_lon))
        & set(list_cached_wind_years(lat=wind_lat, lon=wind_lon))
    )
    cf_ok = len(cached_cf_years) > 0 or (
        bool(custom.get("pv_cf")) and bool(custom.get("wind_cf"))
    )

    cols = st.columns(2)
    with cols[0]:
        if prices_ok:
            missing = [y for y in PRICE_YEARS if y not in cached_price_years]
            label = f"ENTSO-E prices ({zone}): {len(cached_price_years)} / {len(PRICE_YEARS)} years cached"
            st.warning(f"{label} (missing: {missing})") if missing else st.success(
                f"{label} ✓"
            )
        else:
            st.warning(
                f"No ENTSO-E prices cached for zone {zone}. Go to **Get Data** tab"
            )
        if custom.get("price"):
            st.caption(f"+ custom price data for year(s): {sorted(custom['price'])}")

    with cols[1]:
        if cf_ok:
            missing = [y for y in AVAILABLE_YEARS if y not in cached_cf_years]
            label = f"CF profiles: {len(cached_cf_years)} /{len(AVAILABLE_YEARS)} years cached"
            st.warning(f"{label} (missing: {missing})") if missing else st.success(
                f"{label} ✓"
            )
        else:
            st.warning(
                f"No CF profiles cached for PV ({pv_lat:.2f}, {pv_lon:.2f}) + "
                f"wind ({wind_lat:.2f}, {wind_lon:.2f}). Go to **Download Data** tab"
            )
        custom_cf_years = sorted(
            set(custom.get("pv_cf", {})) & set(custom.get("wind_cf", {}))
        )
        if custom_cf_years:
            st.caption(f"+ custom CF data for year(s): {custom_cf_years}")

    return prices_ok, cf_ok


# ── Simulation runner ────────────────────────────────────────────────


def _load_simulation_inputs(scenario) -> tuple[dict, dict, dict]:
    """Cached/custom CF and price series by year: (pv, wind, prices)."""
    from ppa.data import renewables_ninja as rn
    from ppa.data.entsoe_client import (
        fetch_day_ahead_prices,
        list_cached_years as list_cached_price_years,
    )

    pv_lat, pv_lon = scenario.pv_location
    wind_lat, wind_lon = scenario.wind_location
    cached_cf_years = sorted(
        set(rn.list_cached_pv_years(lat=pv_lat, lon=pv_lon))
        & set(rn.list_cached_wind_years(lat=wind_lat, lon=wind_lon))
    )
    pv_by_year: dict[int, pd.Series] = {}
    wind_by_year: dict[int, pd.Series] = {}
    for year in cached_cf_years:
        pv_by_year[year] = rn.download_pv_cf(year, "", lat=pv_lat, lon=pv_lon)
        wind_by_year[year] = rn.download_wind_cf(year, "", lat=wind_lat, lon=wind_lon)

    zone = scenario.bidding_zone
    prices_by_year: dict[int, pd.Series] = {}
    for year in list_cached_price_years(country_code=zone):
        prices_by_year[year] = fetch_day_ahead_prices(year, "", country_code=zone)

    # User-uploaded custom timeseries override cached/downloaded data year-by-year
    # (see ppa/data/custom_timeseries.py + the Download Data tab's import UI).
    custom = state.get_custom_timeseries()
    if custom:
        pv_by_year.update(custom.get("pv_cf", {}))
        wind_by_year.update(custom.get("wind_cf", {}))
        prices_by_year.update(custom.get("price", {}))

    # Fall back to any available price year if a CF year has no matching price year
    # (prices_by_year is cycled the same way as CF in pick_weather_year)
    if not prices_by_year:
        raise RuntimeError(
            f"No ENTSO-E prices cached for zone {zone}. Go to **Get Data** tab first."
        )
    return pv_by_year, wind_by_year, prices_by_year


def _run_simulation(scenario, max_workers: int, mga: dict | None = None) -> None:
    """Size (if co-optimizing), then simulate hourly and run financials.

    `mga` = {"slack": float, "objectives": [keys]} also generates near-optimal
    alternatives from the same sizing LP.
    """
    pv_by_year, wind_by_year, prices_by_year = _load_simulation_inputs(scenario)
    user_scenario = scenario

    progress_bar = st.progress(0, text="Starting optimization ...")
    status_text = st.empty()

    # ── Capacity co-optimization pre-step ─────────────────────────────────────
    if scenario.optimize_capacity:
        import time

        from ppa.sizing import (
            apply_sizing,
            build_sizing_timeseries,
            clamp_sizing_years,
            run_sizing_subprocess,
            weather_cycle_years,
        )

        n_sizing_years, cycle_note = weather_cycle_years(
            scenario.simulation_years, len(pv_by_year), len(prices_by_year)
        )
        if cycle_note:
            st.info(cycle_note)
        n_sizing_years, notice = clamp_sizing_years(
            n_sizing_years, scenario.sizing_resolution_h
        )
        if notice:
            st.warning(notice)
        progress_bar.progress(
            0.0,
            text=(
                f"Sizing portfolio (co-optimizing capacities, {n_sizing_years}-year LP "
                f"at {scenario.sizing_resolution_h}h resolution)..."
            ),
        )
        sizing_ts = build_sizing_timeseries(
            scenario, pv_by_year, wind_by_year, prices_by_year, n_sizing_years
        )

        _t0 = time.monotonic()
        stage = {"text": "Solving the sizing LP"}

        def _sizing_heartbeat() -> None:
            status_text.text(
                f"{stage['text']} in a background process... "
                f"{time.monotonic() - _t0:.0f}s elapsed. Press Stop to cancel."
            )

        def _on_mga_progress(text: str) -> None:
            stage["text"] = text
            progress_bar.progress(0.0, text=text)

        sized = run_sizing_subprocess(
            sizing_ts,
            scenario,
            heartbeat=_sizing_heartbeat,
            mga_slack=mga["slack"] if mga else None,
            mga_objectives=mga["objectives"] if mga else (),
            on_progress=_on_mga_progress,
        )
        if sized.status != "ok":
            raise RuntimeError(
                f"Capacity sizing LP failed: {sized.status} / {sized.condition}"
            )
        if sized.mga is not None:
            state.set_mga_result(sized.mga, user_scenario)
            sized.mga = None  # the alternatives live under their own state key
        else:
            state.clear_mga_result()
        # Keep the sized scenario local to this run: the user's scenario keeps
        # optimize_capacity=True so re-runs re-size; the optimized fleet is
        # surfaced via state.set_optimized_sizes.
        scenario = apply_sizing(scenario, sized)
        state.set_optimized_sizes(sized)
        status_text.success(
            f"Optimized portfolio: Wind {sized.onsw_mw:.0f} MW · "
            f"Solar {sized.pv_mw:.0f} MW · BESS {sized.bess_mw:.0f} MW / "
            f"{sized.bess_mwh:.0f} MWh (sized over {sized.sizing_years_used} year(s) "
            f"at {sized.resolution_h}h resolution): running hourly dispatch..."
        )
    else:
        state.clear_mga_result()

    fin = _run_hourly(
        scenario,
        (pv_by_year, wind_by_year, prices_by_year),
        max_workers,
        progress_bar,
        status_text,
    )
    if state.has_mga_result():
        state.record_mga_kpis("optimum", fin)


def _run_hourly(scenario, inputs, max_workers: int, progress_bar, status_text):
    """Hourly multi-year dispatch + financials for a fixed-capacity scenario."""
    from ppa.financials import run_multi_year_financial_analysis
    from ppa.multi_year import run_multi_year

    pv_by_year, wind_by_year, prices_by_year = inputs

    def _on_progress(done: int, total: int, sim_year: int) -> None:
        progress_bar.progress(done / total, text=f"Year {sim_year} ({done}/{total})")
        status_text.text(f"Solved {done} of {total} year(s)...")

    results = run_multi_year(
        scenario=scenario,
        pv_cf_by_year=pv_by_year,
        wind_cf_by_year=wind_by_year,
        prices_by_year=prices_by_year,
        first_sim_year=scenario.first_sim_year,
        max_workers=max_workers,
        progress_callback=_on_progress,
    )
    state.set_multi_year_results(results)

    fin = run_multi_year_financial_analysis(
        scenario, results, first_sim_year=scenario.first_sim_year
    )
    state.set_multi_year_financial(fin)

    progress_bar.progress(1.0, text="Optimization complete!")
    status_text.success(f"Completed {scenario.simulation_years} year(s) successfully.")
    return fin


def _simulate_alternative(user_scenario, alt, max_workers: int) -> None:
    """Adopt a near-optimal alternative: hourly sim + financials with its fleet.

    The alternative becomes the active portfolio for every results tab (via
    `state.set_optimized_sizes`), exactly like the least-cost optimum after a run.
    """
    from ppa.sizing import apply_sizing

    inputs = _load_simulation_inputs(user_scenario)
    progress_bar = st.progress(0, text=f"Simulating '{alt.label}' hourly...")
    status_text = st.empty()
    fin = _run_hourly(
        apply_sizing(user_scenario, alt.sized),
        inputs,
        max_workers,
        progress_bar,
        status_text,
    )
    state.set_optimized_sizes(alt.sized)
    state.set_mga_active(alt.key)
    state.record_mga_kpis(alt.key, fin)


# ── multi-year results display ────────────────────────────────────────────────


def _render_results(fin, n_years: int) -> None:
    with st.expander("Optimization results", expanded=True):
        cols = st.columns(5)
        irr_str = f"{fin.irr:.1%}" if fin.irr == fin.irr else "N/A"
        lcoe_str = f"€{fin.lcoe:.1f}/MWh" if fin.lcoe == fin.lcoe else "N/A"
        payback_str = (
            f"{fin.simple_payback:.1f} yrs" if fin.simple_payback < 1e8 else "N/A"
        )
        cols[0].metric("NPV", f"€{fin.npv / 1e6:.1f}M")
        cols[1].metric("Project IRR", irr_str)
        cols[2].metric("LCOE", lcoe_str)
        cols[3].metric("Simple Payback", payback_str)
        cols[4].metric(
            "Lifetime Net Revenue", f"€{fin.total_lifetime_revenue / 1e6:.1f}M"
        )

        if n_years == 1:
            y = fin.yearly[0]
            st.caption(
                f"Year {y.year}: PPA revenue €{y.ppa_revenue / 1e6:.2f}M | "
                f"Merchant €{y.merch_revenue / 1e6:.2f}M | "
                f"Delivery {y.fulfilled_share:.1%} | "
                f"Net CF €{y.net_cashflow / 1e6:.2f}M"
            )
            return

    # st.markdown("---")
    with st.expander("Charts & data tables", expanded=True):
        tab_charts, tab_table = st.tabs(["| Charts", "| Year-by-Year Table"])
        with tab_charts:
            tab_chart1, tab_chart2, tab_chart3 = st.tabs(
                [
                    "| Cumulative NPV",
                    "| Annual Revenue Breakdown",
                    "| PPA Delivery Rate",
                ]
            )
            with tab_chart1:
                _render_npv_chart(fin)
            with tab_chart2:
                _render_revenue_chart(fin)
            with tab_chart3:
                _render_delivery_chart(fin)

        with tab_table:
            _render_yearly_table(fin)


def _render_npv_chart(fin) -> None:
    years = [y.year for y in fin.yearly]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=years,
            y=[round(v / 1e6, 2) for v in fin.cumulative_npv],
            mode="lines+markers",
            name="Cumulative NPV",
            line=dict(color="#2196F3", width=2),
        )
    )
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    fig.update_layout(
        title="Cumulative NPV over Project Life",
        xaxis_title="Year",
        yaxis_title="NPV (€M)",
        height=400,
    )
    st.plotly_chart(fig, width="stretch")


def _render_revenue_chart(fin) -> None:
    years = [y.year for y in fin.yearly]
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=years,
            y=[round(y.ppa_revenue / 1e6, 2) for y in fin.yearly],
            name="PPA revenue",
        )
    )
    fig.add_trace(
        go.Bar(
            x=years,
            y=[round(y.merch_revenue / 1e6, 2) for y in fin.yearly],
            name="Merchant revenue",
        )
    )
    fig.add_trace(
        go.Bar(
            x=years,
            y=[round(-y.market_buy_cost / 1e6, 2) for y in fin.yearly],
            name="Market buy cost",
        )
    )
    fig.add_trace(
        go.Bar(
            x=years,
            y=[round(-y.penalty_cost / 1e6, 2) for y in fin.yearly],
            name="Penalty cost",
        )
    )
    fig.add_trace(
        go.Bar(
            x=years,
            y=[round(-y.transmission_cost / 1e6, 2) for y in fin.yearly],
            name="Transmission cost",
        )
    )
    fig.add_trace(
        go.Bar(x=years, y=[round(-y.opex / 1e6, 2) for y in fin.yearly], name="OPEX")
    )
    fig.update_layout(
        barmode="relative",
        title="Annual Revenue Breakdown",
        xaxis_title="Year",
        yaxis_title="€M",
        height=400,
    )
    st.plotly_chart(fig, width="stretch")


def _render_delivery_chart(fin) -> None:
    years = [y.year for y in fin.yearly]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=years,
            y=[round(y.fulfilled_share, 3) * 100 for y in fin.yearly],
            mode="lines+markers",
            name="PPA Delivery Rate",
            line=dict(color="#4CAF50", width=2),
        )
    )
    fig.update_layout(
        title="PPA Delivery Rate by Year",
        xaxis_title="Year",
        yaxis_title="Delivery Rate (%)",
        yaxis=dict(range=[0, 105]),
        height=400,
    )
    st.plotly_chart(fig, width="stretch")


def _render_yearly_table(fin) -> None:
    rows = [
        {
            "Year": y.year,
            "PPA Revenue (€M)": round(y.ppa_revenue / 1e6, 2),
            "Merchant Revenue (€M)": round(y.merch_revenue / 1e6, 2),
            "Market Buy Cost (€M)": round(y.market_buy_cost / 1e6, 2),
            "Penalty Cost (€M)": round(y.penalty_cost / 1e6, 2),
            "Transmission Cost (€M)": round(y.transmission_cost / 1e6, 2),
            "OPEX (€M)": round(y.opex / 1e6, 2),
            "Net Cash Flow (€M)": round(y.net_cashflow / 1e6, 2),
            "Delivery Rate (%)": round(y.fulfilled_share * 100, 1),
            "Wind Gen (GWh)": round(y.wind_gen_mwh / 1e3, 1),
            "PV Gen (GWh)": round(y.pv_gen_mwh / 1e3, 1),
        }
        for y in fin.yearly
    ]
    st.dataframe(
        pd.DataFrame(rows).set_index("Year"), width="stretch", height="content"
    )


# ── near-optimal alternatives (MGA) ───────────────────────────────────────────

# Same technology colors as the dispatch charts (ui/charts.py)
_TECH_COLORS = {"Wind": "#388E3C", "Solar": "#F57C00", "BESS": "#1565C0"}


def _render_mga_status(s) -> dict | None:
    """One-line MGA status (configured in Case Definition); returns run settings."""
    if not s.optimize_capacity:
        return None
    from ppa.sizing import mga_settings

    settings = mga_settings(s)
    if settings is None:
        st.caption(
            "Near-optimal alternatives (MGA): **off**. Enable them in **Case "
            "Definition** under the capacity optimization settings."
        )
        return None
    slack, objectives = settings
    st.caption(
        f"Near-optimal alternatives (MGA): **on**, up to {len(objectives)} "
        f"alternative(s) within **+{slack:.0%}** of least cost "
        "(configured in **Case Definition**)."
    )
    return {"slack": slack, "objectives": list(objectives)}


def _active_alternative():
    """The MGA alternative currently simulated in the results tabs, if any."""
    result = state.get_mga_result()
    if result is None:
        return None
    active = state.get_mga_active()
    return next((a for a in result.all if a.key == active), None)


def _render_mga(s, max_workers: int, data_ready: bool) -> None:
    result = state.get_mga_result()
    kpis = state.get_mga_kpis()
    active_key = state.get_mga_active()
    # Compare field dicts: dataclass == is False across Streamlit class reloads
    mga_scenario = state.get_mga_scenario()
    stale = mga_scenario is None or dataclasses.asdict(mga_scenario) != dataclasses.asdict(s)

    with st.expander("Near-optimal alternatives (MGA)", expanded=True):
        st.caption(
            f"Capacity mixes whose total cost of serving the PPA is within "
            f"**+{result.slack:.0%}** of the least-cost optimum (lost PPA revenue counts "
            "as cost). Capacities and energy shares come from the coarse sizing LP; "
            "**Simulate & adopt** runs the full hourly simulation and financials for an "
            "alternative and makes it the active portfolio in all results tabs."
        )
        if stale:
            st.warning(
                "The scenario has changed since these alternatives were generated. "
                "Re-run the optimization to refresh them."
            )

        opt = result.optimum.sized
        rows = []
        for a in result.all:
            k = kpis.get(a.key)
            near_opt = a.key != "optimum" and all(
                abs(x - y) < 1.0
                for x, y in [
                    (a.sized.onsw_mw, opt.onsw_mw),
                    (a.sized.pv_mw, opt.pv_mw),
                    (a.sized.bess_mw, opt.bess_mw),
                ]
            )
            rows.append(
                {
                    "Alternative": ("▶ " if a.key == active_key else "")
                    + a.label
                    + (" (≈ optimum)" if near_opt else ""),
                    "Stakeholder": a.stakeholder,
                    "Wind (MW)": round(a.sized.onsw_mw, 1),
                    "Solar (MW)": round(a.sized.pv_mw, 1),
                    "BESS (MW)": round(a.sized.bess_mw, 1),
                    "BESS (MWh)": round(a.sized.bess_mwh, 1),
                    "Cost vs least-cost (%)": round(a.cost_increase * 100, 2),
                    "Total cost (€M/yr)": round(a.total_cost_eur_per_yr / 1e6, 2),
                    "Upfront capex (€M)": round(a.capex_eur / 1e6, 1),
                    "Own-RE hourly matching (%)": round(a.re_matching_share * 100, 1),
                    "Market buy (% of load)": round(a.market_buy_share * 100, 1),
                    "Surplus (% of RE available)": round(a.surplus_share * 100, 1),
                    "NPV (€M)": round(k["npv"] / 1e6, 1) if k else None,
                    "IRR (%)": round(k["irr"] * 100, 1) if k and k["irr"] == k["irr"] else None,
                }
            )

        tab_table, tab_caps, tab_ranges = st.tabs(
            ["| Comparison table", "| Capacities", "| Near-optimal ranges"]
        )
        with tab_table:
            st.dataframe(
                pd.DataFrame(rows).set_index("Alternative"),
                width="stretch",
                height="content",
            )
            st.caption(
                "▶ marks the portfolio currently simulated. NPV/IRR appear once an "
                "alternative has been simulated hourly."
            )
        with tab_caps:
            _render_mga_capacity_chart(result)
        with tab_ranges:
            _render_mga_range_chart(result)

        for note in result.notes:
            st.caption(f"ℹ️ {note}")

        cols = st.columns([3, 1], vertical_alignment="bottom")
        choice = cols[0].selectbox(
            "Alternative to simulate",
            options=[a.key for a in result.all],
            index=0,
            format_func=lambda key: next(
                f"{a.label} ({a.stakeholder}, +{a.cost_increase:.1%})"
                for a in result.all
                if a.key == key
            ),
            key="opt_mga_choice",
        )
        simulate = cols[1].button(
            "▶ Simulate & adopt",
            width="stretch",
            key="opt_mga_simulate",
            disabled=stale or not data_ready or choice == active_key,
        )

    if simulate:
        alt = next(a for a in result.all if a.key == choice)
        try:
            _simulate_alternative(s, alt, max_workers)
        except Exception as exc:
            st.error(f"Simulating alternative failed: {exc}")
        else:
            st.rerun()


def _render_mga_capacity_chart(result) -> None:
    alts = result.all
    labels = [a.label for a in alts][::-1]  # optimum on top
    fig = go.Figure()
    # Horizontal groups stack traces bottom-up: add BESS first so wind sits on
    # top of each group, matching the (reversed) legend order
    for tech, attr in [("BESS", "bess_mw"), ("Solar", "pv_mw"), ("Wind", "onsw_mw")]:
        fig.add_trace(
            go.Bar(
                y=labels,
                x=[round(getattr(a.sized, attr), 1) for a in alts][::-1],
                name=tech,
                orientation="h",
                marker_color=_TECH_COLORS[tech],
                hovertemplate=f"%{{y}}<br>{tech}: %{{x:.0f}} MW<extra></extra>",
            )
        )
    fig.update_layout(
        barmode="group",
        bargap=0.25,
        bargroupgap=0.05,
        title=f"Installed capacity by alternative (all within +{result.slack:.0%} of least cost)",
        xaxis_title="MW",
        height=max(380, 70 * len(alts)),
        yaxis=dict(automargin=True),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, x=0, traceorder="reversed"
        ),
        margin=dict(t=90),
    )
    st.plotly_chart(fig, width="stretch")


def _render_mga_range_chart(result) -> None:
    """Per-technology min–max across all alternatives, with the optimum marked."""
    alts = result.all
    techs = [("Wind", "onsw_mw"), ("Solar", "pv_mw"), ("BESS", "bess_mw")]
    fig = go.Figure()
    for tech, attr in techs:
        values = [getattr(a.sized, attr) for a in alts]
        lo, hi = min(values), max(values)
        fig.add_trace(
            go.Bar(
                y=[tech],
                x=[max(hi - lo, 0.5)],  # keep a sliver visible when the range is ~0
                base=[lo],
                orientation="h",
                marker_color=_TECH_COLORS[tech],
                opacity=0.35,
                width=0.5,
                showlegend=False,
                hovertemplate=f"{tech}: {lo:.0f}–{hi:.0f} MW near-optimal range<extra></extra>",
            )
        )
    fig.add_trace(
        go.Scatter(
            y=[t for t, _ in techs],
            x=[getattr(result.optimum.sized, attr) for _, attr in techs],
            mode="markers",
            name="Least-cost optimum",
            marker=dict(symbol="diamond", size=12, color="#333333"),
            hovertemplate="%{y} at least cost: %{x:.0f} MW<extra></extra>",
        )
    )
    fig.update_layout(
        title=f"Capacity ranges within +{result.slack:.0%} of least cost",
        xaxis_title="MW",
        yaxis=dict(autorange="reversed"),
        height=320,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        margin=dict(t=90),
    )
    st.plotly_chart(fig, width="stretch")
    st.caption(
        "Wide ranges mean the technology is flexible at near-optimal cost; narrow "
        "ranges mark capacity that any affordable portfolio needs."
    )


# ── main render ───────────────────────────────────────────────────────────────


def render() -> None:
    st.title("⚙️ Optimization")

    if not state.has_scenario():
        state.set_scenario(BASE_SCENARIO)
    s = state.get_scenario()

    _render_scenario_summary(s)
    # st.markdown("---")

    # ── Simulation ───────────────────────────────────────────────────
    # st.subheader("Optimization")
    with st.expander("Optimization", expanded=True):
        prices_ok, cf_ok = _render_data_status(s)
        data_ready = prices_ok and cf_ok

        cols = st.columns([1, 1, 2], vertical_alignment="bottom")
        with cols[0]:
            model_run = st.button(
                "▶ Run Optimization",
                type="primary",
                width="stretch",
                key="opt_run_eu",
                disabled=not data_ready,
            )
        with cols[1]:
            max_workers = st.selectbox(
                "Parallel workers",
                [1, 2, 4, 8, 16, 24, 30],
                index=2,
                key="opt_max_workers",
                help=(
                    "Max parallel year-solves. Automatically capped to the available "
                    "CPU and RAM (~1.4 GB per worker), so memory-limited hosts like "
                    "Streamlit Cloud fall back to serial regardless of this value. "
                    "Ignored for single-year runs."
                ),
            )
        with cols[2]:
            if not data_ready:
                st.warning("Download data first (see **Get Data** tab).")
            elif state.has_multi_year_results():
                n_done = len(state.get_multi_year_results())
                st.success(f"Last run: {n_done} year(s) solved.")

        mga = _render_mga_status(s)

    if model_run and data_ready:
        try:
            _run_simulation(s, int(max_workers), mga=mga)
        except Exception as exc:
            st.error(f"Optimization failed: {exc}")
        else:
            st.rerun()

    if state.has_multi_year_financial():
        # st.markdown("---")
        if s.optimize_capacity and state.has_optimized_sizes():
            sized = state.get_optimized_sizes()
            active = _active_alternative()
            if active is not None and active.key != "optimum":
                headline = (
                    f"⚡ **Near-optimal alternative adopted: {active.label}** "
                    f"(+{active.cost_increase:.1%} vs least cost)"
                )
            else:
                headline = "⚡ **Optimized portfolio**"
            st.info(
                f"{headline}: Wind **{sized.onsw_mw:.0f} MW** · "
                f"Solar **{sized.pv_mw:.0f} MW** · BESS **{sized.bess_mw:.0f} MW / "
                f"{sized.bess_mwh:.0f} MWh** (sized over {sized.sizing_years_used} year(s) "
                f"at {getattr(sized, 'resolution_h', 1)}h resolution; dispatch & financials run hourly)"
            )
        _render_results(state.get_multi_year_financial(), s.simulation_years)

    if state.has_mga_result():
        _render_mga(s, int(max_workers), data_ready)

    # ── Single-day reference optimization (European reference month) ──────────
    # st.markdown("---")
    with st.expander(
        "Single-day reference optimization (European reference month)", expanded=False
    ):
        st.caption(
            f"Runs the LP over a representative European month ({s.bidding_zone} prices + "
            "renewables.ninja capacity factors, falling back to the German reference cache "
            "if location data is not downloaded yet). Pick the day to inspect under "
            "**Reference day selection**. Results feed the Results, and Analysis tabs."
        )
        ts = _get_timeseries(s)
        if ts is None:
            st.error(
                "Could not load the European reference timeseries from `data/cache/`."
            )
        else:
            from ppa.data_loader import get_available_days

            errors = validate_scenario(s, available_days=get_available_days(ts))
            if errors:
                for err in errors:
                    st.error(err)
                st.warning(
                    "Fix the above issues in **Case Study Definition** before running."
                )
            else:
                cols = st.columns([1, 3])
                with cols[0]:
                    single_run = st.button(
                        "▶ Run Single-Day",
                        type="secondary",
                        width="stretch",
                        key="opt_run_single",
                    )
                with cols[1]:
                    if state.has_result():
                        r = state.get_result()
                        st.success(
                            f"Last run: **{r.solver_status}** / **{r.solver_condition}**"
                        )

                if single_run:
                    with st.spinner("Solving... (typically 5–15 s)"):
                        try:
                            from ppa.data_loader import prepare_timeseries
                            from ppa.network import build_network
                            from ppa.solver import solve
                            from ppa.results import extract_results
                            from ppa.financials import run_financial_analysis
                            from ppa.counterfactuals import compute_counterfactuals

                            ts_prep = prepare_timeseries(ts, s)

                            # Capacity co-optimization pre-step (reference month → fast)
                            if s.optimize_capacity:
                                from ppa.sizing import apply_sizing, optimize_capacities

                                sized = optimize_capacities(ts_prep, s)
                                if sized.status != "ok":
                                    raise RuntimeError(
                                        f"Capacity sizing LP failed: {sized.status} / {sized.condition}"
                                    )
                                s = apply_sizing(s, sized)
                                state.set_optimized_sizes(sized)
                                # Alternatives belong to the multi-year sizing LP
                                state.clear_mga_result()
                                st.info(
                                    f"Optimized portfolio: Wind {sized.onsw_mw:.0f} MW · "
                                    f"Solar {sized.pv_mw:.0f} MW · BESS {sized.bess_mw:.0f} MW / "
                                    f"{sized.bess_mwh:.0f} MWh (sized on the reference month)"
                                )

                            n = build_network(ts_prep, s)
                            status, condition = solve(n, s, ts_prep)
                            result = extract_results(n, s, ts_prep, status, condition)
                            state.set_result(result)

                            if s.run_financial_analysis:
                                fin = run_financial_analysis(
                                    s,
                                    result.summary,
                                    result.revenue,
                                    result.n_period_hours,
                                )
                                state.set_financial(fin)
                            if s.enable_counterfactual:
                                cf = compute_counterfactuals(ts_prep, s, result)
                                state.set_counterfactual(cf)
                        except Exception as exc:
                            st.error(f"Optimization failed: {exc}")
                        else:
                            st.success(
                                f"Complete: {status} / {condition}. See Results tabs."
                            )
