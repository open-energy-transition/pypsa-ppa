import streamlit as st

st.set_page_config(
    page_title="PyPSA PPA Explorer",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

from ui.tabs import (
    welcome,
    introduction,
    case_study,
    data_download,
    optimization,
    results_overview,
    results_deep_dive,
    sensitivity_analysis,
    scenario_analysis,
    financial_model,
    excel_import,
)

st.markdown(
    """
    # PyPSA-based PPA Explorer
    """
)
with st.popover("Disclaimer", width="stretch", icon="⚠️"):
    st.write(
        """
        The content of this document/web page is intended for the exclusive use of **Open Energy Transition (OET)**'s client and other contractually agreed recipients.
        It may only be made available in whole or in part to third parties with the client's consent and on a non-reliance basis.
        **Open Energy Transition** is not liable to third parties for the completeness and accuracy of the information provided therein.
        """
    )

tabs = st.tabs([
    "| 👋 Welcome",
    "| 1. 🔬 Case Setup",
    "| 2.📡 Get Data",
    "| 3. ⚙️ Optimization",
    "| 4. 🔍 Results",
    "| 5. 🏦 Financial Model",
    "| 6. 📊 Sensitivity Analysis",
    "| 7. 📖 HELP",
    # "📊 Results Overview",
    # "Scenario Analysis",
    # "Excel Import",
], on_change="rerun")

i = 0
if tabs[i].open:
    with tabs[i]:
        welcome.render()

i += 1
if tabs[i].open:
    with tabs[i]:
        case_study.render()

i += 1
if tabs[i].open:
    with tabs[i]:
        data_download.render()

i += 1
if tabs[i].open:
    with tabs[i]:
        optimization.render()

i += 1
if tabs[i].open:
    with tabs[i]:
        results_deep_dive.render()

i += 1
if tabs[i].open:
    with tabs[i]:
        financial_model.render()

i += 1
if tabs[i].open:
    with tabs[i]:
        sensitivity_analysis.render()

i += 1
if tabs[i].open:
    with tabs[i]:
        introduction.render()

#i += 1
#if tabs[i].open:
#    with tabs[i]:
#        scenario_analysis.render()

#i += 1
#if tabs[i].open:
#    with tabs[i]:
#        excel_import.render()

#i += 1
#if tabs[i].open:
#    with tabs[i]:
#        results_overview.render()
