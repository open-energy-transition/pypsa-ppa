from __future__ import annotations

import streamlit as st


def render() -> None:
    st.markdown(
        """
# 👋 Welcome to the PyPSA PPA Toolkit!

**An interactive, flexible, open-source toolkit** for modelling renewable portfolios under different
**Power Purchase Agreement (PPA)** assumptions.
**PyPSA**, an open-source energy system optimisation framework, is used to optimise how a renewable portfolio
(wind, solar, battery storage) should be dispatched when bound by the commercial terms of a PPA.

## How to use this toolkit
Navigate through the tabs left to right to work through the different aspects of your project: economic assumptions, demand, and results.

1. 🔬 **Case Setup**: pick one of the four predefined case studies to load a starting scenario, then
   customise any parameters using the sliders and inputs below the cards to reflect your own assumptions.
    * *Portfolio modelling*: wind, solar and battery storage.
    * *PPA contract terms*: flat offtake loads, delivery obligations, shortfall caps, penalty multipliers.
    * *Market interaction*: spot market buy/sell with configurable caps and bid-offer spreads.
    * *Financial assumptions*: CAPEX, LCOE, IRR, NPV, and breakeven PPA price discovery.
    * *Simulation details*: years of simulation, price escalation, and technology degradation.

2. 📡 **Get Data**: download the necessary market prices and renewable profiles, or bring your own
   data by uploading a filled-in template for any weather year.

3. ⚙️ **Optimization**: review the scenario summary and run the optimization to solve
   the model. This typically takes 5 to 15 seconds.

4. 🔍 **Results**: examine the full financial model (CAPEX, IRR, NPV, breakeven
   PPA price) and a detailed daily dispatch chart.

5. 🏦 **Financial Model**: explore the levered project-finance model in detail, including CAPEX, LCOE,
   IRR, NPV, and breakeven PPA price.

6. 📊 **Sensitivity Analysis**: see how individual parameters affect the overall economics.

7. 📖 **HELP**: key concepts and terminology, useful if PPAs or PyPSA are new to you.
        """
    )

    with st.expander("Main packages and data sources", expanded=False):
        st.markdown(
            """
- [PyPSA](https://pypsa.readthedocs.io): energy system modelling
- [HiGHS](https://highs.dev): LP solver
- [Streamlit](https://streamlit.io): web UI
- [Plotly](https://plotly.com): interactive charts
- and using *historical* data from
  - [renewables.ninja](https://renewables.ninja) for wind & solar hourly profiles, and
  - [ENTSO-E](https://transparency.entsoe.eu) for day-ahead spot prices for Europe.
            """
        )
