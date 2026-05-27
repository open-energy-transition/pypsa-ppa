from __future__ import annotations

import streamlit as st

from ppa.results import build_supply_mix_df, build_24h_avg
from ui import state
from ui.charts import make_supply_mix_24h_chart, make_revenue_breakdown_chart


def _no_results_message() -> None:
    st.info(
        "No optimization results yet. Go to the **Optimization** tab and click **Run Optimization**.",
        icon="⚙️",
    )


def render() -> None:
    st.title("📊 Results Overview")

    if not state.has_result():
        _no_results_message()
        return

    result = state.get_result()
    s = result.scenario
    summary = result.summary
    revenue = result.revenue
    fin = state.get_financial()

    # ── KPI row ───────────────────────────────────────────────────────────────
    st.subheader("Key performance indicators")
    col1, col2, col3, col4, col5 = st.columns(5)

    col1.metric(
        "PPA Fulfilment",
        f"{summary.fulfilled_share:.1%}",
        delta=f"{summary.fulfilled_share - s.required_delivery_share:+.1%} vs target",
        delta_color="normal",
    )
    col2.metric(
        "Penalty Volume",
        f"{summary.penalty_mwh:,.0f} MWh",
        delta=f"{summary.penalty_share_of_load:.1%} of load",
        delta_color="inverse",
    )
    col3.metric(
        "Net Revenue",
        f"${revenue.net_revenue / 1e6:,.2f}M",
        help="PPA revenue + merchant revenue − market purchases − penalty costs (period total)",
    )
    col4.metric(
        "Effective Capture Price",
        f"${revenue.effective_capture_price:.2f}/MWh",
        help="Net revenue ÷ total generation (MWh)",
    )
    if fin is not None:
        col5.metric(
            "LCOE",
            f"${fin.lcoe:.2f}/MWh",
            help=f"Levelised Cost of Energy at {s.discount_rate:.0%} WACC",
        )
    else:
        col5.metric("LCOE", "—", help="Run with financial analysis enabled")

    st.markdown("---")

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
        import pandas as pd
        st.dataframe(pd.DataFrame(gen_data), hide_index=True, use_container_width=True)

    with cols[1]:
        st.markdown("**Revenue breakdown**")
        rev_data = {
            "Item": [
                "PPA revenue",
                "Merchant revenue",
                "Market purchase cost",
                "Penalty cost",
                "Net revenue",
            ],
            "$": [
                f"${revenue.ppa_revenue:,.0f}",
                f"${revenue.excess_revenue:,.0f}",
                f"−${revenue.market_purchase_cost:,.0f}",
                f"−${revenue.penalty_cost:,.0f}",
                f"${revenue.net_revenue:,.0f}",
            ],
        }
        st.dataframe(pd.DataFrame(rev_data), hide_index=True, use_container_width=True)

    st.markdown("---")

    # ── Charts ─────────────────────────────────────────────────────────────────
    ts = state.get_timeseries()
    if ts is not None:
        from ppa.data_loader import prepare_timeseries
        ts_prep = prepare_timeseries(ts, s)

        col_a, col_b = st.columns([3, 2])
        with col_a:
            st.subheader("Average hourly supply mix")
            supply_mix = build_supply_mix_df(result.dispatch, ts_prep)
            avg_24h = build_24h_avg(supply_mix)
            fig = make_supply_mix_24h_chart(avg_24h, s.ppaload_mw)
            st.plotly_chart(fig, use_container_width=True)

        with col_b:
            st.subheader("Revenue waterfall")
            fig_rev = make_revenue_breakdown_chart(revenue)
            st.plotly_chart(fig_rev, use_container_width=True)

    # ── Constraint compliance ──────────────────────────────────────────────────
    st.markdown("---")
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
    import pandas as pd
    st.dataframe(pd.DataFrame(compliance), hide_index=True, use_container_width=True)
