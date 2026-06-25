from __future__ import annotations

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
    implied_delivery_share,
    run_tornado,
    run_what_if,
    tornado_to_dataframe,
)
from ui import state


# ── Base inputs ────────────────────────────────────────────────────────────────


def _get_base() -> tuple[EnergyInputs | None, ProjectFinanceInputs | None]:
    """Derive base energy and finance inputs from whatever is in session state."""
    # Prefer the already-run project finance result (keeps user's edited assumptions)
    pf = state.get_project_finance() if state.has_project_finance() else None
    if pf is not None:
        return pf.energy, pf.inputs

    # Fall back to raw optimisation results
    energy: EnergyInputs | None = None
    if state.has_multi_year_results():
        results = [r for r in state.get_multi_year_results() if r is not None]
        if results:
            energy = energy_inputs_from_results(results)
    if energy is None and state.has_result():
        energy = energy_inputs_from_result(state.get_result())

    if energy is None:
        return None, None

    # Seed finance inputs from scenario if available
    scenario = None
    if state.has_result():
        scenario = state.get_result().scenario
    elif state.has_multi_year_results():
        results = [r for r in state.get_multi_year_results() if r is not None]
        if results:
            scenario = results[0].scenario

    finance = project_finance_inputs_from_scenario(scenario) if scenario else ProjectFinanceInputs()
    return energy, finance


# ── Helpers ────────────────────────────────────────────────────────────────────


def _fmt_irr(v: float) -> str:
    return f"{v:.1%}" if v == v else "n/a"


def _delta_str(new_val: float, base_val: float, *, is_pct: bool = False) -> str:
    d = new_val - base_val
    if is_pct:
        return f"{d:+.2f} pp"
    return f"{d:+,.2f}"


# ── What-if panel ──────────────────────────────────────────────────────────────


def _what_if_panel(base_energy: EnergyInputs, base_finance: ProjectFinanceInputs) -> None:
    st.subheader("What-if analysis")
    st.caption(
        "Adjust any parameter — generation volumes scale proportionally with capacity. "
        "Delivery share rebalances PPA delivery vs. merchant excess holding total dispatch constant."
    )

    base_share = implied_delivery_share(base_energy)

    c1, c2, c3 = st.columns(3)
    with c1:
        wind_mw = st.slider(
            "Wind capacity (MW)",
            min_value=0.0,
            max_value=float(max(base_energy.onsw_mw * 3, 300)),
            value=float(base_energy.onsw_mw),
            step=10.0,
            key="sa_wind_mw",
        )
        solar_mw = st.slider(
            "Solar capacity (MW)",
            min_value=0.0,
            max_value=float(max(base_energy.pv_mw * 3, 300)),
            value=float(base_energy.pv_mw),
            step=10.0,
            key="sa_solar_mw",
        )
    with c2:
        bess_mw = st.slider(
            "BESS capacity (MW)",
            min_value=0.0,
            max_value=float(max(base_energy.bess_mw * 3, 150)),
            value=float(base_energy.bess_mw),
            step=5.0,
            key="sa_bess_mw",
        )
        delivery_share_pct = st.slider(
            "Required delivery share (%)",
            min_value=50,
            max_value=100,
            value=int(round(base_share * 100)),
            step=1,
            key="sa_delivery_share",
        )
        delivery_share = delivery_share_pct / 100.0
    with c3:
        ppa_tariff = st.slider(
            "PPA tariff (€/MWh)",
            min_value=0.0,
            max_value=300.0,
            value=float(base_finance.ppa_tariff),
            step=1.0,
            key="sa_ppa_tariff",
        )

    # Run base + what-if
    base_result = run_project_finance(base_finance, base_energy)

    wi_result = run_what_if(
        base_energy, base_finance,
        wind_mw=wind_mw if wind_mw != base_energy.onsw_mw else None,
        solar_mw=solar_mw if solar_mw != base_energy.pv_mw else None,
        bess_mw=bess_mw if bess_mw != base_energy.bess_mw else None,
        delivery_share=delivery_share if abs(delivery_share - base_share) > 1e-6 else None,
        ppa_tariff=ppa_tariff if ppa_tariff != base_finance.ppa_tariff else None,
    )

    st.markdown("#### Results vs. base case")
    cols = st.columns(6)
    metrics = [
        ("Project IRR", "project_irr", True),
        ("Equity IRR", "equity_irr", True),
        ("Gearing", "gearing", True),
        ("NPV (€m)", "npv_project", False),
        ("Total capex (€m)", "total_capex", False),
        ("LCOE (€/MWh)", "lcoe", False),
    ]
    for col, (label, attr, is_pct) in zip(cols, metrics):
        base_v = getattr(base_result, attr)
        wi_v = getattr(wi_result, attr)
        if is_pct:
            col.metric(label, _fmt_irr(wi_v), delta=_delta_str(wi_v * 100, base_v * 100) + " pp")
        else:
            col.metric(label, f"{wi_v:,.1f}", delta=f"{wi_v - base_v:+,.1f}")

    # Energy breakdown for the what-if scenario
    with st.expander("Energy summary (what-if vs. base)", expanded=False):
        wi_e = wi_result.energy
        ba_e = base_energy
        rows = [
            ("Wind (MW)", ba_e.onsw_mw, wi_e.onsw_mw),
            ("Solar (MW)", ba_e.pv_mw, wi_e.pv_mw),
            ("BESS (MW)", ba_e.bess_mw, wi_e.bess_mw),
            ("PPA delivered (GWh/yr)", ba_e.ppa_gwh, wi_e.ppa_gwh),
            ("Excess solar (GWh/yr)", ba_e.excess_solar_gwh, wi_e.excess_solar_gwh),
            ("Excess non-solar (GWh/yr)", ba_e.excess_nonsolar_gwh, wi_e.excess_nonsolar_gwh),
            ("Penalty (GWh/yr)", ba_e.penalty_gwh, wi_e.penalty_gwh),
        ]
        import pandas as pd
        df = pd.DataFrame(rows, columns=["Parameter", "Base", "What-if"])
        df["Change"] = (df["What-if"] - df["Base"]).map(lambda x: f"{x:+.1f}")
        df["Base"] = df["Base"].map(lambda x: f"{x:,.1f}")
        df["What-if"] = df["What-if"].map(lambda x: f"{x:,.1f}")
        st.dataframe(df.set_index("Parameter"), use_container_width=True)


# ── Tornado chart ──────────────────────────────────────────────────────────────


def _tornado_panel(base_energy: EnergyInputs, base_finance: ProjectFinanceInputs) -> None:
    st.subheader("Tornado chart — one-at-a-time sensitivity")
    st.caption("Each bar shows the Project IRR range when one parameter moves ±25% (capacities/tariff) "
               "or ±10 pp (delivery share), all other parameters held at base.")

    base_share = implied_delivery_share(base_energy)

    with st.expander("Adjust ranges", expanded=False):
        rc1, rc2, rc3 = st.columns(3)
        with rc1:
            wind_pct = st.number_input("Wind range (±%)", value=25, min_value=5, max_value=100, step=5, key="sa_t_wind_pct")
            solar_pct = st.number_input("Solar range (±%)", value=25, min_value=5, max_value=100, step=5, key="sa_t_solar_pct")
        with rc2:
            bess_pct = st.number_input("BESS range (±%)", value=25, min_value=5, max_value=100, step=5, key="sa_t_bess_pct")
            tariff_pct = st.number_input("PPA tariff range (±%)", value=20, min_value=5, max_value=100, step=5, key="sa_t_tariff_pct")
        with rc3:
            share_pp = st.number_input("Delivery share range (±pp)", value=10, min_value=1, max_value=30, step=1, key="sa_t_share_pp")
            metric_choice = st.selectbox(
                "Metric",
                options=["project_irr", "equity_irr", "npv_project", "gearing", "lcoe"],
                format_func=lambda x: {
                    "project_irr": "Project IRR",
                    "equity_irr": "Equity IRR",
                    "npv_project": "NPV (€m)",
                    "gearing": "Gearing",
                    "lcoe": "LCOE (€/MWh)",
                }[x],
                key="sa_t_metric",
            )

    def pct_range(base_val: float, pct: float) -> tuple[float, float]:
        delta = base_val * pct / 100.0
        return (max(base_val - delta, 0.0), base_val + delta)

    with st.spinner("Computing tornado…"):
        rows, base_val = run_tornado(
            base_energy, base_finance,
            wind_range=pct_range(base_energy.onsw_mw, wind_pct),
            solar_range=pct_range(base_energy.pv_mw, solar_pct),
            bess_range=pct_range(base_energy.bess_mw, bess_pct),
            delivery_range=(
                max(base_share - share_pp / 100.0, 0.01),
                min(base_share + share_pp / 100.0, 1.0),
            ),
            tariff_range=pct_range(base_finance.ppa_tariff, tariff_pct),
            metric=metric_choice,
        )

    is_pct_metric = metric_choice in ("project_irr", "equity_irr", "gearing")
    scale = 100.0 if is_pct_metric else 1.0
    unit = " pp" if is_pct_metric else ""
    base_scaled = base_val * scale

    fig = go.Figure()
    for row in reversed(rows):  # reversed so largest swing is at top
        lo = row.low_metric * scale
        hi = row.high_metric * scale
        # Bar from min to max of (lo, hi, base)
        bar_left = min(lo, hi)
        bar_right = max(lo, hi)
        # Colour: blue if high > low (higher param → higher metric), orange otherwise
        positive = row.high_metric >= row.low_metric
        col_hi = "#1565C0" if positive else "#EF6C00"
        col_lo = "#EF6C00" if positive else "#1565C0"

        fig.add_trace(go.Bar(
            y=[row.param],
            x=[bar_right - base_scaled],
            base=base_scaled,
            orientation="h",
            marker_color=col_hi,
            showlegend=False,
            hovertemplate=(
                f"<b>{row.param}</b><br>"
                f"High ({row.high_val:.3g}): {hi:.2f}{unit}<br>"
                f"Base: {base_scaled:.2f}{unit}<extra></extra>"
            ),
        ))
        fig.add_trace(go.Bar(
            y=[row.param],
            x=[bar_left - base_scaled],
            base=base_scaled,
            orientation="h",
            marker_color=col_lo,
            showlegend=False,
            hovertemplate=(
                f"<b>{row.param}</b><br>"
                f"Low ({row.low_val:.3g}): {lo:.2f}{unit}<br>"
                f"Base: {base_scaled:.2f}{unit}<extra></extra>"
            ),
        ))

    fig.add_vline(
        x=base_scaled,
        line_dash="dash",
        line_color="black",
        annotation_text=f"Base: {base_scaled:.2f}{unit}",
        annotation_position="top right",
    )
    metric_label = {
        "project_irr": "Project IRR (%)",
        "equity_irr": "Equity IRR (%)",
        "npv_project": "NPV (€m)",
        "gearing": "Gearing (%)",
        "lcoe": "LCOE (€/MWh)",
    }[metric_choice]
    fig.update_layout(
        barmode="overlay",
        height=max(300, len(rows) * 70),
        margin=dict(t=30, b=40, l=180),
        xaxis_title=metric_label,
        yaxis=dict(automargin=True),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Summary table
    with st.expander("Data table", expanded=False):
        df = tornado_to_dataframe(rows, base_val, metric_choice)
        st.dataframe(df.set_index("Parameter"), use_container_width=True)


# ── Tab entry point ────────────────────────────────────────────────────────────


def render() -> None:
    st.header("Sensitivity Analysis")

    base_energy, base_finance = _get_base()
    if base_energy is None:
        st.info(
            "Run an optimisation first (Optimisation tab), then come back here. "
            "For richer results, run the Financial Model tab first — its edited assumptions "
            "will be used as the base case."
        )
        return

    _what_if_panel(base_energy, base_finance)

    st.markdown("---")

    _tornado_panel(base_energy, base_finance)
