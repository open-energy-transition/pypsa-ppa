from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ppa.financial_model import (
    ProjectFinanceInputs,
    EnergyInputs,
    run_project_finance,
    energy_inputs_from_result,
    energy_inputs_from_results,
    project_finance_inputs_from_scenario,
)
from ppa.financial_model_excel import export_financial_model
from ui import state


# ── Energy interface ──────────────────────────────────────────────────────────


def _energy_source() -> tuple[EnergyInputs | None, list, bool]:
    """Energy inputs, the underlying per-year results, and a multi-year flag.

    The same result set drives both ``EnergyInputs`` (averaged) and the per-year
    hourly sheets, so the workbook's rolled-up totals match the model exactly.
    The multi-year flag tells the model whether merchant prices are already
    escalated per year (so it should not escalate them again)."""
    if state.has_multi_year_results():
        results = [r for r in state.get_multi_year_results() if r is not None]
        if len(results) > 1:
            return energy_inputs_from_results(results), results, True
        if results:
            return energy_inputs_from_results(results), results, False
    if state.has_result():
        r = state.get_result()
        return energy_inputs_from_result(r), [r], False
    return None, [], False


# ── Input widgets ──────────────────────────────────────────────────────────────


def _num(label: str, key: str, default, *, step=None, fmt=None, pct=False, help=None, label_visibility="visible"):
    """Number input that persists its own default into session state once.

    With ``pct=True`` the model value is a decimal fraction (e.g. 0.065) but is
    displayed and edited in percent (6.5), and the return value is converted back
    to a fraction. ``step`` and ``fmt`` are then given in percent terms."""
    scale = 100.0 if pct else 1.0
    if key not in st.session_state:
        st.session_state[key] = float(default) * scale if not isinstance(default, int) else default
    kwargs = {}
    if step is not None:
        kwargs["step"] = step
    if fmt is not None:
        kwargs["format"] = fmt
    val = st.number_input(label, key=key, help=help, label_visibility=label_visibility, **kwargs, )
    return val / scale if pct else val


def _collect_inputs(seed: ProjectFinanceInputs, multi_year: bool) -> ProjectFinanceInputs:
    """Render the editable assumption form and return a ProjectFinanceInputs."""
    f = "fm_"

    with st.expander("💶 Costs (build, connection, devex, O&M)", expanded=False):
        cols = st.columns(4, vertical_alignment="bottom")
        cols[1].markdown("**Onshore wind**")
        cols[2].markdown("**Solar PV**")
        cols[3].markdown("**BESS**")

        cols = st.columns(4, vertical_alignment="bottom")
        cols[0].markdown("**Investment** (€M/MW, €M/MWh):")

        with cols[1]:
            onsw_build = _num("**Onshore wind**", f + "onsw_build", seed.onsw_build_cost, step=0.05, fmt="%.3f", label_visibility="collapsed")

        with cols[2]:
            pv_build = _num("**Solar PV**", f + "pv_build", seed.pv_build_cost, step=0.05, fmt="%.3f", label_visibility="collapsed")

        with cols[3]:
            bess_build = _num("**BESS**", f + "bess_build", seed.bess_build_cost, step=0.05, fmt="%.3f", label_visibility="collapsed")

        cols = st.columns(4)
        cols[0].markdown("**Connection** (€M/MW, €M/MWh):")

        with cols[1]:
            onsw_conn = _num("Onshore wind ", f + "onsw_conn", seed.onsw_connection_cost, step=0.01, fmt="%.3f", label_visibility="collapsed")

        with cols[2]:
            pv_conn = _num("Solar PV ", f + "pv_conn", seed.pv_connection_cost, step=0.01, fmt="%.3f", label_visibility="collapsed")

        with cols[3]:
            bess_conn = _num("BESS ", f + "bess_conn", seed.bess_connection_cost, step=0.01, fmt="%.3f", label_visibility="collapsed")

        cols = st.columns(4)
        cols[0].markdown(
            "**Devex** (€/MW, €M/MWh):",
            help=(
                "Expected cost of reaching FID. Paid as a single lump sum per technology "
                "in the FID period (below), funded 100% by equity."
            ),
        )

        with cols[1]:
            onsw_devex = _num("Onshore wind  ", f + "onsw_devex", seed.onsw_devex, step=0.01, fmt="%.3f", label_visibility="collapsed")

        with cols[2]:
            pv_devex = _num("Solar PV  ", f + "pv_devex", seed.pv_devex, step=0.01, fmt="%.3f", label_visibility="collapsed")

        with cols[3]:
            bess_devex = _num("BESS  ", f + "bess_devex", seed.bess_devex, step=0.01, fmt="%.3f", label_visibility="collapsed")

        cols = st.columns(4)
        cols[0].markdown("**Fixed O&M** (€M/MW, €M/MWh p.a.)")

        with cols[1]:
            onsw_om = _num("Onshore wind   ", f + "onsw_om", seed.onsw_fixed_om, step=0.005, fmt="%.3f", label_visibility="collapsed")

        with cols[2]:
            pv_om = _num("Solar PV   ", f + "pv_om", seed.pv_fixed_om, step=0.005, fmt="%.3f", label_visibility="collapsed")

        with cols[3]:
            bess_om = _num("BESS   ", f + "bess_om", seed.bess_fixed_om, step=0.005, fmt="%.3f", label_visibility="collapsed")

        cols = st.columns(4)
        cols[0].markdown("**Ancillary** (% of revenue)")

        with cols[1]:
            anc = _num("Ancillary (% of revenue)", f + "anc", seed.ancillary_pct, step=0.1, fmt="%.2f", pct=True, label_visibility="collapsed")

    with st.expander("📅 Timing (FID, construction, life)", expanded=False):
        cols = st.columns(4, vertical_alignment="bottom")
        with cols[0]:
            st.markdown("**Overall Settings (yrs)**")
        with cols[1]:
            fid_period = int(_num(
                "FID period", f + "fid_period", seed.fid_period, step=1,
                help="Period devex is paid (100% equity) and construction begins.",
            ))
        with cols[2]:
            duration = int(_num("Model duration (yrs)", f + "duration", seed.model_duration, step=1))
        with cols[3]:
            life = int(_num("Operating life (yrs)", f + "life", seed.operating_life, step=1))

        cols = st.columns(4, vertical_alignment="bottom")
        cols[1].markdown("**Wind**")
        cols[2].markdown("**Solar PV**")
        cols[3].markdown("**BESS**")

        cols = st.columns(4, vertical_alignment="bottom")
        with cols[0]:
            st.markdown("**Construction (yrs)**")
        with cols[1]:
            onsw_con = int(_num("Onshore wind ", f + "onsw_con", seed.onsw_constr_years, step=1, label_visibility="collapsed"))
        with cols[2]:
            pv_con = int(_num("Solar PV ", f + "pv_con", seed.pv_constr_years, step=1, label_visibility="collapsed"))
        with cols[3]:
            bess_con = int(_num("BESS ", f + "bess_con", seed.bess_constr_years, step=1, label_visibility="collapsed"))

    with st.expander("💰 Revenue & indexation", expanded=False):
        cols = st.columns(4)
        with cols[0]:
            tenor = int(_num("PPA contract tenor (yrs)", f + "tenor", seed.ppa_tenor, step=1))
            tariff = _num("PPA tariff (€/MWh)", f + "tariff", seed.ppa_tariff, step=1.0)
        with cols[1]:
            pen = _num("Penalty multiple (×)", f + "pen", seed.penalty_multiple, step=0.1, fmt="%.2f")
            lgc = _num("LGC / GO price (€/MWh)", f + "lgc", seed.lgc_price, step=1.0)
        with cols[2]:
            offset = int(_num("Indexation offset (yrs)", f + "offset", seed.indexation_offset_years, step=1))
            cost_infl = _num("Cost inflation (%/yr)", f + "cost_infl", seed.cost_inflation, step=0.1, fmt="%.2f", pct=True)
        with cols[3]:
            ppa_idx = _num("PPA & LGC indexation (%/yr)", f + "ppa_idx", seed.ppa_indexation, step=0.1, fmt="%.2f", pct=True)
            solar_infl = _num("Solar-hour price infl. (%/yr)", f + "solar_infl", seed.solar_price_inflation, step=0.1, fmt="%.2f", pct=True)
            nonsolar_infl = _num("Non-solar price infl. (%/yr)", f + "nonsolar_infl", seed.nonsolar_price_inflation, step=0.1, fmt="%.2f", pct=True)
        esc_key = f + "esc_merch"
        if esc_key not in st.session_state:
            st.session_state[esc_key] = not multi_year
        escalate_merchant = st.checkbox(
            "Escalate merchant prices over the project life",
            key=esc_key,
            help=(
                "Leave OFF when the energy inputs come from a multi-year optimization that "
                "already escalates market prices each year (avoids double-counting price "
                "growth). Turn ON for a single base-year snapshot. The solar-hour / non-solar "
                "price inflation rates above only apply when this is ON."
            ),
        )
        if multi_year and escalate_merchant:
            st.caption(
                "⚠️ Merchant prices are already escalated by the multi-year energy run: "
                "leaving this on double-counts price growth."
            )

    with st.expander("🏦 Debt, depreciation & tax", expanded=True):
        cols = st.columns(4)
        with cols[0]:
            st.markdown("**Debt**")
            debt_tenor = int(_num("Repayment tenor (yrs)", f + "debt_tenor", seed.debt_tenor, step=1))
            debt_rate = _num("Debt rate (%)", f + "debt_rate", seed.debt_rate, step=0.1, fmt="%.2f", pct=True)
            wacc = _num("Discount rate / WACC (%)", f + "wacc", seed.discount_rate, step=0.1, fmt="%.2f", pct=True)
        with cols[1]:
            st.markdown("**DSCR**")
            dscr_c = _num("DSCR, contracted", f + "dscr_c", seed.dscr_contracted, step=0.05, fmt="%.2f")
            dscr_u = _num("DSCR, uncontracted", f + "dscr_u", seed.dscr_uncontracted, step=0.05, fmt="%.2f")
        with cols[2]:
            st.markdown("**Gearing**")
            gear_c = _num("Max gearing, contracted (%)", f + "gear_c", seed.max_gearing_contracted, step=1.0, fmt="%.1f", pct=True)
            gear_u = _num("Max gearing, uncontracted (%)", f + "gear_u", seed.max_gearing_uncontracted, step=1.0, fmt="%.1f", pct=True)
        with cols[3]:
            st.markdown("**Depreciation & tax**")
            book_dep = _num("Book depreciation (%/yr)", f + "book_dep", seed.book_depreciation_rate, step=0.1, fmt="%.2f", pct=True)
            tax_dep = _num("Tax depreciation (%/yr)", f + "tax_dep", seed.tax_depreciation_rate, step=0.1, fmt="%.2f", pct=True)
            tax_rate = _num("Corporate tax rate (%)", f + "tax_rate", seed.corp_tax_rate, step=1.0, fmt="%.1f", pct=True)

    return ProjectFinanceInputs(
        onsw_build_cost=onsw_build, pv_build_cost=pv_build, bess_build_cost=bess_build,
        onsw_connection_cost=onsw_conn, pv_connection_cost=pv_conn, bess_connection_cost=bess_conn,
        onsw_devex=onsw_devex, pv_devex=pv_devex, bess_devex=bess_devex,
        onsw_fixed_om=onsw_om, pv_fixed_om=pv_om, bess_fixed_om=bess_om, ancillary_pct=anc,
        model_duration=duration, fid_period=fid_period,
        onsw_constr_years=onsw_con, pv_constr_years=pv_con, bess_constr_years=bess_con,
        operating_life=life,
        ppa_tenor=tenor, ppa_tariff=tariff, penalty_multiple=pen, lgc_price=lgc,
        indexation_offset_years=offset, cost_inflation=cost_infl, ppa_indexation=ppa_idx,
        solar_price_inflation=solar_infl, nonsolar_price_inflation=nonsolar_infl,
        escalate_merchant_prices=escalate_merchant,
        debt_tenor=debt_tenor, debt_rate=debt_rate,
        dscr_contracted=dscr_c, dscr_uncontracted=dscr_u,
        max_gearing_contracted=gear_c, max_gearing_uncontracted=gear_u,
        book_depreciation_rate=book_dep, tax_depreciation_rate=tax_dep, corp_tax_rate=tax_rate,
        discount_rate=wacc,
    )


# ── Results display ────────────────────────────────────────────────────────────


def _render_results(r) -> None:
    with st.expander("**Key results**", expanded=True):
        cols = st.columns(4)
        irr = lambda v: f"{v:.1%}" if v == v else "n/a"
        cols[0].metric("Project IRR", irr(r.project_irr), help="Unlevered FCFF return")
        cols[1].metric("Equity IRR", irr(r.equity_irr), help="Levered FCFE return")
        cols[2].metric("Gearing", f"{r.gearing:.1%}")
        cols[3].metric("NPV @ WACC", f"€{r.npv_project:,.0f}m")

        cols = st.columns(4)
        cols[0].metric("Total funding (incl. IDC)", f"€{r.total_capex:,.0f}m")
        cols[1].metric("Debt / Equity", f"€{r.total_debt:,.0f}m / €{r.total_equity:,.0f}m")
        cols[2].metric("Min / Avg DSCR", f"{r.min_dscr:.2f} / {r.avg_dscr:.2f}")
        pb = f"{r.payback_years:.1f} yrs" if r.payback_years < 1e8 else "n/a"
        cols[3].metric("Equity payback / LCOE", f"{pb} · €{r.lcoe:,.0f}/MWh")

        bs_ok = r.max_bs_check < 1e-3
        st.metric(
            "Balance sheet check",
            f"{'✅ balances' if bs_ok else '⚠️ imbalance'} (max |A−L−E| = €{r.max_bs_check:,.4f}m)",
            help="Assets should equal Liabilities + Equity in every period.",
        )

    sc = r.schedule
    periods = r.periods
    ops = sc["ops_flag"].astype(bool)

    # st.markdown("---")
    cols = st.columns(2)

    with st.expander("**Annual results**", expanded=True):
        (
            tab_chart1, tab_chart2, tab_chart3,
            tab_capex, tab_revenue, tab_pl, tab_bs, tab_cf,
        ) = st.tabs([
            "| Cumulative equity cash flow (FCFE)",
            "| Revenue: contracted vs uncontracted",
            "| Debt service & DSCR",
            "| Capex & devex by technology",
            "| Revenue by type",
            "| P&L statement",
            "| Balance sheet",
            "| Cash flow statement",
        ])
        with tab_chart1:
            # Cumulative equity cash flow
            st.markdown("**Cumulative equity cash flow (FCFE)**")
            cum = np.cumsum(sc["fcfe"])
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=periods, y=cum, mode="lines", name="Cumulative FCFE",
                                    line=dict(color="#2E7D32", width=2), fill="tozeroy",
                                    fillcolor="rgba(46,125,50,0.08)"))
            fig.add_hline(y=0, line_dash="dash", line_color="gray")
            fig.update_layout(height=400, margin=dict(t=10, b=30), xaxis_title="Period",
                            yaxis_title="€m")
            st.plotly_chart(fig, width="stretch")

        with tab_chart2:
            # Revenue split
            st.markdown("**Revenue: contracted vs uncontracted**")
            fig = go.Figure()
            fig.add_trace(go.Bar(x=periods[ops], y=sc["net_contracted_rev"][ops],
                                name="Contracted", marker_color="#1565C0"))
            fig.add_trace(go.Bar(x=periods[ops], y=sc["net_uncontracted_rev"][ops],
                                name="Uncontracted (merchant + LGC)", marker_color="#90CAF9"))
            fig.update_layout(barmode="stack", height=400, margin=dict(t=10, b=30),
                            xaxis_title="Period", yaxis_title="€m",
                            legend=dict(orientation="h", y=1.15))
            st.plotly_chart(fig, width="stretch")

        with tab_chart3:
            # Debt balance & DSCR
            st.markdown("**Debt service & DSCR**")
            fig = go.Figure()
            fig.add_trace(go.Bar(x=periods[ops], y=sc["interest"][ops], name="Interest", marker_color="#EF6C00"))
            fig.add_trace(go.Bar(x=periods[ops], y=sc["loan_repay"][ops], name="Principal", marker_color="#FFB74D"))
            dscr = sc["dscr"]
            fig.add_trace(go.Scatter(x=periods[ops], y=dscr[ops], name="DSCR", yaxis="y2",
                                    mode="lines+markers", line=dict(color="#1B5E20", width=2)))
            fig.update_layout(barmode="stack", height=400, margin=dict(t=10, b=30),
                            xaxis_title="Period", yaxis_title="€m",
                            yaxis2=dict(title="DSCR", overlaying="y", side="right", showgrid=False),
                            legend=dict(orientation="h", y=1.15))
            st.plotly_chart(fig, width="stretch")

        with tab_capex:
            st.markdown("**Capex & devex by technology (€m)**")
            df = pd.DataFrame({
                "Period": periods.astype(int),
                "Devex: Wind": sc["devex_onsw"],
                "Devex: Solar PV": sc["devex_pv"],
                "Devex: BESS": sc["devex_bess"],
                "Devex: total": sc["devex"],
                "Capex: Wind": sc["capex_onsw"],
                "Capex: Solar PV": sc["capex_pv"],
                "Capex: BESS": sc["capex_bess"],
                "Capex: total": sc["capex"],
                "Total capital spend": sc["total_capital_spend"],
            }).round(3)
            st.dataframe(df.set_index("Period"), width="stretch", height="content")

        with tab_revenue:
            st.markdown("**Revenue by type: volume × price = revenue**")
            df = pd.DataFrame({
                "Period": periods.astype(int),
                "PPA volume (GWh)": sc["vol_ppa_gwh"],
                "PPA price (€/MWh)": sc["price_ppa"],
                "PPA revenue (€m)": sc["rev_ppa"],
                "Penalty volume (GWh)": sc["vol_penalty_gwh"],
                "Penalty price (€/MWh)": sc["price_penalty"],
                "Penalty cost (€m)": -sc["cost_penalty"],
                "Merchant solar volume (GWh)": sc["vol_merchant_solar_gwh"],
                "Merchant solar price (€/MWh)": sc["price_merchant_solar"],
                "Merchant solar revenue (€m)": sc["rev_merchant_solar"],
                "Merchant non-solar volume (GWh)": sc["vol_merchant_nonsolar_gwh"],
                "Merchant non-solar price (€/MWh)": sc["price_merchant_nonsolar"],
                "Merchant non-solar revenue (€m)": sc["rev_merchant_nonsolar"],
                "LGC volume (GWh)": sc["vol_lgc_gwh"],
                "LGC price (€/MWh)": sc["price_lgc"],
                "LGC revenue (€m)": sc["rev_lgc"],
                "Total revenue (€m)": sc["total_rev"],
            }).round(3)
            st.dataframe(df.set_index("Period"), width="stretch", height="content")

        with tab_pl:
            st.markdown("**Profit & loss statement (€m)**")
            df = pd.DataFrame({
                "Period": periods.astype(int),
                "Net contracted revenue": sc["net_contracted_rev"],
                "Net uncontracted revenue": sc["net_uncontracted_rev"],
                "Total revenue": sc["total_rev"],
                "Opex": -sc["opex"],
                "EBITDA": sc["ebitda"],
                "Book depreciation": -sc["book_dep"],
                "EBIT": sc["ebitda"] - sc["book_dep"],
                "Interest expense": -sc["interest"],
                "Profit before tax": sc["pbt"],
                "Income tax": -sc["tax"],
                "Profit after tax": sc["pat"],
            }).round(2)
            st.dataframe(df.set_index("Period"), width="stretch", height="content")

        with tab_bs:
            st.markdown("**Balance sheet (€m, closing balances)**")
            df = pd.DataFrame({
                "Period": periods.astype(int),
                "PP&E, net": sc["ppe_net"],
                "Cash": sc["cash_balance"],
                "Total assets": sc["total_assets"],
                "Debt": sc["debt_balance"],
                "Total liabilities": sc["total_liabilities"],
                "Share capital": sc["share_capital"],
                "Retained earnings": sc["retained_earnings"],
                "Total equity": sc["total_equity_bs"],
                "Check (A − L − E)": sc["bs_check"],
            }).round(4)
            st.dataframe(df.set_index("Period"), width="stretch", height="content")
            if r.max_bs_check >= 1e-3:
                st.warning(
                    f"Balance sheet does not balance in every period (max |A−L−E| = "
                    f"€{r.max_bs_check:,.4f}m). Check the check column above."
                )

        with tab_cf:
            st.markdown("**Cash flow statement (€m)**")
            df = pd.DataFrame({
                "Period": periods.astype(int),
                "Cash from operations": sc["cfo"],
                "Cash from investing": sc["cfi"],
                "Cash from financing": sc["cff"],
                "Net cash flow": sc["net_cash_flow"],
                "Cash balance": sc["cash_balance"],
                "FCFF (project)": sc["fcff"],
                "FCFE (equity)": sc["fcfe"],
                "DSCR": sc["dscr"],
            }).round(3)
            st.dataframe(df.set_index("Period"), width="stretch", height="content")


# ── Tab entry point ────────────────────────────────────────────────────────────


def render() -> None:
    st.title("🏦 Financial Model")
    st.caption(
        "A streamlined project-finance appraisal layered on the energy-model results: "
        "indexed PPA + merchant revenue, DSCR-sculpted debt, depreciation, tax → "
        "Project & Equity IRR. Run it here, or export a live Excel workbook."
    )

    energy, results_list, multi_year = _energy_source()
    if energy is None:
        st.info(
            "No energy results yet. Run an optimization in the **Optimization** tab first: "
            "its generation, PPA delivery and merchant volumes feed this model.",
            icon="⚙️",
        )
        return

    scenario = state.get_scenario()
    seed = (
        project_finance_inputs_from_scenario(scenario)
        if scenario is not None else ProjectFinanceInputs()
    )

    # ── Energy interface (pre-filled, from PyPSA) ─────────────────────────────
    with st.expander("⚡ Energy inputs from PyPSA (pre-filled)", expanded=False):
        st.caption(f"Representative operating year derived from: **{energy.name}**")
        cols = st.columns(4)
        with cols[0]:
            st.metric("PPA delivered",
                      f"{energy.ppa_gwh:,.0f} GWh")
            st.metric("Penalty volume",
                      f"{energy.penalty_gwh:,.0f} GWh")

        with cols[1]:
            st.metric("Total gen (solar / non-solar)",
                      f"{energy.total_solar_gwh:,.0f} / {energy.total_nonsolar_gwh:,.0f} GWh")
            st.metric("Capacity (Wind)",
                      f"{energy.onsw_mw:,.0f} MW")

        with cols[2]:
            st.metric("Excess sold (solar / non-solar)",
                      f"{energy.excess_solar_gwh:,.0f} / {energy.excess_nonsolar_gwh:,.0f} GWh")
            st.metric("Capacity (PV)",
                      f"{energy.pv_mw:,.0f} MW")

        with cols[3]:
            st.metric("Merchant capture (solar / non-solar)",
                      f"€{energy.sell_solar_price:,.0f} / €{energy.sell_nonsolar_price:,.0f}")
            st.metric("Capacity (BESS)",
                      f"{energy.bess_mw:,.0f} MW / {energy.bess_mwh:,.0f} MWh")

    # ── Editable financial assumptions ────────────────────────────────────────
    st.subheader("Financial assumptions")
    inputs = _collect_inputs(seed, multi_year)

    # ── Run ───────────────────────────────────────────────────────────────────
    run = st.button("▶️ Run financial model", type="primary", width="stretch")
    if run:
        try:
            result = run_project_finance(inputs, energy)
            state.set_project_finance(result)
        except Exception as exc:  # surface modelling errors rather than crash the tab
            st.error(f"Financial model failed: {exc}")
            return

    result = state.get_project_finance()
    if result is None:
        st.info("Set your assumptions above and click **Run financial model**.", icon="▶️")
        return

    # st.markdown("---")
    _render_results(result)

    # ── Export ────────────────────────────────────────────────────────────────
    # st.markdown("---")
    with st.expander("⚡ Export financial model as Excel(R) file", expanded=False):
        # st.subheader("Export")
        n_years = len(results_list)
        st.caption(
            "Download a streamlined, **live** Excel workbook: one **Hourly** sheet per "
            f"simulated year ({n_years}) with full hourly dispatch, the Energy totals rolled "
            "up from those hours, and the revenue→tax→cash-flow chain and IRRs as formulas."
        )
        if n_years > 12:
            st.caption(
                f"⚠️ {n_years} years × 8,760 hours means a fairly large workbook, so it can take a "
                "moment to build before it's ready to download."
            )
        try:
            xlsx = export_financial_model(result.inputs, result.energy, result, year_results=results_list)
            fname = f"financial_model_{(result.energy.name or 'scenario').replace(' ', '_')}.xlsx"
            st.download_button(
                "⬇️ Download financial model",
                data=xlsx,
                file_name=fname,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
            )
        except Exception as exc:
            st.error(f"Excel export failed: {exc}")
