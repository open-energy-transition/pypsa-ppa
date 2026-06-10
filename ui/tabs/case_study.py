"""Case Study definition — select a preset and customise all scenario parameters."""
from __future__ import annotations

import streamlit as st

from ppa.scenario import CASE_STUDIES, BASE_SCENARIO, load_case_study
from ui import state
from ui.scenario_form import render_scenario_form


def _render_case_study_card(cs, is_active: bool) -> bool:
    border_color = "#1565C0" if is_active else "#E0E0E0"
    bg_color = "#E3F2FD" if is_active else "#FAFAFA"
    badge = " ✓ Active" if is_active else ""
    st.markdown(
        f"""
<div style="border: 2px solid {border_color}; border-radius: 10px; padding: 16px;
            background: {bg_color}; height: 100%;">
  <div style="font-size: 2rem; margin-bottom: 6px;">{cs.icon}</div>
  <div style="font-weight: 700; font-size: 1.05rem; color: #1A237E;">{cs.name}{badge}</div>
  <div style="font-size: 0.85rem; color: #546E7A; margin-bottom: 8px;">{cs.subtitle}</div>
  <div style="font-size: 0.88rem; color: #424242; line-height: 1.5;">{cs.storyline}</div>
</div>
""",
        unsafe_allow_html=True,
    )
    st.markdown("")
    return st.button(
        "Reload" if is_active else "Load this scenario",
        key=f"load_cs_{cs.id}",
        width="stretch",
        type="primary" if is_active else "secondary",
    )


def render() -> None:
    st.title("🔬 Case Study Definition")
    st.markdown(
        "Choose a predefined scenario to explore, then customise any parameters below — "
        "including **project location**, **simulation horizon**, and **technology degradation**. "
        "Head to **Download Data** to fetch European data, then **Optimization** to run."
    )
    st.markdown("---")

    # ── Case study cards ──────────────────────────────────────────────────────
    st.subheader("Predefined case studies")
    active_id = state.get_active_case_study_id()
    cols = st.columns(len(CASE_STUDIES))
    for col, cs in zip(cols, CASE_STUDIES):
        with col:
            if _render_case_study_card(cs, is_active=(cs.id == active_id)):
                state.set_scenario(load_case_study(cs))
                state.set_active_case_study_id(cs.id)
                state.clear_result()
                st.session_state.pop(state.MULTI_YEAR_RESULTS_KEY, None)
                st.session_state.pop(state.MULTI_YEAR_FINANCIAL_KEY, None)
                st.rerun()

    # ── Customise parameters ──────────────────────────────────────────────────
    with st.expander("Customise parameters", expanded=False):
        st.markdown(
            "Controls are pre-filled from the active case study. "
            "Adjust any value, then click **Apply changes**."
        )
        if not state.has_scenario():
            state.set_scenario(BASE_SCENARIO)

        current = state.get_scenario()
        updated = render_scenario_form(current)

        c1, c2 = st.columns(2)
        with c1:
            if st.button("Apply changes", type="primary", width="stretch"):
                state.set_scenario(updated)
                state.clear_result()
                st.session_state.pop(state.MULTI_YEAR_RESULTS_KEY, None)
                st.session_state.pop(state.MULTI_YEAR_FINANCIAL_KEY, None)
                st.success("Scenario updated. Head to Optimization to run.")
        with c2:
            if st.button("Reset to base defaults", type="secondary", width="stretch"):
                state.set_scenario(BASE_SCENARIO)
                state.set_active_case_study_id("")
                state.clear_result()
                st.session_state.pop(state.MULTI_YEAR_RESULTS_KEY, None)
                st.session_state.pop(state.MULTI_YEAR_FINANCIAL_KEY, None)
                st.rerun()
