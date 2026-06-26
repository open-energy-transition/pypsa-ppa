from __future__ import annotations

import streamlit as st


def render() -> None:
    cols = st.columns([3, 1])

    with cols[0]:
        st.markdown(
            """
# 👋 Welcome to the PyPSA PPA Toolkit!

**Interactive, full flexible and open-source toolkit** for modelling renewable portfolios under different 
**Power Purchase Agreement (PPA)** assumptions.
**PyPSA** — an open-source energy system optimisation framework — is used to optimise how a renewable portfolio
(wind, solar, battery storage) should be dispatched when bound by the commercial terms of a PPA.

## How to use this toolkit
Navigate through the tabs to manage different aspects of your project (economic and demand parameters) from left to right.

1. 🔬 **Case Setup** — pick one of the four predefined case studies to load a starting scenario, then
   customise any parameters using the sliders and inputs below the cards to reflect your personal assumptions.
    * *Portfolio modelling*: Wind + solar + battery storage co-located at a single aggregation point.
    * *PPA contract encoding*: Flat offtake loads, delivery obligations, shortfall caps, penalty multipliers.
    * *Market interaction*: Spot market buy/sell with configurable caps and bid-offer spreads.
    * *Financial assumptions*: CAPEX, LCOE, IRR, NPV, and breakeven PPA price discovery.
    * *Simulation details:* Years of simulation, price escalation, and technology degradation.

2. 📡 **Get Data** — download the necessary data.

3. ⚙️ **Optimization** — review the scenario summary and run the optimization to solve
   the model. This typically takes 5–15 seconds.

4. 🔍 **Results** — examine the full financial model (CAPEX, IRR, NPV, breakeven
   PPA price) and a detailed daily dispatch chart.

5. 🏦 **Financial Model** — explore the financial model in detail, including CAPEX, LCOE, 
   IRR, NPV, and breakeven PPA price.

6. 📊 **Sensitivity Analysis** — understand the impact of individual parameters on the overall economics.

7. 📖 **HELP** — introduce key concepts and terminology for newbies in the world of PPA and PyPSA.
            """
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
Historical hourly **European** data:

- Wind & solar capacity factors — [renewables.ninja](https://renewables.ninja)
- Day-ahead spot prices: [ENTSO-E](https://transparency.entsoe.eu)
            """
        )
