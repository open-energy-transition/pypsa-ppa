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


def _num(label: str, key: str, default: float, *, step: float | None = None, fmt: str | None = None, pct: bool = False):
    """With ``pct=True`` the model value is a decimal fraction (e.g. 0.065) but is
    displayed and edited in percent (6.5); ``step``/``fmt`` are in percent terms."""
    scale = 100.0 if pct else 1.0
    if key not in st.session_state:
        st.session_state[key] = float(default) * scale
    kw: dict = {}
    if step is not None:
        kw["step"] = step
    if fmt is not None:
        kw["format"] = fmt
    val = st.number_input(label, key=key, **kw)
    return val / scale if pct else val


def _what_if_panel(base_energy: EnergyInputs, base_finance: ProjectFinanceInputs) -> None:
    with st.expander("What-if analysis", expanded=False):
        st.caption(
            "Adjust any combination of financial parameters and see the result instantly. "
            "Parameters that require a PyPSA re-run (capacities, delivery share, BESS efficiency) "
            "are in the Optimisation tab."
        )

        pf = "wi_"
        cols = st.columns(4)

        with cols[0]:
            st.markdown("**CAPEX (€m/MW or €m/MWh)**")
            onsw_build = _num("Wind build", pf + "onsw_build", base_finance.onsw_build_cost, step=0.05, fmt="%.3f")
            pv_build   = _num("Solar build", pf + "pv_build",  base_finance.pv_build_cost,   step=0.05, fmt="%.3f")
            bess_build = _num("BESS build",  pf + "bess_build", base_finance.bess_build_cost, step=0.05, fmt="%.3f")
            st.markdown("**OPEX (€m/MW or €m/MWh p.a.)**")
            onsw_om  = _num("Wind O&M",  pf + "onsw_om",  base_finance.onsw_fixed_om,  step=0.005, fmt="%.4f")
            pv_om    = _num("Solar O&M", pf + "pv_om",    base_finance.pv_fixed_om,    step=0.005, fmt="%.4f")
            bess_om  = _num("BESS O&M",  pf + "bess_om",  base_finance.bess_fixed_om,  step=0.005, fmt="%.4f")
            anc      = _num("Ancillary (% rev)", pf + "anc", base_finance.ancillary_pct, step=0.1, fmt="%.2f", pct=True)

        with cols[1]:
            st.markdown("**Revenue**")
            tariff  = _num("PPA tariff (€/MWh)",    pf + "tariff",  base_finance.ppa_tariff,      step=1.0)
            pen     = _num("Penalty multiple (×)",   pf + "pen",     base_finance.penalty_multiple, step=0.1, fmt="%.2f")
            lgc     = _num("LGC / GO (€/MWh)",       pf + "lgc",     base_finance.lgc_price,        step=0.5)
            st.markdown("**Indexation (%/yr)**")
            ppa_idx      = _num("PPA indexation",     pf + "ppa_idx",      base_finance.ppa_indexation,          step=0.1, fmt="%.2f", pct=True)
            cost_infl    = _num("Cost inflation",     pf + "cost_infl",    base_finance.cost_inflation,           step=0.1, fmt="%.2f", pct=True)
            solar_infl   = _num("Solar price",        pf + "solar_infl",   base_finance.solar_price_inflation,    step=0.1, fmt="%.2f", pct=True)
            nonsolar_infl= _num("Non-solar price",    pf + "nonsolar_infl",base_finance.nonsolar_price_inflation, step=0.1, fmt="%.2f", pct=True)

        with cols[2]:
            st.markdown("**Debt**")
            debt_rate   = _num("Debt rate (%)",      pf + "debt_rate",   base_finance.debt_rate,   step=0.1, fmt="%.2f", pct=True)
            debt_tenor  = int(_num("Tenor (yrs)",    pf + "debt_tenor",  base_finance.debt_tenor,  step=1))
            dscr_c      = _num("DSCR contracted",    pf + "dscr_c",      base_finance.dscr_contracted,   step=0.05, fmt="%.2f")
            dscr_u      = _num("DSCR uncontracted",  pf + "dscr_u",      base_finance.dscr_uncontracted, step=0.05, fmt="%.2f")
            gear_c      = _num("Max gearing contr. (%)", pf + "gear_c",  base_finance.max_gearing_contracted,   step=1.0, fmt="%.1f", pct=True)
            gear_u      = _num("Max gearing uncontr. (%)", pf + "gear_u", base_finance.max_gearing_uncontracted, step=1.0, fmt="%.1f", pct=True)

        with cols[3]:
            st.markdown("**Tax & depreciation**")
            tax_rate  = _num("Corp. tax rate (%)",    pf + "tax_rate",  base_finance.corp_tax_rate,         step=1.0, fmt="%.1f", pct=True)
            book_dep  = _num("Book dep. rate (%)",     pf + "book_dep",  base_finance.book_depreciation_rate, step=0.1, fmt="%.2f", pct=True)
            tax_dep   = _num("Tax dep. rate (%)",      pf + "tax_dep",   base_finance.tax_depreciation_rate,  step=0.1, fmt="%.2f", pct=True)
            wacc      = _num("WACC / discount rate (%)", pf + "wacc",    base_finance.discount_rate,          step=0.1, fmt="%.2f", pct=True)
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

    with st.expander("Base results", expanded=True):
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
                col.metric(label, f"{wv:.2%}") # , delta=f"{(wv - bv) * 100:+.2f} pp")
            else:
                col.metric(label, f"{wv:,.2f}") # , delta=f"{wv - bv:+,.2f}")


# ── Tornado chart ──────────────────────────────────────────────────────────────


def _tornado_panel(base_energy: EnergyInputs, base_finance: ProjectFinanceInputs) -> None:
    tab_chart1, tab_chart2 = st.tabs([
        "| Tornado chart — one-at-a-time sensitivity", 
        "| Data table",
    ])
    with tab_chart1:
    # with st.expander("Tornado chart — one-at-a-time sensitivity", expanded=True):
        cols = st.columns([3, 1])
        with cols[1]:
            metric_key = st.selectbox(
                "Metric",
                options=list(METRIC_OPTIONS),
                format_func=lambda x: METRIC_OPTIONS[x],
                key="sa_t_metric",
            )
            top_n = st.number_input(
                "Show top N parameters",
                min_value=3, max_value=len(PARAMS), value=12, step=1,
                key="sa_t_topn",
            )

        with st.spinner("Computing sensitivity…"):
            rows, base_val, zero_rows = run_tornado(
                base_energy, base_finance, metric=metric_key, min_swing_fraction=0.01
            )

        if zero_rows:
            names = ", ".join(r.param for r in zero_rows)
            st.caption(
                f"**{len(zero_rows)} parameter(s) hidden** (as of negligible effect on "
                f"{METRIC_OPTIONS[metric_key]} in this scenario): {names}."
            )

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
                    f"Low ({row.low_val:.4g}): {lo:.2f}{unit}<br>"
                    f"Base ({row.base_val:.4g}): {base_scaled:.2f}{unit}<br>"
                    f"Delta: {(base_scaled-lo):.2f}{unit}<extra></extra>"
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
                    f"High ({row.high_val:.4g}): {hi:.2f}{unit}<br>"
                    f"Base ({row.base_val:.4g}): {base_scaled:.2f}{unit}<br>"
                    f"Delta: {(base_scaled-hi):.2f}{unit}<extra></extra>"
                ),
            ))

        # Label above the plot area (yref="paper", y>1) so it never overlaps
        # the top bar.
        fig.add_vline(
            x=base_scaled,
            line_dash="dash",
            line_color="black",
            annotation=dict(
                text=f"Base {base_scaled:.2f}{unit}",
                yref="paper",
                y=1.0,
                yanchor="bottom",
                xanchor="center",
                showarrow=False,
            ),
        )

        metric_label = METRIC_OPTIONS[metric_key]
        if metric_key in PCT_METRICS:
            metric_label += " (%)"

        fig.update_layout(
            barmode="overlay",
            height=max(350, len(rows) * 32 + 80),
            margin=dict(t=50, b=50, l=10, r=40),
            xaxis_title=metric_label,
            yaxis=dict(automargin=True),
            plot_bgcolor="white",
            paper_bgcolor="white",
        )
        with cols[0]:
            st.plotly_chart(fig, width='stretch')

    with tab_chart2:
    # with st.expander("Data table", expanded=False):
        df = tornado_to_dataframe(rows, base_val, metric_key)
        st.dataframe(df.set_index("Parameter"), width='stretch', height="content")


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
    # st.markdown("---")
    _tornado_panel(base_energy, base_finance)
