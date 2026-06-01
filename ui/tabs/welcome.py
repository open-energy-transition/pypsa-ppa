from __future__ import annotations

import streamlit as st


def render() -> None:
    cols = st.columns([2, 1])

    with cols[0]:
        st.markdown(
            """
# 🏠 Welcome to the PyPSA PPA Toolkit!

This app uses **PyPSA** — an open-source energy system optimisation framework — to model
how a renewable portfolio (wind, solar, battery storage) should be dispatched when bound
by the commercial terms of a Power Purchase Agreement.

The underlying optimisation finds the **least-cost hourly dispatch** across the provided
set of market data, honouring contractual delivery obligations, shortfall allowances, 
penalty regimes, market interaction caps, and installation of wind, solar, and/or battery
storage.

## How to use this toolkit
1. **Introduction to PPAs** — introduce key concepts and terminology for newbies in the 
   world of PPA.

2. **Case Study Definition** — pick one of the four predefined case studies to load a
   starting scenario, then customise any parameters using the sliders and inputs below
   the cards to reflect your personal assumptions.
    * *Portfolio modelling*: Wind + solar + battery storage co-located at a single aggregation point.
    * *PPA contract encoding*: Flat offtake loads, delivery obligations, shortfall caps, penalty multipliers.
    * *Market interaction*: Spot market buy/sell with configurable caps and bid-offer spreads.
    * *Linear optimisation*: HiGHS solver via PyPSA / Linopy for each 744-hour month.
    * *Financial analysis*: CAPEX, LCOE, IRR, NPV, and breakeven PPA price discovery.
    * *Scenario comparison:* Four predefined case studies plus full custom parameter control.


3. **Optimization** — review the scenario summary and run the optimization to solve
   the model. This typically takes 5–15 seconds.

4. **Results Overview** — explore key KPIs: PPA fulfilment rate, LCOE, net revenue, and
   the hourly supply mix chart.

5. **Results Deep Dive** — examine the full financial model (CAPEX, IRR, NPV, breakeven
   PPA price) and a detailed daily dispatch chart.
            """
        )
        st.info(
            "**Tip:** Optimization results are preserved as you switch between tabs.",
            icon="💡",
        )

    with cols[1]:
        st.markdown(
            """
### Built with

- [PyPSA](https://pypsa.readthedocs.io) — energy system modelling
- [HiGHS](https://highs.dev) — LP solver
- [Streamlit](https://streamlit.io) — web UI
- [Plotly](https://plotly.com) — interactive charts

### Data
Initially, real hourly NEM data for **March 2025** (NSW dispatch region) are considered (sourced via UNSW-CEEM's *NEMOSIS*).

Includes:
- Wind capacity factors
- Solar PV capacity factors
- NSW spot electricity prices
            """
        )
