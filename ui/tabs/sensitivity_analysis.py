from __future__ import annotations

import dataclasses

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ppa.financial_model import (
    EnergyInputs,
    ProjectFinanceInputs,
    energy_inputs_from_result,
    energy_inputs_from_results,
    project_finance_inputs_from_scenario,
    run_project_finance,
)
from ppa.sensitivity import (
    PARAMS,
    PARAM_BY_FIELD,
    run_tornado,
    run_what_if,
    tornado_to_dataframe,
)
from ui import state


# ── Base inputs ────────────────────────────────────────────────────────────────


def _get_base() -> tuple[EnergyInputs | None, ProjectFinanceInputs | None]:
    """Derive base energy and finance inputs from session state.

    Prefers an already-run Financial Model result so the user's edited
    assumptions carry over; falls back to raw optimisation results.
    """
    pf = state.get_project_finance() if state.has_project_finance() else None
    if pf is not None:
        return pf.energy, pf.inputs

    energy: EnergyInputs | None = None
    if state.has_multi_year_results():
        results = [r for r in state.get_multi_year_results() if r is not None]
        if results:
            energy = energy_inputs_from_results(results)
    if energy is None and state.has_result():
        energy = energy_inputs_from_result(state.get_result())

    if energy is None:
        return None, None

    scenario = None
    if state.has_result():
        scenario = state.get_result().scenario
    elif state.has_multi_year_results():
        results = [r for r in state.get_multi_year_results() if r is not None]
        if results:
            scenario = results[0].scenario

    finance = project_finance_inputs_from_scenario(scenario) if scenario else ProjectFinanceInputs()
    return energy, finance


# ── Metric helpers ─────────────────────────────────────────────────────────────

METRIC_OPTIONS = {
    "project_irr": "Project IRR",
    "equity_irr": "Equity IRR",
    "npv_project": "NPV (€m)",
    "gearing": "Gearing",
    "lcoe": "LCOE (€/MWh)",
    "total_capex": "Total capex (€m)",
    "total_debt": "Total debt (€m)",
    "min_dscr": "Min DSCR",
}
PCT_METRICS = {"project_irr", "equity_irr", "gearing"}


def _fmt(v: float, metric: str) -> str:
    if metric in PCT_METRICS:
        return f"{v:.1%}" if v == v else "n/a"
    return f"{v:,.2f}" if v == v else "n/a"


def _scale(metric: str) -> float:
    return 100.0 if metric in PCT_METRICS else 1.0


def _unit(metric: str) -> str:
    return "%" if metric in PCT_METRICS else ""


# ── What-if panel ──────────────────────────────────────────────────────────────


def _num(label: str, key: str, default: float, *, step: float | None = None, fmt: str | None = None):
    if key not in st.session_state:
        st.session_state[key] = float(default)
    kw: dict = {}
    if step is not None:
        kw["step"] = step
    if fmt is not None:
        kw["format"] = fmt
    return st.number_input(label, key=key, **kw)


def _what_if_panel(base_energy: EnergyInputs, base_finance: ProjectFinanceInputs) -> None:
    st.subheader("What-if analysis")
    st.caption(
        "Adjust any combination of financial parameters and see the result instantly. "
        "Parameters that require a PyPSA re-run (capacities, delivery share, BESS efficiency) "
        "are in the Optimisation tab."
    )

    pf = "wi_"
    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.markdown("**CAPEX (€m/MW or €m/MWh)**")
        onsw_build = _num("Wind build", pf + "onsw_build", base_finance.onsw_build_cost, step=0.05, fmt="%.3f")
        pv_build   = _num("Solar build", pf + "pv_build",  base_finance.pv_build_cost,   step=0.05, fmt="%.3f")
        bess_build = _num("BESS build",  pf + "bess_build", base_finance.bess_build_cost, step=0.05, fmt="%.3f")
        st.markdown("**OPEX (€m/MW or €m/MWh p.a.)**")
        onsw_om  = _num("Wind O&M",  pf + "onsw_om",  base_finance.onsw_fixed_om,  step=0.005, fmt="%.4f")
        pv_om    = _num("Solar O&M", pf + "pv_om",    base_finance.pv_fixed_om,    step=0.005, fmt="%.4f")
        bess_om  = _num("BESS O&M",  pf + "bess_om",  base_finance.bess_fixed_om,  step=0.005, fmt="%.4f")
        anc      = _num("Ancillary (% rev)", pf + "anc", base_finance.ancillary_pct, step=0.005, fmt="%.3f")

    with c2:
        st.markdown("**Revenue**")
        tariff  = _num("PPA tariff (€/MWh)",    pf + "tariff",  base_finance.ppa_tariff,      step=1.0)
        pen     = _num("Penalty multiple (×)",   pf + "pen",     base_finance.penalty_multiple, step=0.1, fmt="%.2f")
        lgc     = _num("LGC / GO (€/MWh)",       pf + "lgc",     base_finance.lgc_price,        step=0.5)
        st.markdown("**Indexation (%/yr)**")
        ppa_idx      = _num("PPA indexation",     pf + "ppa_idx",      base_finance.ppa_indexation,          step=0.005, fmt="%.3f")
        cost_infl    = _num("Cost inflation",     pf + "cost_infl",    base_finance.cost_inflation,           step=0.005, fmt="%.3f")
        solar_infl   = _num("Solar price",        pf + "solar_infl",   base_finance.solar_price_inflation,    step=0.005, fmt="%.3f")
        nonsolar_infl= _num("Non-solar price",    pf + "nonsolar_infl",base_finance.nonsolar_price_inflation, step=0.005, fmt="%.3f")

    with c3:
        st.markdown("**Debt**")
        debt_rate   = _num("Debt rate",          pf + "debt_rate",   base_finance.debt_rate,   step=0.005, fmt="%.3f")
        debt_tenor  = int(_num("Tenor (yrs)",    pf + "debt_tenor",  base_finance.debt_tenor,  step=1))
        dscr_c      = _num("DSCR contracted",    pf + "dscr_c",      base_finance.dscr_contracted,   step=0.05, fmt="%.2f")
        dscr_u      = _num("DSCR uncontracted",  pf + "dscr_u",      base_finance.dscr_uncontracted, step=0.05, fmt="%.2f")
        gear_c      = _num("Max gearing contr.", pf + "gear_c",      base_finance.max_gearing_contracted,   step=0.05, fmt="%.2f")
        gear_u      = _num("Max gearing uncontr.", pf + "gear_u",    base_finance.max_gearing_uncontracted, step=0.05, fmt="%.2f")

    with c4:
        st.markdown("**Tax & depreciation**")
        tax_rate  = _num("Corp. tax rate",       pf + "tax_rate",  base_finance.corp_tax_rate,         step=0.01, fmt="%.3f")
        book_dep  = _num("Book dep. rate",        pf + "book_dep",  base_finance.book_depreciation_rate, step=0.005, fmt="%.3f")
        tax_dep   = _num("Tax dep. rate",         pf + "tax_dep",   base_finance.tax_depreciation_rate,  step=0.005, fmt="%.3f")
        wacc      = _num("WACC / discount rate",  pf + "wacc",      base_finance.discount_rate,          step=0.005, fmt="%.3f")
        st.markdown("**Devex**")
        onsw_devex = _num("Wind devex",  pf + "onsw_devex", base_finance.onsw_devex, step=0.01, fmt="%.3f")
        pv_devex   = _num("Solar devex", pf + "pv_devex",   base_finance.pv_devex,   step=0.01, fmt="%.3f")
        bess_devex = _num("BESS devex",  pf + "bess_devex", base_finance.bess_devex, step=0.01, fmt="%.3f")

    wi_finance = dataclasses.replace(
        base_finance,
        onsw_build_cost=onsw_build, pv_build_cost=pv_build, bess_build_cost=bess_build,
        onsw_fixed_om=onsw_om, pv_fixed_om=pv_om, bess_fixed_om=bess_om, ancillary_pct=anc,
        ppa_tariff=tariff, penalty_multiple=pen, lgc_price=lgc,
        ppa_indexation=ppa_idx, cost_inflation=cost_infl,
        solar_price_inflation=solar_infl, nonsolar_price_inflation=nonsolar_infl,
        debt_rate=debt_rate, debt_tenor=debt_tenor,
        dscr_contracted=dscr_c, dscr_uncontracted=dscr_u,
        max_gearing_contracted=gear_c, max_gearing_uncontracted=gear_u,
        corp_tax_rate=tax_rate, book_depreciation_rate=book_dep, tax_depreciation_rate=tax_dep,
        discount_rate=wacc,
        onsw_devex=onsw_devex, pv_devex=pv_devex, bess_devex=bess_devex,
    )

    base_result = run_project_finance(base_finance, base_energy)
    wi_result   = run_project_finance(wi_finance,   base_energy)

    st.markdown("#### Results vs. base case")
    cols = st.columns(6)
    kpis = [
        ("Project IRR", "project_irr", True),
        ("Equity IRR",  "equity_irr",  True),
        ("Gearing",     "gearing",     True),
        ("NPV (€m)",    "npv_project", False),
        ("Total capex (€m)", "total_capex", False),
        ("Min DSCR",    "min_dscr",    False),
    ]
    for col, (label, attr, is_pct) in zip(cols, kpis):
        bv = getattr(base_result, attr)
        wv = getattr(wi_result,   attr)
        if is_pct:
            col.metric(label, f"{wv:.1%}", delta=f"{(wv - bv) * 100:+.2f} pp")
        else:
            col.metric(label, f"{wv:,.2f}", delta=f"{wv - bv:+,.2f}")


# ── Tornado chart ──────────────────────────────────────────────────────────────


def _tornado_panel(base_energy: EnergyInputs, base_finance: ProjectFinanceInputs) -> None:
    st.subheader("Tornado chart — one-at-a-time sensitivity")

    tc1, tc2 = st.columns([3, 1])
    with tc2:
        metric_key = st.selectbox(
            "Metric",
            options=list(METRIC_OPTIONS),
            format_func=lambda x: METRIC_OPTIONS[x],
            key="sa_t_metric",
        )
        default_pct = st.number_input(
            "Default range (±%)",
            min_value=5, max_value=100, value=25, step=5,
            key="sa_t_pct",
            help="Applied to all parameters that don't have a custom range.",
        )
        top_n = st.number_input(
            "Show top N parameters",
            min_value=5, max_value=len(PARAMS), value=15, step=1,
            key="sa_t_topn",
        )

    # Build parameter list with overridden default pct
    params_run = [dataclasses.replace(p, pct=default_pct) for p in PARAMS]

    with st.spinner("Computing sensitivity…"):
        rows, base_val = run_tornado(base_energy, base_finance, params=params_run, metric=metric_key)

    rows = rows[: int(top_n)]
    scale = _scale(metric_key)
    unit = _unit(metric_key)
    base_scaled = base_val * scale

    # ── Tornado figure ──
    fig = go.Figure()

    for row in reversed(rows):
        lo = row.low_metric * scale
        hi = row.high_metric * scale

        # Which end is "down" vs "up"?
        col_down = "#EF6C00"   # orange  — parameter decrease → lower metric
        col_up   = "#1565C0"   # blue    — parameter increase → higher metric
        # If increasing the parameter increases the metric: hi > lo
        if hi >= lo:
            col_lo_bar, col_hi_bar = col_down, col_up
        else:
            col_lo_bar, col_hi_bar = col_up, col_down

        # Lower half bar (from base to left)
        fig.add_trace(go.Bar(
            name="Low",
            y=[row.param],
            x=[min(lo, hi) - base_scaled],
            base=base_scaled,
            orientation="h",
            marker_color=col_lo_bar,
            showlegend=False,
            hovertemplate=(
                f"<b>{row.param}</b><br>"
                f"Low ({row.low_val:.4g}): {lo:.3f}{unit}<br>"
                f"Base: {base_scaled:.3f}{unit}<extra></extra>"
            ),
        ))
        # Upper half bar (from base to right)
        fig.add_trace(go.Bar(
            name="High",
            y=[row.param],
            x=[max(lo, hi) - base_scaled],
            base=base_scaled,
            orientation="h",
            marker_color=col_hi_bar,
            showlegend=False,
            hovertemplate=(
                f"<b>{row.param}</b><br>"
                f"High ({row.high_val:.4g}): {hi:.3f}{unit}<br>"
                f"Base: {base_scaled:.3f}{unit}<extra></extra>"
            ),
        ))

    fig.add_vline(
        x=base_scaled,
        line_dash="dash",
        line_color="black",
        annotation_text=f"Base {base_scaled:.2f}{unit}",
        annotation_position="top right",
    )

    metric_label = METRIC_OPTIONS[metric_key]
    if metric_key in PCT_METRICS:
        metric_label += " (%)"

    fig.update_layout(
        barmode="overlay",
        height=max(350, len(rows) * 52 + 80),
        margin=dict(t=40, b=50, l=10, r=40),
        xaxis_title=metric_label,
        yaxis=dict(automargin=True),
        plot_bgcolor="white",
        paper_bgcolor="white",
    )
    with tc1:
        st.plotly_chart(fig, use_container_width=True)

    with st.expander("Data table", expanded=False):
        df = tornado_to_dataframe(rows, base_val, metric_key)
        st.dataframe(df.set_index("Parameter"), use_container_width=True)


# ── Tab entry point ────────────────────────────────────────────────────────────


def render() -> None:
    st.header("Sensitivity Analysis")
    st.caption(
        "Financial-parameter sensitivity — no PyPSA re-run required. "
        "For capacity or dispatch changes (wind/solar/BESS MW, delivery share, "
        "BESS round-trip efficiency) run a new optimisation in the Optimisation tab."
    )

    base_energy, base_finance = _get_base()
    if base_energy is None:
        st.info(
            "Run an optimisation first (Optimisation tab), then return here. "
            "For richer results, run the Financial Model tab first — "
            "its edited assumptions will be used as the base case."
        )
        return

    _what_if_panel(base_energy, base_finance)
    st.markdown("---")
    _tornado_panel(base_energy, base_finance)
