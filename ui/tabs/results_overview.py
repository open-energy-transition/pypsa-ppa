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
    cols = st.columns(4)
    cols[0].metric(
        "PPA Fulfilment",
        f"{summary.fulfilled_share:.1%}",
        delta=f"{summary.fulfilled_share - s.required_delivery_share:+.1%} vs target",
        delta_color="normal",
    )
    cols[1].metric(
        "Net Revenue",
        f"${revenue.net_revenue / 1e6:,.2f}M",
        help="PPA revenue + merchant revenue − market purchases − penalty costs (period total)",
    )
    cols[2].metric(
        "Effective Capture Price",
        f"${revenue.effective_capture_price:.2f}/MWh",
        help="Net revenue ÷ total generation (MWh)",
    )
    if fin is not None:
        cols[3].metric(
            "LCOE",
            f"${fin.lcoe:.2f}/MWh",
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
            "Effective $/MWh for the modelled period — covers shortfall hours at spot for the PPA column."
        )
        cols = st.columns(4)
        cols[0].metric(
            "PPA (offtaker)",
            f"${cf.ppa_effective_price:.2f}/MWh",
            help="PPA tariff for delivered MWh + spot price for any undelivered load.",
        )
        cols[1].metric(
            "Spot-only",
            f"${cf.spot_avg_price:.2f}/MWh",
            delta=f"{cf.spot_avg_price - cf.ppa_effective_price:+.2f} $/MWh vs PPA",
            delta_color="normal",
            help="100% of load sourced at real-time spot each hour.",
        )
        cols[2].metric(
            f"CAL Y+1 (${s.cal_forward_price:.0f}/MWh)",
            f"${cf.cal_avg_price:.2f}/MWh",
            delta=f"{cf.cal_avg_price - cf.ppa_effective_price:+.2f} $/MWh vs PPA",
            delta_color="normal",
            help="Flat baseload forward contract; zero spot exposure.",
        )
        cols[3].metric(
            f"Blended ({s.cal_hedge_fraction:.0%} CAL)",
            f"${cf.blended_avg_price:.2f}/MWh",
            delta=f"{cf.blended_avg_price - cf.ppa_effective_price:+.2f} $/MWh vs PPA",
            delta_color="normal",
            help=f"{s.cal_hedge_fraction:.0%} of load at CAL Y+1 forward + remainder at spot.",
        )

    st.markdown("---")

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
        import pandas as pd
        st.dataframe(pd.DataFrame(gen_data), hide_index=True, width="stretch")

    with cols[1]:
        st.markdown("**Revenue breakdown**")
        mkt_buy_label = (
            "Market buy cost"
            if revenue.market_purchase_cost >= 0
            else "Market buy (negative-price benefit)"
        )
        mkt_buy_display = (
            f"−${revenue.market_purchase_cost:,.0f}"
            if revenue.market_purchase_cost >= 0
            else f"+${-revenue.market_purchase_cost:,.0f}"
        )
        rev_data = {
            "Item": [
                "PPA revenue",
                "Merchant revenue",
                mkt_buy_label,
                "Penalty cost",
                "Net revenue",
            ],
            "$": [
                f"${revenue.ppa_revenue:,.0f}",
                f"${revenue.excess_revenue:,.0f}",
                mkt_buy_display,
                f"−${revenue.penalty_cost:,.0f}",
                f"${revenue.net_revenue:,.0f}",
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
