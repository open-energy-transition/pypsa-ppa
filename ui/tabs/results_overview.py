from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ppa.results import build_supply_mix_df, build_24h_avg
from ui import state
from ui.charts import make_supply_mix_24h_chart, make_revenue_breakdown_chart


def _render_multi_year_overview(fin) -> None:
    s = state.get_scenario()

    # ── Lifetime KPIs ─────────────────────────────────────────────────────────
    st.subheader("Lifetime KPIs")
    c1, c2, c3, c4, c5 = st.columns(5)
    irr_str = f"{fin.irr:.1%}" if fin.irr == fin.irr else "N/A"
    lcoe_str = f"€{fin.lcoe:.1f}/MWh" if fin.lcoe == fin.lcoe else "N/A"
    payback_str = f"{fin.simple_payback:.1f} yrs" if fin.simple_payback < 1e8 else "N/A"
    c1.metric("NPV", f"€{fin.npv / 1e6:.1f}M")
    c2.metric("Project IRR", irr_str)
    c3.metric("LCOE", lcoe_str)
    c4.metric("Simple Payback", payback_str)
    c5.metric("Lifetime Net Revenue", f"€{fin.total_lifetime_revenue / 1e6:.1f}M")

    # ── CAPEX breakdown ───────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("CAPEX & OPEX")
    cc1, cc2 = st.columns(2)
    with cc1:
        capex_rows = [
            ("Onshore wind", f"€{fin.capex.capex_wind / 1e6:.1f}M"),
            ("Solar PV", f"€{fin.capex.capex_pv / 1e6:.1f}M"),
            ("BESS", f"€{fin.capex.capex_bess / 1e6:.1f}M"),
            ("Total CAPEX", f"€{fin.capex.capex_total / 1e6:.1f}M"),
            ("Annual OPEX", f"€{fin.annual_opex / 1e6:.2f}M/yr"),
        ]
        st.dataframe(
            pd.DataFrame(capex_rows, columns=["Item", "Value"]),
            hide_index=True,
            width="stretch",
        )
    with cc2:
        avg_delivery = sum(y.fulfilled_share for y in fin.yearly) / len(fin.yearly) if fin.yearly else 0.0
        total_gen_gwh = fin.total_lifetime_generation_mwh / 1e3
        avg_wind_gwh = sum(y.wind_gen_mwh for y in fin.yearly) / len(fin.yearly) / 1e3 if fin.yearly else 0.0
        avg_pv_gwh = sum(y.pv_gen_mwh for y in fin.yearly) / len(fin.yearly) / 1e3 if fin.yearly else 0.0
        gen_rows = [
            ("Avg annual PPA delivery rate", f"{avg_delivery:.1%}"),
            ("Total lifetime generation", f"{total_gen_gwh:.0f} GWh"),
            ("Avg annual wind generation", f"{avg_wind_gwh:.1f} GWh"),
            ("Avg annual solar generation", f"{avg_pv_gwh:.1f} GWh"),
        ]
        st.dataframe(
            pd.DataFrame(gen_rows, columns=["Metric", "Value"]),
            hide_index=True,
            width="stretch",
        )

    # ── Cumulative NPV chart ──────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Cumulative NPV")
    years = [y.year for y in fin.yearly]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=years, y=[v / 1e6 for v in fin.cumulative_npv],
        mode="lines+markers", name="Cumulative NPV",
        line=dict(color="#2196F3", width=2),
        fill="tozeroy",
        fillcolor="rgba(33,150,243,0.08)",
    ))
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    fig.update_layout(
        xaxis_title="Year", yaxis_title="NPV (€M)", height=320,
        margin=dict(t=10, b=40),
    )
    st.plotly_chart(fig, width="stretch")

    # ── Year-by-year table ────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Year-by-year results")
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

    st.caption(
        "Detailed hourly dispatch analysis is available in **Results Deep Dive** "
        "after running the Single-Day reference in the Optimization tab."
    )


def _render_single_day_overview() -> None:
    result = state.get_result()
    s = result.scenario
    summary = result.summary
    revenue = result.revenue
    fin = state.get_financial()

    # ── KPI row ───────────────────────────────────────────────────────────────
    st.subheader("Key performance indicators")
    cols = st.columns(4)
    cols[0].metric(
        "PPA Fulfilment",
        f"{summary.fulfilled_share:.1%}",
        delta=f"{summary.fulfilled_share - s.required_delivery_share:+.1%} vs target",
        delta_color="normal",
    )
    cols[1].metric(
        "Net Revenue",
        f"€{revenue.net_revenue / 1e6:,.2f}M",
        help="PPA revenue + merchant revenue − market purchases − penalty costs (period total)",
    )
    cols[2].metric(
        "Effective Capture Price",
        f"€{revenue.effective_capture_price:.2f}/MWh",
        help="Net revenue ÷ total generation (MWh)",
    )
    if fin is not None:
        cols[3].metric(
            "LCOE",
            f"€{fin.lcoe:.2f}/MWh",
            help=f"Levelised Cost of Energy at {s.discount_rate:.0%} WACC",
        )
    else:
        cols[3].metric("LCOE", "—", help="Run with financial analysis enabled")

    cols = st.columns(4)
    cols[0].metric(
        "Penalty Volume",
        f"{summary.penalty_mwh:,.0f} MWh",
        delta=f"{summary.penalty_share_of_load:.1%} of load",
        delta_color="inverse",
    )

    # ── Offtaker procurement comparison ───────────────────────────────────────
    if state.has_counterfactual():
        cf = state.get_counterfactual()
        st.markdown("---")
        st.subheader("Offtaker procurement comparison")
        st.caption(
            "How much would the offtaker have paid under alternative sourcing strategies? "
            "Effective €/MWh for the modelled period — covers shortfall hours at spot for the PPA column."
        )
        cols = st.columns(4)
        cols[0].metric(
            "PPA (offtaker)",
            f"€{cf.ppa_effective_price:.2f}/MWh",
            help="PPA tariff for delivered MWh + spot price for any undelivered load.",
        )
        cols[1].metric(
            "Spot-only",
            f"€{cf.spot_avg_price:.2f}/MWh",
            delta=f"{cf.spot_avg_price - cf.ppa_effective_price:+.2f} €/MWh vs PPA",
            delta_color="normal",
            help="100% of load sourced at real-time spot each hour.",
        )
        cols[2].metric(
            f"CAL Y+1 (€{s.cal_forward_price:.0f}/MWh)",
            f"€{cf.cal_avg_price:.2f}/MWh",
            delta=f"{cf.cal_avg_price - cf.ppa_effective_price:+.2f} €/MWh vs PPA",
            delta_color="normal",
            help="Flat baseload forward contract; zero spot exposure.",
        )
        cols[3].metric(
            f"Blended ({s.cal_hedge_fraction:.0%} CAL)",
            f"€{cf.blended_avg_price:.2f}/MWh",
            delta=f"{cf.blended_avg_price - cf.ppa_effective_price:+.2f} €/MWh vs PPA",
            delta_color="normal",
            help=f"{s.cal_hedge_fraction:.0%} of load at CAL Y+1 forward + remainder at spot.",
        )

    st.markdown("---")

    # ── Constraint compliance ──────────────────────────────────────────────────
    st.subheader("Constraint compliance")
    allowed_limit = s.allowed_shortfall_share * summary.total_load_mwh
    buy_limit = s.market_buy_share * summary.ppa_delivered_mwh

    compliance = {
        "Constraint": ["Allowed shortfall cap", "Market buy cap"],
        "Actual (MWh)": [f"{summary.allowed_shortfall_mwh:,.0f}", f"{summary.market_buy_to_ppa_mwh:,.0f}"],
        "Limit (MWh)": [f"{allowed_limit:,.0f}", f"{buy_limit:,.0f}"],
        "Status": [
            "✅ Satisfied" if summary.allowed_shortfall_mwh <= allowed_limit + 1 else "❌ Violated",
            "✅ Satisfied" if summary.market_buy_to_ppa_mwh <= buy_limit + 1 else "❌ Violated",
        ],
    }
    st.dataframe(pd.DataFrame(compliance), hide_index=True, width="stretch")

    # ── Dispatch summary table ─────────────────────────────────────────────────
    st.subheader("Dispatch summary")

    cols = st.columns(2)
    with cols[0]:
        st.markdown("**Generation volumes**")
        gen_data = {
            "Metric": [
                "Total PPA load",
                "PPA delivered",
                " › from renewables & storage",
                " › from market purchase",
                "Allowed shortfall",
                "Penalty volume",
            ],
            "MWh": [
                f"{summary.total_load_mwh:,.0f}",
                f"{summary.ppa_delivered_mwh:,.0f}",
                f"{summary.renewable_and_storage_to_ppa_mwh:,.0f}",
                f"{summary.market_buy_to_ppa_mwh:,.0f}",
                f"{summary.allowed_shortfall_mwh:,.0f}",
                f"{summary.penalty_mwh:,.0f}",
            ],
        }
        st.dataframe(pd.DataFrame(gen_data), hide_index=True, width="stretch")

    with cols[1]:
        st.markdown("**Revenue breakdown**")
        mkt_buy_label = (
            "Market buy cost"
            if revenue.market_purchase_cost >= 0
            else "Market buy (negative-price benefit)"
        )
        mkt_buy_display = (
            f"−€{revenue.market_purchase_cost:,.0f}"
            if revenue.market_purchase_cost >= 0
            else f"+€{-revenue.market_purchase_cost:,.0f}"
        )
        rev_data = {
            "Item": [
                "PPA revenue",
                "Merchant revenue",
                mkt_buy_label,
                "Penalty cost",
                "Net revenue",
            ],
            "€": [
                f"€{revenue.ppa_revenue:,.0f}",
                f"€{revenue.excess_revenue:,.0f}",
                mkt_buy_display,
                f"−€{revenue.penalty_cost:,.0f}",
                f"€{revenue.net_revenue:,.0f}",
            ],
        }
        st.dataframe(pd.DataFrame(rev_data), hide_index=True, width="stretch")

    st.markdown("---")

    # ── Charts ─────────────────────────────────────────────────────────────────
    ts = state.get_timeseries()
    if ts is not None:
        from ppa.data_loader import prepare_timeseries
        ts_prep = prepare_timeseries(ts, s)

        cols = st.columns([3, 2])
        with cols[0]:
            st.subheader("Average hourly supply mix")
            supply_mix = build_supply_mix_df(result.dispatch, ts_prep)
            avg_24h = build_24h_avg(supply_mix)
            fig = make_supply_mix_24h_chart(avg_24h, s.ppaload_mw)
            st.plotly_chart(fig, width="stretch", height=500)

        with cols[1]:
            st.subheader("Revenue waterfall")
            fig_rev = make_revenue_breakdown_chart(revenue)
            st.plotly_chart(fig_rev, width="stretch", height=500)


def render() -> None:
    st.title("📊 Results Overview")

    if state.has_multi_year_financial():
        n = len(state.get_multi_year_financial().yearly)
        mode = f"{n}-year European simulation"
        st.caption(f"Showing results from last run: **{mode}**.")
        _render_multi_year_overview(state.get_multi_year_financial())

        if state.has_result():
            st.markdown("---")
            with st.expander("Single-day reference results", expanded=False):
                _render_single_day_overview()

    elif state.has_result():
        st.caption("Showing results from last single-day reference run.")
        _render_single_day_overview()

    else:
        st.info(
            "No results yet. Run the **European simulation** in the **Optimization** tab "
            "to see lifetime financial results here.",
            icon="⚙️",
        )
