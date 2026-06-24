"""Optimization tab — run European simulation or single-day reference optimization."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ppa.scenario import BASE_SCENARIO, validate_scenario
from ui import state


# ── timeseries loader (European reference-month path) ──────────────────────────

@st.cache_data
def _cached_reference_ts():
    from ppa.data.european_data import load_reference_month_ts
    return load_reference_month_ts()


def _get_timeseries():
    if state.has_timeseries():
        return state.get_timeseries()
    ts = _cached_reference_ts()
    if ts is None:
        return None
    state.set_timeseries(ts)
    return ts


# ── scenario summary ──────────────────────────────────────────────────────────

def _render_scenario_summary(s) -> None:
    st.subheader("Scenario summary")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown("**Portfolio**")
        st.markdown(f"- Wind: **{s.onsw_mw:.0f} MW**")
        st.markdown(f"- Solar: **{s.pv_mw:.0f} MWac**")
        if s.include_bess:
            st.markdown(f"- BESS: **{s.effective_bess_mw:.0f} MW / {s.effective_bess_mwh:.0f} MWh**")
        else:
            st.markdown("- BESS: *disabled*")

    with c2:
        st.markdown("**PPA contract**")
        st.markdown(f"- Offtake: **{s.ppaload_mw:.0f} MW** flat")
        st.markdown(f"- Tariff: **€{s.ppa_price:.0f}/MWh**")
        st.markdown(f"- Required delivery: **{s.required_delivery_share:.0%}**")
        if s.enable_penalty:
            st.markdown(f"- Penalty: **{s.pen_mult:.1f}×** = €{s.penalty_price:.0f}/MWh")
        else:
            st.markdown("- Penalty: *disabled*")

    with c3:
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

    with c4:
        st.markdown("**Simulation**")
        st.markdown(f"- Location: **{s.lat:.2f}°N, {s.lon:.2f}°E**")
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

def _render_data_status(lat: float, lon: float) -> tuple[bool, bool]:
    from ppa.data.entsoe_client import list_cached_years as list_cached_price_years, AVAILABLE_YEARS as PRICE_YEARS
    from ppa.data.renewables_ninja import list_cached_years, AVAILABLE_YEARS

    cached_price_years = list_cached_price_years()
    prices_ok = len(cached_price_years) > 0
    cached_cf_years = list_cached_years(lat=lat, lon=lon)
    cf_ok = len(cached_cf_years) > 0

    c1, c2 = st.columns(2)
    with c1:
        if prices_ok:
            missing = [y for y in PRICE_YEARS if y not in cached_price_years]
            label = f"ENTSO-E prices: {len(cached_price_years)}/{len(PRICE_YEARS)} years cached"
            st.warning(f"{label} (missing: {missing})") if missing else st.success(f"{label} ✓")
        else:
            st.warning("No ENTSO-E prices cached — go to **Download Data** tab")
    with c2:
        if cf_ok:
            missing = [y for y in AVAILABLE_YEARS if y not in cached_cf_years]
            label = f"CF profiles: {len(cached_cf_years)}/{len(AVAILABLE_YEARS)} years cached"
            st.warning(f"{label} (missing: {missing})") if missing else st.success(f"{label} ✓")
        else:
            st.warning(f"No CF profiles cached for ({lat:.2f}, {lon:.2f}) — go to **Download Data** tab")
    return prices_ok, cf_ok


# ── European simulation runner ────────────────────────────────────────────────

def _run_eu_simulation(scenario, max_workers: int) -> None:
    from ppa.data import renewables_ninja as rn
    from ppa.data.entsoe_client import fetch_day_ahead_prices, list_cached_years as list_cached_price_years
    from ppa.multi_year import run_multi_year
    from ppa.financials import run_multi_year_financial_analysis

    lat, lon = scenario.lat, scenario.lon
    cached_cf_years = rn.list_cached_years(lat=lat, lon=lon)
    pv_by_year: dict[int, pd.Series] = {}
    wind_by_year: dict[int, pd.Series] = {}
    for year in cached_cf_years:
        pv_by_year[year] = rn.download_pv_cf(year, "", lat=lat, lon=lon)
        wind_by_year[year] = rn.download_wind_cf(year, "", lat=lat, lon=lon)

    prices_by_year: dict[int, pd.Series] = {}
    for year in list_cached_price_years():
        prices_by_year[year] = fetch_day_ahead_prices(year, "")

    # Fall back to any available price year if a CF year has no matching price year
    # (prices_by_year is cycled the same way as CF in pick_weather_year)
    if not prices_by_year:
        raise RuntimeError("No ENTSO-E prices cached. Go to Download Data first.")

    progress_bar = st.progress(0, text="Starting simulation…")
    status_text = st.empty()

    def _on_progress(done: int, total: int, sim_year: int) -> None:
        progress_bar.progress(done / total, text=f"Year {sim_year} ({done}/{total})")
        status_text.text(f"Solved {done} of {total} year(s)…")

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

    progress_bar.progress(1.0, text="Simulation complete!")
    status_text.success(f"Completed {scenario.simulation_years} year(s) successfully.")


# ── multi-year results display ────────────────────────────────────────────────

def _render_eu_results(fin, n_years: int) -> None:
    st.subheader("Simulation results")

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
    st.plotly_chart(fig, width="stretch")


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
    st.plotly_chart(fig, width="stretch")


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
    st.plotly_chart(fig, width="stretch")


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
    st.dataframe(pd.DataFrame(rows).set_index("Year"), width="stretch")


# ── main render ───────────────────────────────────────────────────────────────

def render() -> None:
    st.title("⚙️ Optimization")

    if not state.has_scenario():
        state.set_scenario(BASE_SCENARIO)
    s = state.get_scenario()

    _render_scenario_summary(s)
    st.markdown("---")

    # ── European simulation ───────────────────────────────────────────────────
    st.subheader("European simulation")
    prices_ok, cf_ok = _render_data_status(s.lat, s.lon)
    data_ready = prices_ok and cf_ok

    run_col, workers_col, status_col = st.columns([1, 1, 2])
    with workers_col:
        max_workers = st.selectbox(
            "Parallel workers", [1, 2, 4, 6, 8], index=2, key="opt_max_workers",
            help="Threads used for multi-year solving. Ignored for single-year runs.",
        )
    with run_col:
        eu_run = st.button(
            "▶ Run Simulation",
            type="primary",
            width="stretch",
            key="opt_run_eu",
            disabled=not data_ready,
        )
    with status_col:
        if not data_ready:
            st.warning("Download data first (see **Download Data** tab).")
        elif state.has_multi_year_results():
            n_done = len(state.get_multi_year_results())
            st.success(f"Last run: {n_done} year(s) solved.")

    if eu_run and data_ready:
        try:
            _run_eu_simulation(s, int(max_workers))
        except Exception as exc:
            st.error(f"Simulation failed: {exc}")
        else:
            st.rerun()

    if state.has_multi_year_financial():
        st.markdown("---")
        _render_eu_results(state.get_multi_year_financial(), s.simulation_years)

    # ── Single-day reference optimization (European reference month) ──────────
    st.markdown("---")
    with st.expander("Single-day reference optimization (European reference month)", expanded=False):
        st.caption(
            "Runs the LP over a representative European month (German DE-LU prices + "
            "renewables.ninja capacity factors). Pick the day to inspect under **Reference "
            "day selection**. Results feed the Results Overview, Results Deep Dive, and analysis tabs."
        )
        ts = _get_timeseries()
        if ts is None:
            st.error("Could not load the European reference timeseries from `data/cache/`.")
        else:
            from ppa.data_loader import get_available_days
            errors = validate_scenario(s, available_days=get_available_days(ts))
            if errors:
                for err in errors:
                    st.error(err)
                st.warning("Fix the above issues in **Case Study Definition** before running.")
            else:
                c1, c2 = st.columns([1, 3])
                with c1:
                    single_run = st.button("▶ Run Single-Day", type="secondary", width="stretch", key="opt_run_single")
                with c2:
                    if state.has_result():
                        r = state.get_result()
                        st.success(f"Last run: **{r.solver_status}** / **{r.solver_condition}**")

                if single_run:
                    with st.spinner("Solving… (typically 5–15 s)"):
                        try:
                            from ppa.data_loader import prepare_timeseries
                            from ppa.network import build_network
                            from ppa.solver import solve
                            from ppa.results import extract_results
                            from ppa.financials import run_financial_analysis
                            from ppa.counterfactuals import compute_counterfactuals

                            ts_prep = prepare_timeseries(ts, s)
                            n = build_network(ts_prep, s)
                            status, condition = solve(n, s, ts_prep)
                            result = extract_results(n, s, ts_prep, status, condition)
                            state.set_result(result)

                            if s.run_financial_analysis:
                                fin = run_financial_analysis(s, result.summary, result.revenue, result.n_period_hours)
                                state.set_financial(fin)
                            if s.enable_counterfactual:
                                cf = compute_counterfactuals(ts_prep, s, result)
                                state.set_counterfactual(cf)
                        except Exception as exc:
                            st.error(f"Optimization failed: {exc}")
                        else:
                            st.success(f"Complete — {status} / {condition}. See Results tabs.")
