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


def _num(label: str, key: str, default, *, step=None, fmt=None, pct=False, help=None):
    """Number input that persists its own default into session state once."""
    if key not in st.session_state:
        st.session_state[key] = float(default) if not isinstance(default, int) else default
    kwargs = {}
    if step is not None:
        kwargs["step"] = step
    if fmt is not None:
        kwargs["format"] = fmt
    return st.number_input(label, key=key, help=help, **kwargs)


def _collect_inputs(seed: ProjectFinanceInputs, multi_year: bool) -> ProjectFinanceInputs:
    """Render the editable assumption form and return a ProjectFinanceInputs."""
    f = "fm_"

    with st.expander("💶 Costs (build, connection, devex, O&M)", expanded=False):
        st.caption("Costs in €m/MW (€m/MWh for BESS energy).")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("**Build cost**")
            onsw_build = _num("Onshore wind", f + "onsw_build", seed.onsw_build_cost, step=0.05, fmt="%.3f")
            pv_build = _num("Solar PV", f + "pv_build", seed.pv_build_cost, step=0.05, fmt="%.3f")
            bess_build = _num("BESS", f + "bess_build", seed.bess_build_cost, step=0.05, fmt="%.3f")
        with c2:
            st.markdown("**Connection**")
            onsw_conn = _num("Onshore wind ", f + "onsw_conn", seed.onsw_connection_cost, step=0.01, fmt="%.3f")
            pv_conn = _num("Solar PV ", f + "pv_conn", seed.pv_connection_cost, step=0.01, fmt="%.3f")
            bess_conn = _num("BESS ", f + "bess_conn", seed.bess_connection_cost, step=0.01, fmt="%.3f")
            st.markdown("**Devex**")
            onsw_devex = _num("Onshore wind  ", f + "onsw_devex", seed.onsw_devex, step=0.01, fmt="%.3f")
            pv_devex = _num("Solar PV  ", f + "pv_devex", seed.pv_devex, step=0.01, fmt="%.3f")
            bess_devex = _num("BESS  ", f + "bess_devex", seed.bess_devex, step=0.01, fmt="%.3f")
        with c3:
            st.markdown("**Fixed O&M (p.a.)**")
            onsw_om = _num("Onshore wind   ", f + "onsw_om", seed.onsw_fixed_om, step=0.005, fmt="%.4f")
            pv_om = _num("Solar PV   ", f + "pv_om", seed.pv_fixed_om, step=0.005, fmt="%.4f")
            bess_om = _num("BESS   ", f + "bess_om", seed.bess_fixed_om, step=0.005, fmt="%.4f")
            anc = _num("Ancillary (% of revenue)", f + "anc", seed.ancillary_pct, step=0.005, fmt="%.3f")

    with st.expander("📅 Timing (development, construction, life)", expanded=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            duration = int(_num("Model duration (yrs)", f + "duration", seed.model_duration, step=1))
            life = int(_num("Operating life (yrs)", f + "life", seed.operating_life, step=1))
            dev_start = int(_num("Development start period", f + "dev_start", seed.development_start, step=1))
        with c2:
            st.markdown("**Development (yrs)**")
            onsw_dev = int(_num("Onshore wind", f + "onsw_dev", seed.onsw_dev_years, step=1))
            pv_dev = int(_num("Solar PV", f + "pv_dev", seed.pv_dev_years, step=1))
            bess_dev = int(_num("BESS", f + "bess_dev", seed.bess_dev_years, step=1))
        with c3:
            st.markdown("**Construction (yrs)**")
            onsw_con = int(_num("Onshore wind ", f + "onsw_con", seed.onsw_constr_years, step=1))
            pv_con = int(_num("Solar PV ", f + "pv_con", seed.pv_constr_years, step=1))
            bess_con = int(_num("BESS ", f + "bess_con", seed.bess_constr_years, step=1))

    with st.expander("💰 Revenue & indexation", expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            tenor = int(_num("PPA contract tenor (yrs)", f + "tenor", seed.ppa_tenor, step=1))
            tariff = _num("PPA tariff (€/MWh)", f + "tariff", seed.ppa_tariff, step=1.0)
            pen = _num("Penalty multiple (×)", f + "pen", seed.penalty_multiple, step=0.1, fmt="%.2f")
            lgc = _num("LGC / GO price (€/MWh)", f + "lgc", seed.lgc_price, step=1.0)
        with c2:
            offset = int(_num("Indexation offset (yrs)", f + "offset", seed.indexation_offset_years, step=1))
            cost_infl = _num("Cost inflation (%/yr)", f + "cost_infl", seed.cost_inflation, step=0.005, fmt="%.3f")
            ppa_idx = _num("PPA & LGC indexation (%/yr)", f + "ppa_idx", seed.ppa_indexation, step=0.005, fmt="%.3f")
            solar_infl = _num("Solar-hour price infl. (%/yr)", f + "solar_infl", seed.solar_price_inflation, step=0.005, fmt="%.3f")
            nonsolar_infl = _num("Non-solar price infl. (%/yr)", f + "nonsolar_infl", seed.nonsolar_price_inflation, step=0.005, fmt="%.3f")
        esc_key = f + "esc_merch"
        if esc_key not in st.session_state:
            st.session_state[esc_key] = not multi_year
        escalate_merchant = st.checkbox(
            "Escalate merchant prices over the project life",
            key=esc_key,
            help=(
                "Leave OFF when the energy inputs come from a multi-year simulation that "
                "already escalates market prices each year (avoids double-counting price "
                "growth). Turn ON for a single base-year snapshot. The solar-hour / non-solar "
                "price inflation rates above only apply when this is ON."
            ),
        )
        if multi_year and escalate_merchant:
            st.caption(
                "⚠️ Merchant prices are already escalated by the multi-year energy run — "
                "leaving this on double-counts price growth."
            )

    with st.expander("🏦 Debt, depreciation & tax", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("**Debt**")
            debt_tenor = int(_num("Repayment tenor (yrs)", f + "debt_tenor", seed.debt_tenor, step=1))
            debt_rate = _num("Debt rate (%)", f + "debt_rate", seed.debt_rate, step=0.005, fmt="%.3f")
            wacc = _num("Discount rate / WACC (%)", f + "wacc", seed.discount_rate, step=0.005, fmt="%.3f")
        with c2:
            st.markdown("**DSCR & gearing**")
            dscr_c = _num("DSCR — contracted", f + "dscr_c", seed.dscr_contracted, step=0.05, fmt="%.2f")
            dscr_u = _num("DSCR — uncontracted", f + "dscr_u", seed.dscr_uncontracted, step=0.05, fmt="%.2f")
            gear_c = _num("Max gearing — contracted", f + "gear_c", seed.max_gearing_contracted, step=0.05, fmt="%.2f")
            gear_u = _num("Max gearing — uncontracted", f + "gear_u", seed.max_gearing_uncontracted, step=0.05, fmt="%.2f")
        with c3:
            st.markdown("**Depreciation & tax**")
            book_dep = _num("Book depreciation (%/yr)", f + "book_dep", seed.book_depreciation_rate, step=0.005, fmt="%.3f")
            tax_dep = _num("Tax depreciation (%/yr)", f + "tax_dep", seed.tax_depreciation_rate, step=0.005, fmt="%.3f")
            tax_rate = _num("Corporate tax rate (%)", f + "tax_rate", seed.corp_tax_rate, step=0.01, fmt="%.2f")

    return ProjectFinanceInputs(
        onsw_build_cost=onsw_build, pv_build_cost=pv_build, bess_build_cost=bess_build,
        onsw_connection_cost=onsw_conn, pv_connection_cost=pv_conn, bess_connection_cost=bess_conn,
        onsw_devex=onsw_devex, pv_devex=pv_devex, bess_devex=bess_devex,
        onsw_fixed_om=onsw_om, pv_fixed_om=pv_om, bess_fixed_om=bess_om, ancillary_pct=anc,
        model_duration=duration, development_start=dev_start,
        onsw_dev_years=onsw_dev, pv_dev_years=pv_dev, bess_dev_years=bess_dev,
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
    st.subheader("Key results")
    c = st.columns(4)
    irr = lambda v: f"{v:.1%}" if v == v else "n/a"
    c[0].metric("Project IRR", irr(r.project_irr), help="Unlevered FCFF return")
    c[1].metric("Equity IRR", irr(r.equity_irr), help="Levered FCFE return")
    c[2].metric("Gearing", f"{r.gearing:.1%}")
    c[3].metric("NPV @ WACC", f"€{r.npv_project:,.0f}m")
    c = st.columns(4)
    c[0].metric("Total funding (incl. IDC)", f"€{r.total_capex:,.0f}m")
    c[1].metric("Debt / Equity", f"€{r.total_debt:,.0f}m / €{r.total_equity:,.0f}m")
    c[2].metric("Min / Avg DSCR", f"{r.min_dscr:.2f} / {r.avg_dscr:.2f}")
    pb = f"{r.payback_years:.1f} yrs" if r.payback_years < 1e8 else "n/a"
    c[3].metric("Equity payback / LCOE", f"{pb} · €{r.lcoe:,.0f}/MWh")

    sc = r.schedule
    periods = r.periods
    ops = sc["ops_flag"].astype(bool)

    st.markdown("---")
    cc = st.columns(2)

    # Cumulative equity cash flow
    with cc[0]:
        st.markdown("**Cumulative equity cash flow (FCFE)**")
        cum = np.cumsum(sc["fcfe"])
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=periods, y=cum, mode="lines", name="Cumulative FCFE",
                                 line=dict(color="#2E7D32", width=2), fill="tozeroy",
                                 fillcolor="rgba(46,125,50,0.08)"))
        fig.add_hline(y=0, line_dash="dash", line_color="gray")
        fig.update_layout(height=300, margin=dict(t=10, b=30), xaxis_title="Period",
                          yaxis_title="€m")
        st.plotly_chart(fig, width="stretch")

    # Revenue split
    with cc[1]:
        st.markdown("**Revenue: contracted vs uncontracted**")
        fig = go.Figure()
        fig.add_trace(go.Bar(x=periods[ops], y=sc["net_contracted_rev"][ops],
                             name="Contracted", marker_color="#1565C0"))
        fig.add_trace(go.Bar(x=periods[ops], y=sc["net_uncontracted_rev"][ops],
                             name="Uncontracted (merchant + LGC)", marker_color="#90CAF9"))
        fig.update_layout(barmode="stack", height=300, margin=dict(t=10, b=30),
                          xaxis_title="Period", yaxis_title="€m",
                          legend=dict(orientation="h", y=1.15))
        st.plotly_chart(fig, width="stretch")

    # Debt balance & DSCR
    st.markdown("**Debt service & DSCR**")
    fig = go.Figure()
    fig.add_trace(go.Bar(x=periods[ops], y=sc["interest"][ops], name="Interest", marker_color="#EF6C00"))
    fig.add_trace(go.Bar(x=periods[ops], y=sc["loan_repay"][ops], name="Principal", marker_color="#FFB74D"))
    dscr = sc["dscr"]
    fig.add_trace(go.Scatter(x=periods[ops], y=dscr[ops], name="DSCR", yaxis="y2",
                             mode="lines+markers", line=dict(color="#1B5E20", width=2)))
    fig.update_layout(barmode="stack", height=320, margin=dict(t=10, b=30),
                      xaxis_title="Period", yaxis_title="€m",
                      yaxis2=dict(title="DSCR", overlaying="y", side="right", showgrid=False),
                      legend=dict(orientation="h", y=1.15))
    st.plotly_chart(fig, width="stretch")

    # Annual schedule table
    with st.expander("📋 Full annual schedule", expanded=False):
        df = pd.DataFrame({
            "Period": periods.astype(int),
            "Net contracted rev": sc["net_contracted_rev"],
            "Net uncontracted rev": sc["net_uncontracted_rev"],
            "Opex": -sc["opex"],
            "EBITDA": sc["ebitda"],
            "Interest": -sc["interest"],
            "Loan repay": -sc["loan_repay"],
            "Book dep": -sc["book_dep"],
            "Tax": -sc["tax"],
            "PAT": sc["pat"],
            "FCFF": sc["fcff"],
            "FCFE": sc["fcfe"],
            "DSCR": sc["dscr"],
        })
        df = df[(df["Period"] >= 1)].round(2)
        st.dataframe(df.set_index("Period"), width="stretch", height=400)


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
            "No energy results yet. Run a simulation in the **Optimization** tab first — "
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
        e1, e2, e3 = st.columns(3)
        e1.metric("PPA delivered", f"{energy.ppa_gwh:,.0f} GWh")
        e1.metric("Penalty volume", f"{energy.penalty_gwh:,.1f} GWh")
        e2.metric("Excess sold (solar / non-solar)",
                  f"{energy.excess_solar_gwh:,.0f} / {energy.excess_nonsolar_gwh:,.0f} GWh")
        e2.metric("Total gen (solar / non-solar)",
                  f"{energy.total_solar_gwh:,.0f} / {energy.total_nonsolar_gwh:,.0f} GWh")
        e3.metric("Merchant capture (solar / non-solar)",
                  f"€{energy.sell_solar_price:,.0f} / €{energy.sell_nonsolar_price:,.0f}")
        e3.metric("Capacity (W / PV / BESS)",
                  f"{energy.onsw_mw:,.0f} / {energy.pv_mw:,.0f} MW / {energy.bess_mwh:,.0f} MWh")

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

    st.markdown("---")
    _render_results(result)

    # ── Export ────────────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Export")
    n_years = len(results_list)
    st.caption(
        "Download a streamlined, **live** Excel workbook — one **Hourly** sheet per "
        f"simulated year ({n_years}) with full hourly dispatch, the Energy totals rolled "
        "up from those hours, and the revenue→tax→cash-flow chain and IRRs as formulas."
    )
    if n_years > 12:
        st.caption(
            f"⚠️ {n_years} years × 8 760 hours makes a large workbook — it may take a moment "
            "to build and download."
        )
    try:
        xlsx = export_financial_model(result.inputs, result.energy, result, year_results=results_list)
        fname = f"financial_model_{(result.energy.name or 'scenario').replace(' ', '_')}.xlsx"
        st.download_button(
            "⬇️ Export financial model to Excel",
            data=xlsx,
            file_name=fname,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )
    except Exception as exc:
        st.error(f"Excel export failed: {exc}")
