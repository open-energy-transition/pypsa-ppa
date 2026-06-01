import streamlit as st

st.set_page_config(
    page_title="PyPSA PPA Explorer",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

from ui.tabs import welcome, introduction, case_study, optimization, results_overview, results_deep_dive, sensitivity_analysis

st.title("⚡ PyPSA PPA Explorer")
st.write(
    "Interactive but full flexible toolkit for modelling renewable portfolios under different Power Purchase Agreement (PPA) assumptions."
)

with st.popover("Disclaimer", width="stretch", icon="⚠️"):
    st.write("""
        The content of this document/web page is intended for the exclusive use of **Open Energy Transition**'s client and other contractually agreed recipients.
        It may only be made available in whole or in part to third parties with the client's consent and on a non-reliance basis.
        **Open Energy Transition** is not liable to third parties for the completeness and accuracy of the information provided therein.
        """)

tabs = st.tabs([
    "🏠 Welcome",
    "📖 Introduction to PPAs",
    "🔬 Case Study Definition",
    "⚙️ Optimization",
    "📊 Results Overview",
    "🔍 Results Deep Dive",
    "Sensitivity Analysis",
])

with tabs[0]:
    welcome.render()

with tabs[1]:
    introduction.render()

with tabs[2]:
    case_study.render()

with tabs[3]:
    optimization.render()

with tabs[4]:
    results_overview.render()

with tabs[5]:
    results_deep_dive.render()

with tabs[6]:
    sensitivity_analysis.render()
