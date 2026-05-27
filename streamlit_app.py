import streamlit as st

st.set_page_config(
    page_title="PyPSA PPA Explorer",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

from ui.tabs import welcome, introduction, case_study, optimization, results_overview, results_deep_dive

tabs = st.tabs([
    "🏠 Welcome",
    "📖 Introduction to PPAs",
    "🔬 Case Study Definition",
    "⚙️ Optimization",
    "📊 Results Overview",
    "🔍 Results Deep Dive",
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
