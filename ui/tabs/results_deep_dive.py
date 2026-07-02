from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import streamlit as st

from ppa.counterfactuals import compute_counterfactuals
from ppa.results import build_supply_mix_df, build_ops_day_df
from ui import state
from ui.charts import (
    make_supply_mix_day_chart,
    make_soc_chart,
    make_price_series_chart,
    make_counterfactual_bar_chart,
    make_cumulative_cost_chart,
    make_multi_year_counterfactual_chart,
)


def _fmt_m(v: float) -> str:
    return f"€{v / 1e6:,.2f}M"


def _render_dispatch_section(result, s, chosen_day: str) -> None:
    supply_mix = build_supply_mix_df(result.dispatch)
    day_mix = supply_mix[supply_mix.index.strftime("%Y-%m-%d") == chosen_day]
    fig = make_supply_mix_day_chart(day_mix, s.ppaload_mw, chosen_day)
    st.plotly_chart(fig, width="stretch", height=500)

    if s.include_bess and s.effective_bess_mwh > 0:
        st.subheader("BESS state of charge")
        fig_soc = make_soc_chart(result.dispatch.soc, s.effective_bess_mwh)
        st.plotly_chart(fig_soc, width="stretch", height=400)

    if getattr(result, "market_prices", None) is not None:
        st.subheader("Market spot price")
        price_day = result.market_prices[result.market_prices.index.strftime("%Y-%m-%d") == chosen_day]
        fig_price = make_price_series_chart(price_day, title=f"Day-ahead price — {chosen_day}")
        st.plotly_chart(fig_price, width="stretch", height=300)


def _render_gen_stats(result, s) -> None:
    summary = result.summary
    n_hours = result.n_period_hours
    wind_cf = summary.wind_generation_mwh / (s.onsw_mw * n_hours) if s.onsw_mw > 0 else 0.0
    pv_cf = summary.pv_generation_mwh / (s.pv_mw * n_hours) if s.pv_mw > 0 else 0.0
    bess_cycles = summary.bess_dispatch_mwh / s.effective_bess_mwh if s.include_bess and s.effective_bess_mwh > 0 else 0.0
    avg_soc = float(result.dispatch.soc.mean()) if s.include_bess else 0.0

    stats_df = pd.DataFrame(
        [
            ("Wind capacity factor", f"{wind_cf:.1%}", f"{summary.wind_generation_mwh:,.0f} MWh"),
            ("PV capacity factor", f"{pv_cf:.1%}", f"{summary.pv_generation_mwh:,.0f} MWh"),
            ("BESS equivalent cycles", f"{bess_cycles:.1f}", f"over {n_hours} h"),
            ("BESS average SoC", f"{avg_soc:.1f} MWh",
             f"{avg_soc / s.effective_bess_mwh:.1%} of capacity" if s.effective_bess_mwh > 0 else ""),
            ("Sold to spot market", f"{summary.sold_to_market_mwh:,.0f} MWh", ""),
        ],
        columns=["Metric", "Value", "Detail"],
    )
    cols = st.columns(2)
    cols[0].dataframe(stats_df, hide_index=True, width="stretch")


def _render_multi_year_counterfactuals(results, fin, s) -> None:
    # Need market_prices on each result — skip if not available (old cached runs)
    if not any(getattr(r, "market_prices", None) is not None for r in results):
        return

    st.markdown("---")
    st.subheader("Counterfactual procurement comparison")
    st.caption(
        "Compares the offtaker's all-in cost under the PPA versus alternative sourcing strategies. "
        "CAL Y+1 price is escalated year-on-year at the same rate as market prices."
    )

    yearly_cfs = []
    for idx, (yf, res) in enumerate(zip(fin.yearly, results)):
        prices = getattr(res, "market_prices", None)
        if prices is None:
            continue
        # Escalate CAL forward price same as market prices
        cal_price = s.cal_forward_price * (1 + s.price_escalation_rate) ** idx
        year_scenario = dataclasses.replace(res.scenario, cal_forward_price=cal_price)
        ts_mock = pd.DataFrame({"ts_MktPrice": prices})
        cf = compute_counterfactuals(ts_mock, year_scenario, res)
        yearly_cfs.append((yf.year, cf, cal_price))

    if not yearly_cfs:
        st.info("Re-run the European simulation to see counterfactual data.")
        return

    years = [y for y, _, _ in yearly_cfs]
    ppa_prices = [cf.ppa_effective_price for _, cf, _ in yearly_cfs]
    spot_prices = [cf.spot_avg_price for _, cf, _ in yearly_cfs]
    cal_prices = [cf.cal_avg_price for _, cf, _ in yearly_cfs]
    blended_prices = [cf.blended_avg_price for _, cf, _ in yearly_cfs]

    st.plotly_chart(
        make_multi_year_counterfactual_chart(years, ppa_prices, spot_prices, cal_prices, blended_prices),
        width="stretch",
    )

    # Lifetime totals table
    total_load = sum(cf.total_load_mwh for _, cf, _ in yearly_cfs)
    total_spot = sum(cf.spot_cost for _, cf, _ in yearly_cfs)
    total_cal = sum(cf.cal_cost for _, cf, _ in yearly_cfs)
    total_blended = sum(cf.blended_cost for _, cf, _ in yearly_cfs)
    total_ppa = sum(cf.ppa_offtaker_cost for _, cf, _ in yearly_cfs)

    def _eff(cost): return cost / total_load if total_load > 0 else 0.0
    def _em(cost): return f"€{cost / 1e6:.2f}M"

    tbl = pd.DataFrame([
        ("PPA (offtaker)", f"€{_eff(total_ppa):.2f}/MWh", _em(total_ppa), "—"),
        ("Spot-only", f"€{_eff(total_spot):.2f}/MWh", _em(total_spot),
         f"€{(total_spot - total_ppa) / 1e6:+.2f}M vs PPA"),
        ("CAL Y+1 (escalated)", f"€{_eff(total_cal):.2f}/MWh", _em(total_cal),
         f"€{(total_cal - total_ppa) / 1e6:+.2f}M vs PPA"),
        ("Blended", f"€{_eff(total_blended):.2f}/MWh", _em(total_blended),
         f"€{(total_blended - total_ppa) / 1e6:+.2f}M vs PPA"),
    ], columns=["Strategy", "Lifetime effective price", "Lifetime total cost", "vs PPA"])
    st.dataframe(tbl, hide_index=True, width="stretch")


def _render_multi_year_deep_dive() -> None:
    results = state.get_multi_year_results()
    fin = state.get_multi_year_financial()
    s = state.get_scenario()

    # ── Year + day selectors ──────────────────────────────────────────────────
    year_options = [y.year for y in fin.yearly]
    cols = st.columns(2)
    selected_year = cols[0].selectbox("Simulation year", year_options, key="dd_year")
    year_idx = year_options.index(selected_year)
    result = results[year_idx]

    available_days = sorted(result.dispatch.wind_gen.index.normalize().unique().strftime("%Y-%m-%d"))
    chosen_day = cols[1].selectbox("Day to inspect", available_days, index=0, key="dd_chosen_day1")

    # ── Financial summary for selected year ───────────────────────────────────
    st.markdown("---")
    st.subheader(f"Year {selected_year} — financial summary")
    yf = fin.yearly[year_idx]
    cols = st.columns(5)
    cols[0].metric("PPA Revenue", f"€{yf.ppa_revenue / 1e6:.2f}M")
    cols[1].metric("Merchant Revenue", f"€{yf.merch_revenue / 1e6:.2f}M")
    cols[2].metric("Net Cash Flow", f"€{yf.net_cashflow / 1e6:.2f}M")
    cols[3].metric("Delivery Rate", f"{yf.fulfilled_share:.1%}")
    cols[4].metric("Wind+PV Gen", f"{(yf.wind_gen_mwh + yf.pv_gen_mwh) / 1e3:.0f} GWh")

    # ── Lifetime project economics ────────────────────────────────────────────
    with st.expander("Lifetime project economics", expanded=False):
        cols = st.columns(2)
        with cols[0]:
            st.markdown("**CAPEX & OPEX**")
            capex_df = pd.DataFrame(
                [
                    ("Onshore wind", _fmt_m(fin.capex.capex_wind), f"{s.onsw_mw:.0f} MW × €{s.wind_capex_per_kw:,.0f}/kW"),
                    ("Solar PV", _fmt_m(fin.capex.capex_pv), f"{s.pv_mw:.0f} MW × €{s.pv_capex_per_kw:,.0f}/kW"),
                    ("BESS", _fmt_m(fin.capex.capex_bess), f"{s.effective_bess_mwh:.0f} MWh × €{s.bess_capex_per_kwh:,.0f}/kWh"),
                    ("Total CAPEX", _fmt_m(fin.capex.capex_total), ""),
                    ("Annual OPEX", _fmt_m(fin.annual_opex), f"{s.opex_rate:.0%} of CAPEX"),
                ],
                columns=["Component", "Value", "Basis"],
            )
            st.dataframe(capex_df, hide_index=True, width="stretch")
        with cols[1]:
            st.markdown("**Project economics**")
            irr_str = f"{fin.irr:.1%}" if fin.irr == fin.irr else "n/a"
            lcoe_str = f"€{fin.lcoe:.2f}/MWh" if fin.lcoe == fin.lcoe else "n/a"
            payback_str = f"{fin.simple_payback:.1f} yrs" if fin.simple_payback < 1e8 else "n/a"
            econ_df = pd.DataFrame(
                [
                    ("NPV", _fmt_m(fin.npv), f"at {s.discount_rate:.0%} WACC"),
                    ("Project IRR", irr_str, f"{s.project_life_yrs}-yr life"),
                    ("LCOE", lcoe_str, f"at {s.discount_rate:.0%} WACC"),
                    ("Simple payback", payback_str, ""),
                    ("Total lifetime revenue", _fmt_m(fin.total_lifetime_revenue), ""),
                    ("Total lifetime generation", f"{fin.total_lifetime_generation_mwh / 1e3:.0f} GWh", ""),
                ],
                columns=["Metric", "Value", "Note"],
            )
            st.dataframe(econ_df, hide_index=True, width="stretch")

    # ── Daily dispatch ────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader(f"Hourly dispatch — {chosen_day}")
    _render_dispatch_section(result, result.scenario, chosen_day)

    # ── Generation statistics ─────────────────────────────────────────────────
    st.markdown("---")
    st.subheader(f"Generation statistics — {selected_year}")
    _render_gen_stats(result, result.scenario)

    # ── Counterfactual procurement comparison ─────────────────────────────────
    _render_multi_year_counterfactuals(results, fin, s)


def _render_single_day_deep_dive() -> None:
    result = state.get_result()
    s = result.scenario
    fin = state.get_financial()
    ts = state.get_timeseries()

    # ── Financial analysis ────────────────────────────────────────────────────
    st.subheader("Financial analysis")

    if fin is None:
        st.info(
            "Financial analysis was not run. Enable **Run financial analysis** in the scenario "
            "form and re-run the optimisation.",
            icon="💰",
        )
    else:
        cols = st.columns(2)
        with cols[0]:
            st.markdown("**CAPEX & OPEX**")
            capex_df = pd.DataFrame(
                [
                    ("Onshore wind", _fmt_m(fin.capex.capex_wind), f"{s.onsw_mw:.0f} MW × €{s.wind_capex_per_kw:,.0f}/kW"),
                    ("Solar PV", _fmt_m(fin.capex.capex_pv), f"{s.pv_mw:.0f} MW × €{s.pv_capex_per_kw:,.0f}/kW"),
                    ("BESS", _fmt_m(fin.capex.capex_bess), f"{s.effective_bess_mwh:.0f} MWh × €{s.bess_capex_per_kwh:,.0f}/kWh"),
                    ("Total CAPEX", _fmt_m(fin.capex.capex_total), ""),
                    ("Annual OPEX", _fmt_m(fin.capex.annual_opex), f"{s.opex_rate:.0%} of CAPEX"),
                ],
                columns=["Component", "Value", "Basis"],
            )
            st.dataframe(capex_df, hide_index=True, width="stretch")

        with cols[1]:
            st.markdown("**Project economics**")
            irr_str = f"{fin.project_irr:.1%}" if not np.isnan(fin.project_irr) else "n/a"
            lcoe_str = f"€{fin.lcoe:.2f}/MWh" if not np.isnan(fin.lcoe) else "n/a"
            be_str = f"€{fin.breakeven_ppa_price:.2f}/MWh" if not np.isnan(fin.breakeven_ppa_price) else "n/a"
            econ_df = pd.DataFrame(
                [
                    ("Scale factor (period → annual)", f"×{fin.scale_factor:.2f}", ""),
                    ("Annual generation (indicative)", f"{fin.annual_gen_mwh:,.0f} MWh", ""),
                    ("Annual PPA revenue", _fmt_m(fin.annual_ppa_rev), f"€{s.ppa_price:.0f}/MWh"),
                    ("Annual merchant revenue", _fmt_m(fin.annual_merch_rev), f"avg €{fin.avg_merch_price:.2f}/MWh"),
                    ("Annual market purchase cost", _fmt_m(fin.annual_buy_cost), f"avg €{fin.avg_buy_price:.2f}/MWh"),
                    ("Annual net revenue", _fmt_m(fin.annual_net_rev), ""),
                    ("Annual OPEX", _fmt_m(fin.annual_opex), ""),
                    ("Annual pre-tax cashflow", _fmt_m(fin.annual_cf), ""),
                    ("LCOE", lcoe_str, f"at {s.discount_rate:.0%} WACC"),
                    ("Simple payback", f"{fin.simple_payback:.1f} yrs", ""),
                    ("Project IRR", irr_str, f"pre-tax, {s.project_life_yrs}-yr life"),
                    ("NPV at WACC", _fmt_m(fin.npv_at_wacc), f"at {s.discount_rate:.0%}"),
                    (f"Breakeven PPA for {s.target_irr:.0%} IRR", be_str, f"vs €{s.ppa_price:.0f}/MWh contracted"),
                ],
                columns=["Metric", "Value", "Note"],
            )
            st.dataframe(econ_df, hide_index=True, width="stretch", height=500)

    # ── Dispatch detail ────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Daily dispatch detail")

    if ts is not None:
        from ppa.data_loader import prepare_timeseries, get_available_days
        ts_prep = prepare_timeseries(ts, s)
        available_days = get_available_days(ts)
        default_idx = available_days.index(s.chosen_day) if s.chosen_day in available_days else 14
        chosen_day = st.selectbox("Select a day to inspect", available_days, index=default_idx, key="dd_chosen_day2")

        _render_dispatch_section(result, s, chosen_day)

        st.subheader("Market spot price")
        if getattr(result, "market_prices", None) is not None:
            fig_price = make_price_series_chart(result.market_prices, title="Market spot price")
        else:
            fig_price = make_price_series_chart(ts_prep)
        st.plotly_chart(fig_price, width="stretch", height=400)

    # ── Generation statistics ──────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Generation statistics")
    _render_gen_stats(result, s)

    # ── Counterfactual procurement comparison ──────────────────────────────────
    if state.has_counterfactual():
        cf = state.get_counterfactual()
        st.markdown("---")
        st.subheader("Counterfactual procurement comparison")
        st.markdown(
            "How does the PPA cost compare to what the offtaker would have paid "
            "under alternative sourcing strategies? All figures are for the modelled period."
        )

        cols = st.columns([1, 2])
        with cols[0]:
            fig_cf = make_counterfactual_bar_chart(cf, s)
            st.plotly_chart(fig_cf, width="stretch", height=400)
        with cols[1]:
            fig_cum = make_cumulative_cost_chart(cf)
            st.plotly_chart(fig_cum, width="stretch", height=400)

        cf_table = pd.DataFrame(
            [
                ("Spot-only", f"€{cf.spot_avg_price:.2f}", f"€{cf.spot_cost / 1e6:.3f}M",
                 f"€{cf.spot_cost - cf.ppa_offtaker_cost:+,.0f}"),
                (f"CAL Y+1 (€{s.cal_forward_price:.0f}/MWh)", f"€{cf.cal_avg_price:.2f}",
                 f"€{cf.cal_cost / 1e6:.3f}M", f"€{cf.cal_cost - cf.ppa_offtaker_cost:+,.0f}"),
                (f"Blended ({s.cal_hedge_fraction:.0%} CAL)", f"€{cf.blended_avg_price:.2f}",
                 f"€{cf.blended_cost / 1e6:.3f}M", f"€{cf.blended_cost - cf.ppa_offtaker_cost:+,.0f}"),
                ("PPA (offtaker)", f"€{cf.ppa_effective_price:.2f}",
                 f"€{cf.ppa_offtaker_cost / 1e6:.3f}M", "—"),
            ],
            columns=["Strategy", "Effective €/MWh", "Period total", "vs PPA (€, + = more expensive)"],
        )
        st.dataframe(cf_table, hide_index=True, width="stretch")


def render() -> None:
    st.title("🔍 Detailed Results")

    if state.has_multi_year_results() and state.has_multi_year_financial():
        n = len(state.get_multi_year_financial().yearly)
        st.caption(f"Showing results from last European simulation run ({n} year(s)).")
        _render_multi_year_deep_dive()

        if state.has_result():
            st.markdown("---")
            with st.expander("Single-day reference deep dive", expanded=False):
                _render_single_day_deep_dive()

    elif state.has_result():
        st.caption("Showing results from last single-day reference run.")
        _render_single_day_deep_dive()

    else:
        st.info(
            "No results yet. Run the **European simulation** in the **Optimization** tab "
            "to explore hourly dispatch for any day in any simulated year.",
            icon="⚙️",
        )
