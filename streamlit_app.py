import streamlit as st
from ui.tabs import (
    welcome,
    introduction,
    case_study,
    data_download,
    optimization,
    results_deep_dive,
    sensitivity_analysis,
    financial_model,
)

import traceback

mailaddr = "markus.groissbock@openenergytransition.org"

def custom_error_page(error: Exception):
    """Render a user-friendly error UI."""
    st.error(
        """⚠️ Oops! Something went wrong."""
        )
    
    st.info(
        """
        We regret to inform you that an unexpected system error occurred while processing your request.
        
        We recommend refreshing your browser.
        
        Should the problem continue, please submit an inquiry to our support team.
        """
    )
    st.markdown(
        f'<a href="mailto:{mailaddr}">For suggestions, questions, remarks or any hints send us a message!</a>',
        unsafe_allow_html=True
    )
    
    if st.button("🔄 Refresh the page ..."):
        st.rerun()

    # Developer view inside an expander
    with st.expander("Show technical details ..."):
        st.code(traceback.format_exc(), language="python")

def main_app():
    st.set_page_config(
        page_title="PyPSA PPA Explorer",
        page_icon="⚡",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    st.markdown(
        """
        # PyPSA-based PPA Explorer
        """
    )
    st.warning(
        "**Proof of concept (PoC).** This is a demonstration tool for exploring PPA structures"
        "and portfolio economics, not a production planning system. Market data, cost assumptions "
        "and results are illustrative and should not be used to make real investment, procurement"
        "or legal decisions. Provided as-is, with no warranty of accuracy or fitness for any purpose.",
        icon="🚧",
    )
    st.markdown(
        f'<a href="mailto:{mailaddr}">For suggestions, questions, remarks or any hints send us a message!</a>',
        unsafe_allow_html=True
    )

    tabs = st.tabs(
        [
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
        ],
        on_change="rerun",
    )

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

    # i += 1
    # if tabs[i].open:
    #    with tabs[i]:
    #        scenario_analysis.render()

    # i += 1
    # if tabs[i].open:
    #    with tabs[i]:
    #        excel_import.render()

    # i += 1
    # if tabs[i].open:
    #    with tabs[i]:
    #        results_overview.render()

# Main Entry Point
if __name__ == "__main__":
    try:
        main_app()
    except Exception as e:
        custom_error_page(e)
