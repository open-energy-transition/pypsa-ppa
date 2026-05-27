from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from ppa.results import build_supply_mix_df, build_ops_day_df
from ui import state
from ui.charts import make_supply_mix_day_chart, make_soc_chart, make_price_series_chart


def _no_results_message() -> None:
    st.info(
        "No optimization results yet. Go to the **Optimization** tab and click **Run Optimization**.",
        icon="⚙️",
    )


def _fmt_m(v: float) -> str:
    return f"${v / 1e6:,.2f}M"


def render() -> None:
    st.title("🔍 Results Deep Dive")

    if not state.has_result():
        _no_results_message()
        return

    result = state.get_result()
    s = result.scenario
    fin = state.get_financial()
    ts = state.get_timeseries()

    # ── Financial analysis ─────────────────────────────────────────────────────
    st.subheader("Financial analysis")

    if fin is None:
        st.info(
            "Financial analysis was not run. Enable **Run financial analysis** in the scenario "
            "form and re-run the optimisation.",
            icon="💰",
        )
    else:
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("**CAPEX & OPEX**")
            capex_df = pd.DataFrame(
                [
                    ("Onshore wind", _fmt_m(fin.capex.capex_wind), f"{s.onsw_mw:.0f} MW × ${s.wind_capex_per_kw:,.0f}/kW"),
                    ("Solar PV", _fmt_m(fin.capex.capex_pv), f"{s.pv_mw:.0f} MW × ${s.pv_capex_per_kw:,.0f}/kW"),
                    ("BESS", _fmt_m(fin.capex.capex_bess), f"{s.effective_bess_mwh:.0f} MWh × ${s.bess_capex_per_kwh:,.0f}/kWh"),
                    ("Total CAPEX", _fmt_m(fin.capex.capex_total), ""),
                    ("Annual OPEX", _fmt_m(fin.capex.annual_opex), f"{s.opex_rate:.0%} of CAPEX"),
                ],
                columns=["Component", "Value", "Basis"],
            )
            st.dataframe(capex_df, hide_index=True, use_container_width=True)

        with col2:
            st.markdown("**Project economics**")
            irr_str = f"{fin.project_irr:.1%}" if not np.isnan(fin.project_irr) else "n/a"
            lcoe_str = f"${fin.lcoe:.2f}/MWh" if not np.isnan(fin.lcoe) else "n/a"
            be_str = f"${fin.breakeven_ppa_price:.2f}/MWh" if not np.isnan(fin.breakeven_ppa_price) else "n/a"

            econ_df = pd.DataFrame(
                [
                    ("Scale factor (March → annual)", f"×{fin.scale_factor:.2f}", ""),
                    ("Annual generation (indicative)", f"{fin.annual_gen_mwh:,.0f} MWh", f"March × {fin.scale_factor:.2f}"),
                    ("Annual PPA revenue", _fmt_m(fin.annual_ppa_rev), f"${s.ppa_price:.0f}/MWh"),
                    ("Annual merchant revenue", _fmt_m(fin.annual_merch_rev), f"avg ${fin.avg_merch_price:.2f}/MWh"),
                    ("Annual market purchase cost", _fmt_m(fin.annual_buy_cost), f"avg ${fin.avg_buy_price:.2f}/MWh"),
                    ("Annual net revenue", _fmt_m(fin.annual_net_rev), ""),
                    ("Annual OPEX", _fmt_m(fin.annual_opex), ""),
                    ("Annual pre-tax cashflow", _fmt_m(fin.annual_cf), ""),
                    ("LCOE", lcoe_str, f"at {s.discount_rate:.0%} WACC"),
                    ("Simple payback", f"{fin.simple_payback:.1f} yrs", ""),
                    ("Project IRR", irr_str, f"pre-tax, ungeared, {s.project_life_yrs}-yr life"),
                    ("NPV at WACC", _fmt_m(fin.npv_at_wacc), f"at {s.discount_rate:.0%}"),
                    (f"Breakeven PPA for {s.target_irr:.0%} IRR", be_str, f"vs ${s.ppa_price:.0f}/MWh contracted"),
                ],
                columns=["Metric", "Value", "Note"],
            )
            st.dataframe(econ_df, hide_index=True, use_container_width=True)

    # ── Dispatch detail ────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Daily dispatch detail")

    if ts is not None:
        from ppa.data_loader import prepare_timeseries, get_available_days
        ts_prep = prepare_timeseries(ts, s)
        available_days = get_available_days(ts)
        default_idx = available_days.index(s.chosen_day) if s.chosen_day in available_days else 14
        chosen_day = st.selectbox(
            "Select a day to inspect", available_days, index=default_idx, key="dd_chosen_day"
        )

        col_a, col_b = st.columns([3, 2])
        with col_a:
            supply_mix = build_supply_mix_df(result.dispatch, ts_prep)
            day_mix = supply_mix.loc[chosen_day] if chosen_day in supply_mix.index.strftime("%Y-%m-%d") else supply_mix
            # Filter supply mix to chosen day
            day_mix = supply_mix[supply_mix.index.strftime("%Y-%m-%d") == chosen_day]
            fig = make_supply_mix_day_chart(day_mix, s.ppaload_mw, chosen_day)
            st.plotly_chart(fig, use_container_width=True)

        with col_b:
            ops_df = build_ops_day_df(result.dispatch, chosen_day)
            st.dataframe(ops_df, use_container_width=True)

        # BESS state of charge
        if s.include_bess and s.effective_bess_mwh > 0:
            st.subheader("BESS state of charge")
            fig_soc = make_soc_chart(result.dispatch.soc, s.effective_bess_mwh)
            st.plotly_chart(fig_soc, use_container_width=True)

        # Market price
        st.subheader("Market spot price")
        fig_price = make_price_series_chart(ts_prep)
        st.plotly_chart(fig_price, use_container_width=True)

    # ── Generation statistics ──────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Generation statistics")
    summary = result.summary
    n_hours = result.n_period_hours

    wind_cf = summary.wind_generation_mwh / (s.onsw_mw * n_hours) if s.onsw_mw > 0 else 0.0
    pv_cf = summary.pv_generation_mwh / (s.pv_mw * n_hours) if s.pv_mw > 0 else 0.0
    bess_equiv_cycles = (
        summary.bess_dispatch_mwh / s.effective_bess_mwh if s.include_bess and s.effective_bess_mwh > 0 else 0.0
    )
    avg_soc = float(result.dispatch.soc.mean()) if s.include_bess else 0.0

    stats_df = pd.DataFrame(
        [
            ("Wind capacity factor", f"{wind_cf:.1%}", f"{summary.wind_generation_mwh:,.0f} MWh"),
            ("PV capacity factor", f"{pv_cf:.1%}", f"{summary.pv_generation_mwh:,.0f} MWh"),
            ("BESS equivalent cycles", f"{bess_equiv_cycles:.1f}", f"over {n_hours} h"),
            ("BESS average SoC", f"{avg_soc:.1f} MWh",
             f"{avg_soc / s.effective_bess_mwh:.1%} of capacity" if s.effective_bess_mwh > 0 else ""),
            ("Sold to spot market", f"{summary.sold_to_market_mwh:,.0f} MWh", ""),
        ],
        columns=["Metric", "Value", "Detail"],
    )
    st.dataframe(stats_df, hide_index=True, use_container_width=True)
