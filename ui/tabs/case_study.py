"""Case Study definition and European simulation runner (merged tab)."""
from __future__ import annotations

import dataclasses

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ppa.scenario import CASE_STUDIES, BASE_SCENARIO, load_case_study
from ui import state
from ui.scenario_form import render_scenario_form


# ── case study cards ──────────────────────────────────────────────────────────

def _render_case_study_card(cs, is_active: bool) -> bool:
    border_color = "#1565C0" if is_active else "#E0E0E0"
    bg_color = "#E3F2FD" if is_active else "#FAFAFA"
    badge = " ✓ Active" if is_active else ""
    st.markdown(
        f"""
<div style="border: 2px solid {border_color}; border-radius: 10px; padding: 16px;
            background: {bg_color}; height: 100%;">
  <div style="font-size: 2rem; margin-bottom: 6px;">{cs.icon}</div>
  <div style="font-weight: 700; font-size: 1.05rem; color: #1A237E;">{cs.name}{badge}</div>
  <div style="font-size: 0.85rem; color: #546E7A; margin-bottom: 8px;">{cs.subtitle}</div>
  <div style="font-size: 0.88rem; color: #424242; line-height: 1.5;">{cs.storyline}</div>
</div>
""",
        unsafe_allow_html=True,
    )
    st.markdown("")
    return st.button(
        "Reload" if is_active else "Load this scenario",
        key=f"load_cs_{cs.id}",
        width="stretch",
        type="primary" if is_active else "secondary",
    )


# ── data status ───────────────────────────────────────────────────────────────

def _check_data(lat: float, lon: float) -> tuple[bool, list[int]]:
    """Return (prices_cached, cached_weather_years)."""
    from ppa.data.entsoe_client import is_cached
    from ppa.data.renewables_ninja import list_cached_years
    return is_cached(2024), list_cached_years(lat=lat, lon=lon)


def _render_data_status(lat: float, lon: float) -> tuple[bool, bool]:
    """Render a compact data-readiness row. Returns (prices_ok, cf_ok)."""
    prices_ok, cached_years = _check_data(lat, lon)
    from ppa.data.renewables_ninja import AVAILABLE_YEARS
    cf_ok = len(cached_years) > 0

    c1, c2, c3 = st.columns(3)
    with c1:
        if prices_ok:
            st.success("ENTSO-E 2024 prices: cached ✓")
        else:
            st.warning("ENTSO-E 2024 prices: not downloaded")
    with c2:
        if cf_ok:
            missing = [y for y in AVAILABLE_YEARS if y not in cached_years]
            label = f"CF profiles: {len(cached_years)}/{len(AVAILABLE_YEARS)} years"
            if missing:
                st.warning(f"{label} (missing: {missing})")
            else:
                st.success(f"{label} ✓")
        else:
            st.warning(f"CF profiles: none cached for ({lat:.2f}, {lon:.2f})")
    with c3:
        st.caption(
            f"Location: **{lat:.2f}°N, {lon:.2f}°E** — "
            "Go to **Download Data** tab to fetch missing files."
        )
    return prices_ok, cf_ok


# ── simulation runner ─────────────────────────────────────────────────────────

def _run_eu_simulation(scenario, max_workers: int) -> None:
    from ppa.data import renewables_ninja as rn
    from ppa.data.entsoe_client import fetch_day_ahead_prices, is_cached
    from ppa.multi_year import run_multi_year
    from ppa.financials import run_multi_year_financial_analysis

    lat, lon = scenario.lat, scenario.lon
    cached_years = rn.list_cached_years(lat=lat, lon=lon)
    if not cached_years:
        st.error("No CF profiles cached for this location. Download them first.")
        return
    if not is_cached(2024):
        st.error("2024 ENTSO-E prices not cached. Download them first.")
        return

    pv_by_year: dict[int, pd.Series] = {}
    wind_by_year: dict[int, pd.Series] = {}
    for year in cached_years:
        pv_by_year[year] = rn.download_pv_cf(year, "", lat=lat, lon=lon)
        wind_by_year[year] = rn.download_wind_cf(year, "", lat=lat, lon=lon)
    base_prices = fetch_day_ahead_prices(2024, "")

    n_years = scenario.simulation_years
    progress_bar = st.progress(0, text="Starting simulation…")
    status_text = st.empty()

    def _on_progress(done: int, total: int, sim_year: int) -> None:
        progress_bar.progress(done / total, text=f"Year {sim_year} ({done}/{total})")
        status_text.text(f"Solved {done} of {total} year(s)…")

    try:
        results = run_multi_year(
            scenario=scenario,
            pv_cf_by_year=pv_by_year,
            wind_cf_by_year=wind_by_year,
            base_prices=base_prices,
            base_price_year=2024,
            first_sim_year=scenario.first_sim_year,
            max_workers=max_workers,
            progress_callback=_on_progress,
        )
        state.set_multi_year_results(results)

        fin = run_multi_year_financial_analysis(
            scenario, results, first_sim_year=scenario.first_sim_year
        )
        state.set_multi_year_financial(fin)

        progress_bar.progress(1.0, text="Simulation complete!")
        status_text.success(f"Completed {n_years} year(s) successfully.")
    except Exception as exc:
        st.error(f"Simulation failed: {exc}")
        raise


# ── results ───────────────────────────────────────────────────────────────────

def _render_results(fin, n_years: int) -> None:
    st.subheader("Results")

    c1, c2, c3, c4, c5 = st.columns(5)
    irr_str = f"{fin.irr:.1%}" if fin.irr == fin.irr else "N/A"
    lcoe_str = f"€{fin.lcoe:.1f}/MWh" if fin.lcoe == fin.lcoe else "N/A"
    payback_str = f"{fin.simple_payback:.1f} yrs" if fin.simple_payback < 1e8 else "N/A"
    c1.metric("NPV", f"€{fin.npv/1e6:.1f}M")
    c2.metric("Project IRR", irr_str)
    c3.metric("LCOE", lcoe_str)
    c4.metric("Simple Payback", payback_str)
    c5.metric("Lifetime Net Revenue", f"€{fin.total_lifetime_revenue/1e6:.1f}M")

    if n_years == 1:
        y = fin.yearly[0]
        st.caption(
            f"Year {y.year} — PPA revenue €{y.ppa_revenue/1e6:.2f}M | "
            f"Merchant €{y.merch_revenue/1e6:.2f}M | "
            f"Delivery {y.fulfilled_share:.1%} | "
            f"Net CF €{y.net_cashflow/1e6:.2f}M"
        )
        return

    tab_charts, tab_table = st.tabs(["Charts", "Year-by-Year Table"])
    with tab_charts:
        _render_npv_chart(fin)
        _render_revenue_chart(fin)
        _render_delivery_chart(fin)
    with tab_table:
        _render_yearly_table(fin)


def _render_npv_chart(fin) -> None:
    years = [y.year for y in fin.yearly]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=years, y=[v / 1e6 for v in fin.cumulative_npv],
        mode="lines+markers", name="Cumulative NPV",
        line=dict(color="#2196F3", width=2),
    ))
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    fig.update_layout(
        title="Cumulative NPV over Project Life",
        xaxis_title="Year", yaxis_title="NPV (€M)", height=350,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_revenue_chart(fin) -> None:
    years = [y.year for y in fin.yearly]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=years, y=[y.ppa_revenue / 1e6 for y in fin.yearly], name="PPA revenue"))
    fig.add_trace(go.Bar(x=years, y=[y.merch_revenue / 1e6 for y in fin.yearly], name="Merchant revenue"))
    fig.add_trace(go.Bar(x=years, y=[-y.market_buy_cost / 1e6 for y in fin.yearly], name="Market buy cost"))
    fig.add_trace(go.Bar(x=years, y=[-y.penalty_cost / 1e6 for y in fin.yearly], name="Penalty cost"))
    fig.add_trace(go.Bar(x=years, y=[-y.opex / 1e6 for y in fin.yearly], name="OPEX"))
    fig.update_layout(
        barmode="relative", title="Annual Revenue Breakdown",
        xaxis_title="Year", yaxis_title="€M", height=400,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_delivery_chart(fin) -> None:
    years = [y.year for y in fin.yearly]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=years, y=[y.fulfilled_share * 100 for y in fin.yearly],
        mode="lines+markers", name="PPA Delivery Rate",
        line=dict(color="#4CAF50", width=2),
    ))
    fig.update_layout(
        title="PPA Delivery Rate by Year",
        xaxis_title="Year", yaxis_title="Delivery Rate (%)",
        yaxis=dict(range=[0, 105]), height=300,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_yearly_table(fin) -> None:
    rows = [
        {
            "Year": y.year,
            "PPA Revenue (€M)": round(y.ppa_revenue / 1e6, 2),
            "Merchant Revenue (€M)": round(y.merch_revenue / 1e6, 2),
            "Market Buy Cost (€M)": round(y.market_buy_cost / 1e6, 2),
            "Penalty Cost (€M)": round(y.penalty_cost / 1e6, 2),
            "OPEX (€M)": round(y.opex / 1e6, 2),
            "Net Cash Flow (€M)": round(y.net_cashflow / 1e6, 2),
            "Delivery Rate (%)": round(y.fulfilled_share * 100, 1),
            "Wind Gen (GWh)": round(y.wind_gen_mwh / 1e3, 1),
            "PV Gen (GWh)": round(y.pv_gen_mwh / 1e3, 1),
        }
        for y in fin.yearly
    ]
    st.dataframe(pd.DataFrame(rows).set_index("Year"), use_container_width=True)


# ── main render ───────────────────────────────────────────────────────────────

def render() -> None:
    st.title("🔬 Case Study & Simulation")
    st.markdown(
        "Select a predefined case study or customise all parameters below. "
        "Set the **project location** to fetch European market and weather data, "
        "then run a single-year or multi-year LP optimisation."
    )

    # ── 1. Case study cards ───────────────────────────────────────────────────
    st.subheader("Predefined case studies")
    active_id = state.get_active_case_study_id()
    cols = st.columns(len(CASE_STUDIES))
    for col, cs in zip(cols, CASE_STUDIES):
        with col:
            if _render_case_study_card(cs, is_active=(cs.id == active_id)):
                state.set_scenario(load_case_study(cs))
                state.set_active_case_study_id(cs.id)
                state.clear_result()
                st.session_state.pop(state.MULTI_YEAR_RESULTS_KEY, None)
                st.session_state.pop(state.MULTI_YEAR_FINANCIAL_KEY, None)
                st.rerun()

    # ── 2. Customise parameters ───────────────────────────────────────────────
    with st.expander("Customise parameters", expanded=False):
        if not state.has_scenario():
            state.set_scenario(BASE_SCENARIO)

        current = state.get_scenario()
        updated = render_scenario_form(current)

        c1, c2 = st.columns(2)
        with c1:
            if st.button("Apply changes", type="primary", width="stretch"):
                state.set_scenario(updated)
                state.clear_result()
                st.session_state.pop(state.MULTI_YEAR_RESULTS_KEY, None)
                st.session_state.pop(state.MULTI_YEAR_FINANCIAL_KEY, None)
                st.success("Scenario updated.")
        with c2:
            if st.button("Reset to base defaults", type="secondary", width="stretch"):
                state.set_scenario(BASE_SCENARIO)
                state.set_active_case_study_id("")
                state.clear_result()
                st.session_state.pop(state.MULTI_YEAR_RESULTS_KEY, None)
                st.session_state.pop(state.MULTI_YEAR_FINANCIAL_KEY, None)
                st.rerun()

    # Need a scenario to proceed
    if not state.has_scenario():
        state.set_scenario(BASE_SCENARIO)
    scenario = state.get_scenario()

    # ── 3. Active scenario summary ────────────────────────────────────────────
    st.markdown("---")
    sim_label = (
        f"**1-year** (European, {scenario.first_sim_year})"
        if scenario.simulation_years == 1
        else f"**{scenario.simulation_years}-year** ({scenario.first_sim_year}–{scenario.first_sim_year + scenario.simulation_years - 1})"
    )
    st.markdown(
        f"**Active scenario:** {scenario.name} — "
        f"Wind {scenario.onsw_mw:.0f} MW | Solar {scenario.pv_mw:.0f} MW | "
        f"PPA {scenario.ppaload_mw:.0f} MW @ €{scenario.ppa_price:.0f}/MWh | "
        f"Simulation: {sim_label}"
    )

    # ── 4. Data readiness ─────────────────────────────────────────────────────
    prices_ok, cf_ok = _render_data_status(scenario.lat, scenario.lon)
    data_ready = prices_ok and cf_ok

    # ── 5. Run controls ───────────────────────────────────────────────────────
    st.markdown("---")
    run_col, workers_col, status_col = st.columns([2, 1, 3])

    with workers_col:
        max_workers = st.selectbox(
            "Parallel workers",
            options=[1, 2, 4, 6, 8],
            index=2,
            key="cs_max_workers",
            help="Threads used for multi-year solving. Ignored for single-year runs.",
        )

    with run_col:
        run_clicked = st.button(
            "▶ Run Simulation",
            type="primary",
            width="stretch",
            key="cs_run_sim",
            disabled=not data_ready,
        )

    with status_col:
        if not data_ready:
            st.warning("Data not ready — download it in the **Download Data** tab first.")
        elif state.has_multi_year_results():
            n_done = len(state.get_multi_year_results())
            st.success(f"Last run: {n_done} year(s) solved. Re-run to refresh.")

    if run_clicked and data_ready:
        _run_eu_simulation(scenario, int(max_workers))
        st.rerun()

    # ── 6. Results ────────────────────────────────────────────────────────────
    if state.has_multi_year_financial():
        st.markdown("---")
        _render_results(state.get_multi_year_financial(), scenario.simulation_years)
