import streamlit as st

st.set_page_config(
    page_title="PyPSA PPA Explorer",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

from ui.tabs import welcome, introduction, case_study, optimization, results_overview, results_deep_dive, sensitivity_analysis, scenario_analysis, excel_import, multi_year_simulation

st.markdown(
    """
    # PyPSA-based PPA Explorer
    Interactive and full flexible toolkit for modelling renewable portfolios under different Power Purchase Agreement (PPA) assumptions.
    """
)

tabs = st.tabs([
    "🏠 Welcome",
    "📖 Introduction to PPAs",
    "🔬 Case Study Definition",
    "⚙️ Optimization",
    "📊 Results Overview",
    "🔍 Results Deep Dive",
    "Sensitivity Analysis",
    "Scenario Analysis",
    "Excel Import",
    "🌍 Multi-Year Simulation",
], on_change="rerun")

if tabs[0].open:
    with tabs[0]:
        welcome.render()

if tabs[1].open:
    with tabs[1]:
        introduction.render()

if tabs[2].open:
    with tabs[2]:
        case_study.render()

if tabs[3].open:
    with tabs[3]:
        optimization.render()

if tabs[4].open:
    with tabs[4]:
        results_overview.render()

if tabs[5].open:
    with tabs[5]:
        results_deep_dive.render()

if tabs[6].open:
    with tabs[6]:
        sensitivity_analysis.render()

if tabs[7].open:
    with tabs[7]:
        scenario_analysis.render()

if tabs[8].open:
    with tabs[8]:
        excel_import.render()

if tabs[9].open:
    with tabs[9]:
        multi_year_simulation.render()

with st.popover("Disclaimer", width="stretch", icon="⚠️"):
    st.write("""
        The content of this document/web page is intended for the exclusive use of **Open Energy Transition**'s client and other contractually agreed recipients.
        It may only be made available in whole or in part to third parties with the client's consent and on a non-reliance basis.
        **Open Energy Transition** is not liable to third parties for the completeness and accuracy of the information provided therein.
        """)
