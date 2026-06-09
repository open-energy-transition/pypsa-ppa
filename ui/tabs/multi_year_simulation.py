"""Multi-year European PPA simulation tab."""
from __future__ import annotations

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

from ui import state


# ── helpers ──────────────────────────────────────────────────────────────────

def _token_key(name: str) -> str:
    return f"_token_{name}"


def _get_token(name: str) -> str:
    return st.session_state.get(_token_key(name), "")


def _entsoe_cached(year: int) -> bool:
    from ppa.data.entsoe_client import is_cached
    return is_cached(year)


def _ninja_cached_years(lat: float, lon: float) -> list[int]:
    from ppa.data.renewables_ninja import list_cached_years
    return list_cached_years(lat=lat, lon=lon)


# ── data preparation section ─────────────────────────────────────────────────

def _render_data_section(lat: float, lon: float) -> None:
    st.subheader("1. Data Preparation")

    with st.expander("API Tokens & Download", expanded=True):
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("**ENTSO-E Transparency Platform**")
            st.caption(
                "Free token — register at [transparency.entsoe.eu](https://transparency.entsoe.eu). "
                "Used to fetch 2024 German day-ahead prices."
            )
            entsoe_token = st.text_input(
                "ENTSO-E API token",
                value=_get_token("entsoe"),
                type="password",
                key="entsoe_token_input",
                placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
            )
            if entsoe_token:
                st.session_state[_token_key("entsoe")] = entsoe_token

            price_cached = _entsoe_cached(2024)
            if price_cached:
                st.success("2024 DE-LU prices: cached ✓")
            else:
                st.warning("2024 DE-LU prices: not downloaded yet")

            if st.button("Download 2024 DA Prices", disabled=not entsoe_token, key="dl_prices"):
                with st.spinner("Fetching from ENTSO-E…"):
                    try:
                        from ppa.data.entsoe_client import fetch_day_ahead_prices
                        fetch_day_ahead_prices(2024, entsoe_token)
                        st.success("Downloaded and cached.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"ENTSO-E fetch failed: {exc}")

        with col2:
            st.markdown("**Renewables.ninja**")
            st.caption(
                "Free account at [renewables.ninja](https://www.renewables.ninja). "
                "Used to fetch 2018–2023 wind & solar CF profiles for Germany."
            )
            ninja_token = st.text_input(
                "Renewables.ninja API token",
                value=_get_token("ninja"),
                type="password",
                key="ninja_token_input",
                placeholder="your-ninja-token",
            )
            if ninja_token:
                st.session_state[_token_key("ninja")] = ninja_token

            cached_years = _ninja_cached_years(lat, lon)
            from ppa.data.renewables_ninja import AVAILABLE_YEARS
            missing = [y for y in AVAILABLE_YEARS if y not in cached_years]
            if not missing:
                st.success(f"All {len(AVAILABLE_YEARS)} weather years cached ✓")
            else:
                st.warning(f"Missing weather years: {missing}")

            if st.button(
                "Download CF Profiles",
                disabled=not ninja_token or not missing,
                key="dl_cf",
                help="Downloads missing years only. Adds a 2-second delay between requests.",
            ):
                progress = st.progress(0, text="Starting download…")
                try:
                    from ppa.data.renewables_ninja import download_all_years
                    total = len(missing) * 2  # pv + wind per year
                    done = 0

                    for year in missing:
                        from ppa.data import renewables_ninja as rn
                        progress.progress(done / total, text=f"Downloading PV {year}…")
                        rn.download_pv_cf(year, ninja_token, lat=lat, lon=lon)
                        done += 1
                        import time; time.sleep(2)

                        progress.progress(done / total, text=f"Downloading wind {year}…")
                        rn.download_wind_cf(year, ninja_token, lat=lat, lon=lon)
                        done += 1
                        import time; time.sleep(2)

                    progress.progress(1.0, text="Done!")
                    st.success("All CF profiles downloaded.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Renewables.ninja download failed: {exc}")


# ── simulation config ─────────────────────────────────────────────────────────

def _render_sim_config() -> tuple[int, float, float, float, float, float, int]:
    st.subheader("2. Simulation Configuration")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        sim_years = st.number_input(
            "Simulation years",
            min_value=1,
            max_value=40,
            value=st.session_state.get("my_sim_years", 25),
            step=1,
            key="my_sim_years",
            help="Number of years in the project lifetime to simulate.",
        )
    with col2:
        first_year = st.number_input(
            "First simulation year",
            min_value=2024,
            max_value=2040,
            value=st.session_state.get("my_first_year", 2025),
            step=1,
            key="my_first_year",
        )
    with col3:
        escalation = st.number_input(
            "Annual price escalation (%)",
            min_value=0.0,
            max_value=10.0,
            value=st.session_state.get("my_escalation", 2.0),
            step=0.1,
            format="%.1f",
            key="my_escalation",
            help="Applied to 2024 ENTSO-E prices for each subsequent year.",
        )
    with col4:
        max_workers = st.selectbox(
            "Parallel workers",
            options=[1, 2, 4, 6, 8],
            index=2,
            key="my_workers",
            help="Number of years solved simultaneously (threads).",
        )

    st.markdown("**Technology degradation** (compound annual rate applied from year 1)")
    dcol1, dcol2, dcol3 = st.columns(3)
    with dcol1:
        pv_deg = st.number_input(
            "Solar PV degradation (%/yr)",
            min_value=0.0,
            max_value=5.0,
            value=st.session_state.get("my_pv_deg", 0.5),
            step=0.05,
            format="%.2f",
            key="my_pv_deg",
            help="Annual reduction in PV output. Industry standard: 0.5 %/yr.",
        )
    with dcol2:
        wind_deg = st.number_input(
            "Wind degradation (%/yr)",
            min_value=0.0,
            max_value=5.0,
            value=st.session_state.get("my_wind_deg", 0.5),
            step=0.05,
            format="%.2f",
            key="my_wind_deg",
            help="Annual reduction in wind output. Industry standard: 0.5 %/yr.",
        )
    with dcol3:
        bess_deg = st.number_input(
            "BESS capacity degradation (%/yr)",
            min_value=0.0,
            max_value=10.0,
            value=st.session_state.get("my_bess_deg", 2.0),
            step=0.1,
            format="%.1f",
            key="my_bess_deg",
            help="Annual reduction in usable BESS energy capacity. Industry standard: 2.0 %/yr.",
        )

    return (
        int(sim_years),
        float(first_year),
        float(escalation) / 100.0,
        float(pv_deg) / 100.0,
        float(wind_deg) / 100.0,
        float(bess_deg) / 100.0,
        int(max_workers),
    )


# ── run + progress ────────────────────────────────────────────────────────────

def _run_simulation(
    scenario,
    sim_years: int,
    first_year: int,
    escalation: float,
    pv_deg: float,
    wind_deg: float,
    bess_deg: float,
    max_workers: int,
) -> None:
    lat, lon = scenario.lat, scenario.lon

    # Load cached data
    cached_years = _ninja_cached_years(lat, lon)
    if not cached_years:
        st.error("No wind/solar CF profiles found. Download them first (section 1).")
        return

    if not _entsoe_cached(2024):
        st.error("2024 ENTSO-E prices not found. Download them first (section 1).")
        return

    import dataclasses
    scenario = dataclasses.replace(
        scenario,
        simulation_years=sim_years,
        price_escalation_rate=escalation,
        pv_degradation_rate=pv_deg,
        wind_degradation_rate=wind_deg,
        bess_degradation_rate=bess_deg,
    )

    from ppa.data import renewables_ninja as rn
    from ppa.data.entsoe_client import fetch_day_ahead_prices

    # Load all CF data into memory
    pv_by_year: dict[int, pd.Series] = {}
    wind_by_year: dict[int, pd.Series] = {}
    for year in cached_years:
        pv_by_year[year] = rn.download_pv_cf(year, "", lat=lat, lon=lon)  # token ignored if cached
        wind_by_year[year] = rn.download_wind_cf(year, "", lat=lat, lon=lon)

    base_prices = fetch_day_ahead_prices(2024, "")  # token ignored if cached

    progress_bar = st.progress(0, text="Starting multi-year simulation…")
    status_text = st.empty()

    completed_count = [0]

    def _on_progress(done: int, total: int, sim_year: int) -> None:
        completed_count[0] = done
        pct = done / total
        progress_bar.progress(pct, text=f"Year {sim_year} complete ({done}/{total})")
        status_text.text(f"Solved {done} of {total} years…")

    from ppa.multi_year import run_multi_year
    from ppa.financials import run_multi_year_financial_analysis

    try:
        results = run_multi_year(
            scenario=scenario,
            pv_cf_by_year=pv_by_year,
            wind_cf_by_year=wind_by_year,
            base_prices=base_prices,
            base_price_year=2024,
            first_sim_year=first_year,
            max_workers=max_workers,
            progress_callback=_on_progress,
        )
        state.set_multi_year_results(results)

        fin = run_multi_year_financial_analysis(scenario, results, first_sim_year=first_year)
        state.set_multi_year_financial(fin)

        progress_bar.progress(1.0, text="Simulation complete!")
        status_text.success(f"All {sim_years} years solved successfully.")
    except Exception as exc:
        st.error(f"Simulation failed: {exc}")
        raise


# ── results rendering ─────────────────────────────────────────────────────────

def _render_results(fin, first_year: int) -> None:
    st.subheader("4. Results")

    # ── KPI cards ─────────────────────────────────────────────────────────────
    col1, col2, col3, col4, col5 = st.columns(5)
    irr_str = f"{fin.irr:.1%}" if not (fin.irr != fin.irr) else "N/A"
    col1.metric("NPV", f"€{fin.npv/1e6:.1f}M")
    col2.metric("Project IRR", irr_str)
    col3.metric("LCOE", f"€{fin.lcoe:.1f}/MWh" if not (fin.lcoe != fin.lcoe) else "N/A")
    col4.metric("Simple Payback", f"{fin.simple_payback:.1f} yrs" if fin.simple_payback < 1e8 else "N/A")
    col5.metric("Lifetime Net Revenue", f"€{fin.total_lifetime_revenue/1e6:.1f}M")

    st.markdown("---")

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
    fig.add_trace(
        go.Scatter(
            x=years,
            y=[v / 1e6 for v in fin.cumulative_npv],
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
        height=350,
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
        barmode="relative",
        title="Annual Revenue Breakdown",
        xaxis_title="Year",
        yaxis_title="€M",
        height=400,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_delivery_chart(fin) -> None:
    years = [y.year for y in fin.yearly]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=years,
            y=[y.fulfilled_share * 100 for y in fin.yearly],
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
        height=300,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_yearly_table(fin) -> None:
    rows = []
    for y in fin.yearly:
        rows.append(
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
        )
    df = pd.DataFrame(rows).set_index("Year")
    st.dataframe(df, use_container_width=True)


# ── main render ───────────────────────────────────────────────────────────────

def render() -> None:
    st.title("🌍 Multi-Year European Simulation")
    st.markdown(
        "Simulate the full project lifetime using **German (DE-LU) market prices** from ENTSO-E "
        "and wind/solar capacity-factor profiles from **renewables.ninja** (historical years 2018–2023, cycled). "
        "Each simulation year is solved as an independent LP with real hourly data."
    )

    if not state.has_scenario():
        st.info("Define a scenario in the **Case Study Definition** tab first.")
        return

    scenario = state.get_scenario()

    st.markdown(
        f"**Active scenario:** {scenario.name} — "
        f"Wind {scenario.onsw_mw:.0f} MW | Solar {scenario.pv_mw:.0f} MW | "
        f"PPA {scenario.ppaload_mw:.0f} MW @ €{scenario.ppa_price:.0f}/MWh"
    )

    _render_data_section(scenario.lat, scenario.lon)

    st.markdown("---")
    sim_years, first_year, escalation, pv_deg, wind_deg, bess_deg, max_workers = _render_sim_config()

    st.markdown("---")
    st.subheader("3. Run Simulation")

    col1, col2 = st.columns([1, 3])
    with col1:
        run_clicked = st.button(
            "▶ Run Multi-Year Simulation",
            type="primary",
            width="stretch",
            key="run_multi_year",
        )
    with col2:
        if state.has_multi_year_results():
            results = state.get_multi_year_results()
            st.success(f"Last run: **{len(results)} years** solved.")

    if run_clicked:
        _run_simulation(scenario, sim_years, first_year, escalation, pv_deg, wind_deg, bess_deg, max_workers)
        st.rerun()

    if state.has_multi_year_financial():
        st.markdown("---")
        _render_results(state.get_multi_year_financial(), first_year)
