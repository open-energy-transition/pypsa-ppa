from __future__ import annotations

import streamlit as st

from ppa.data_loader import find_default_csv, load_timeseries, prepare_timeseries
from ppa.counterfactuals import compute_counterfactuals
from ppa.financials import run_financial_analysis
from ppa.network import build_network
from ppa.results import extract_results
from ppa.scenario import BASE_SCENARIO, validate_scenario
from ppa.solver import solve
from ui import state


@st.cache_data
def _cached_load_timeseries(csv_path: str):
    return load_timeseries(csv_path)


def _ensure_timeseries() -> bool:
    if state.has_timeseries():
        return True
    csv_path = find_default_csv()
    if csv_path is None:
        st.error("Could not find `data/march_2025_pypsa_timeseries.csv`. Check the `data/` folder.")
        return False
    ts = _cached_load_timeseries(str(csv_path))
    state.set_timeseries(ts)
    return True


def _render_scenario_summary(s) -> None:
    st.subheader("Scenario summary")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("**Portfolio**")
        st.markdown(f"- Wind: **{s.onsw_mw:.0f} MW**")
        st.markdown(f"- Solar: **{s.pv_mw:.0f} MWac**")
        if s.include_bess:
            st.markdown(f"- BESS: **{s.effective_bess_mw:.0f} MW / {s.effective_bess_mwh:.0f} MWh**")
        else:
            st.markdown("- BESS: *disabled*")

    with col2:
        st.markdown("**PPA contract**")
        st.markdown(f"- Offtake load: **{s.ppaload_mw:.0f} MW** (flat)")
        st.markdown(f"- Tariff: **${s.ppa_price:.0f}/MWh**")
        st.markdown(f"- Required delivery: **{s.required_delivery_share:.0%}** of total load")
        if s.enable_penalty:
            st.markdown(f"- Penalty: **{s.pen_mult:.1f}× tariff** = ${s.penalty_price:.0f}/MWh")
        else:
            st.markdown("- Penalty regime: *disabled*")

    with col3:
        st.markdown("**Market interaction**")
        if s.enable_market_buy:
            st.markdown(f"- Market buy cap: **{s.market_buy_share:.0%}** of delivery")
        else:
            st.markdown("- Market buy: *disabled*")
        if s.enable_market_sell:
            st.markdown(f"- Market sell: enabled (max {s.maxsell_mw:.0f} MW)")
        else:
            st.markdown("- Market sell: *disabled*")
        if s.enable_shortfall:
            st.markdown(f"- Shortfall allowance: **{s.allowed_shortfall_share:.0%}** of total load")
        else:
            st.markdown("- Shortfall allowance: *disabled*")


def render() -> None:
    st.title("⚙️ Optimization")

    if not _ensure_timeseries():
        return

    # Use base scenario if none selected yet
    if not state.has_scenario():
        state.set_scenario(BASE_SCENARIO)

    s = state.get_scenario()

    # Validation
    ts = state.get_timeseries()
    from ppa.data_loader import get_available_days
    errors = validate_scenario(s, available_days=get_available_days(ts))

    _render_scenario_summary(s)
    st.markdown("---")

    if errors:
        for err in errors:
            st.error(err)
        st.warning("Fix the above issues in the **Case Study Definition** tab before running.")
        return

    col1, col2 = st.columns([1, 3])
    with col1:
        run_clicked = st.button("▶ Run Optimization", type="primary", use_container_width=True)
    with col2:
        if state.has_result():
            r = state.get_result()
            st.success(
                f"Last run: solver status **{r.solver_status}** — "
                f"condition **{r.solver_condition}**. "
                "Navigate to Results tabs to explore."
            )

    if run_clicked:
        with st.spinner("Building network and solving with HiGHS… (typically 5–15 seconds)"):
            try:
                ts_prepared = prepare_timeseries(ts, s)
                n = build_network(ts_prepared, s)
                status, condition = solve(n, s, ts_prepared)
                result = extract_results(n, s, ts_prepared, status, condition)
                state.set_result(result)

                if s.run_financial_analysis:
                    fin = run_financial_analysis(
                        s, result.summary, result.revenue, result.n_period_hours
                    )
                    state.set_financial(fin)

                if s.enable_counterfactual:
                    cf = compute_counterfactuals(ts_prepared, s, result)
                    state.set_counterfactual(cf)

            except Exception as exc:
                st.error(f"Optimization failed: {exc}")
                return

        st.success(
            f"Optimization complete — solver: **{status}**, condition: **{condition}**. "
            "Navigate to the Results tabs."
        )
