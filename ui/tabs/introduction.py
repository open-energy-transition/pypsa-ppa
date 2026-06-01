from __future__ import annotations

import streamlit as st

from ppa.data_loader import find_default_csv, load_timeseries
from ppa.scenario import BASE_SCENARIO
from ui.charts import (
    make_price_vs_ppa_chart,
    make_availability_profile_chart,
    make_ppa_obligation_chart,
    make_portfolio_flow_chart,
)


@st.cache_data
def _load_ts(path: str):
    return load_timeseries(path)


def render() -> None:
    st.title("📖 Introduction to PPAs")
    st.markdown(
        "A primer on Power Purchase Agreements — what they are, how they work, and why energy "
        "system modelling adds value for both developers and offtakers."
    )
    st.markdown("---")

    # ── What is a PPA ─────────────────────────────────────────────────────────
    st.header("What is a Power Purchase Agreement?")
    st.markdown(
        """
A **Power Purchase Agreement (PPA)** is a long-term contract between a power producer and a buyer
(the *offtaker*) that sets out the terms under which electricity is sold — including the price,
volume, delivery obligations, and what happens when those obligations are not met.

PPAs have become a central instrument in the global energy transition:

- **Enabling renewable project finance.** Developers use PPAs to secure predictable revenue that
  underpins project debt, reducing the cost of capital for new wind and solar capacity. Without a
  PPA, a merchant project must absorb the full volatility of wholesale electricity prices, which
  makes financing harder and more expensive.

- **Supporting corporate clean energy procurement.** Large energy consumers — data centres,
  manufacturers, retailers — use PPAs to source renewable electricity at contracted prices,
  supporting net-zero commitments and RE100 targets.

- **Managing price and volume risk.** PPAs allow both producers and buyers to hedge against spot
  price volatility. The contract allocates risk between counterparties: who bears the cost of a
  price spike? Who is exposed if the wind doesn't blow?
        """
    )

    # Chart: spot price vs PPA price
    csv = find_default_csv()
    ts = _load_ts(str(csv)) if csv else None
    if ts is not None:
        st.plotly_chart(
            make_price_vs_ppa_chart(ts, ppa_price=BASE_SCENARIO.ppa_price),
            use_container_width=True, height=400,
        )
        st.caption(
            "Real NSW wholesale spot prices for March 2025 can swing from deeply negative "
            "(oversupply) to thousands of dollars per MWh (scarcity events) within the same day. "
            "A PPA fixes the revenue stream for the generator at the contracted tariff — "
            "insulating both parties from this volatility."
        )

    st.subheader("PPA structures vary widely")
    st.markdown(
        """
| Dimension | Common variants |
|---|---|
| **Delivery structure** | Pay-as-produced (variable output), baseload or shaped, 24/7 hourly matched |
| **Settlement** | Physical (direct supply to buyer), virtual / financial (CfD settled against spot) |
| **Duration** | Short-term (1–5 years) through to long-term (10–20+ years) |
| **Offtake profile** | Flat MW demand, shaped to the buyer's load, or a defined hourly schedule |
| **Balancing obligations** | Who covers shortfall or excess, and at what penalty rate? |
        """
    )

    # Chart: PPA obligation diagram
    s = BASE_SCENARIO
    st.subheader("Delivery obligations and penalty structure")
    st.markdown(
        "Most PPAs specify a minimum delivery obligation over the contract period. "
        "Below is an example structure — the same parameters used in this app's base scenario."
    )
    st.plotly_chart(
        make_ppa_obligation_chart(
            s.required_delivery_share,
            s.allowed_shortfall_share,
            s.ppaload_mw,
            s.pen_mult,
            s.ppa_price,
        ),
        use_container_width=True,
    )
    st.caption(
        f"The IPP must deliver at least **{s.required_delivery_share:.0%}** of the contracted "
        f"{s.ppaload_mw:.0f} MW load on average over the period. Up to "
        f"**{s.allowed_shortfall_share:.0%}** may go undelivered without penalty. "
        f"Any shortfall beyond that cap incurs a **{s.pen_mult:.1f}× tariff** penalty "
        f"(${s.ppa_price * s.pen_mult:.0f}/MWh)."
    )

    st.markdown("---")

    # ── Key terms ─────────────────────────────────────────────────────────────
    st.header("Key terms")
    st.markdown(
        """
| Term | Meaning |
|---|---|
| **MW** | Megawatt — a unit of *power* (rate of energy flow at an instant) |
| **MWh** | Megawatt-hour — a unit of *energy* (volume). Revenue and costs are expressed per MWh. |
| **MWac** | Megawatt AC — the AC-side output capacity of a solar inverter |
| **Capacity factor** | Actual output as a fraction of maximum possible output |
| **IPP** | Independent Power Producer — owns and operates generation assets |
| **Offtaker** | The buyer in a PPA |
| **BESS** | Battery Energy Storage System — co-located storage used to shift generation in time |
| **NEM / AEMO** | National Electricity Market / its operator in eastern Australia |
| **Spot price** | Real-time wholesale electricity price — can spike very high or go negative |
| **Merchant revenue** | Revenue from selling into the spot market at prevailing prices |
| **LCOE** | Levelised Cost of Energy — total lifetime costs ÷ total lifetime energy ($/MWh) |
| **IRR** | Internal Rate of Return — the discount rate at which project NPV = 0 |
| **WACC** | Weighted Average Cost of Capital — blended required return on debt and equity |
        """
    )

    st.markdown("---")

    # ── Why model ─────────────────────────────────────────────────────────────
    st.header("Why model a PPA with PyPSA?")
    st.markdown(
        """
PyPSA is often used to model entire energy grids, but it can also model **how particular plants
operate under PPAs**. In this framing, we model the *commercial flows of power* — dispatch is
optimised against the conditions of the offtake contract.

This is useful for renewable energy developers who are building grid-connected plants and intend
to sell power under an offtake agreement. PyPSA modelling can be used to:

- **Size the plant and storage configuration** — how much wind, solar, and battery do you need?
- **Test dispatch strategies** — when should the BESS charge vs. dispatch?
- **Compare PPA structures** — what delivery obligation can the portfolio reliably meet?
- **Quantify risk** — what is the expected penalty exposure under different market price scenarios?
        """
    )

    # Chart: renewable availability profiles
    if ts is not None:
        st.subheader("The dispatch challenge: renewable availability vs flat demand")
        st.plotly_chart(
            make_availability_profile_chart(ts),
            use_container_width=True, height=400,
        )
        st.caption(
            "Solar peaks sharply around midday and is zero overnight. Wind is more distributed "
            "but still variable. A PPA with a **flat 100 MW load** requires delivery at all hours — "
            "including nights and cloudy, low-wind periods. This mismatch is what makes storage "
            "and market interaction valuable: the BESS can absorb surplus afternoon solar and "
            "discharge it during the early-evening demand window when solar has dropped off."
        )

    st.markdown("---")

    # ── PyPSA components ──────────────────────────────────────────────────────
    st.header("PyPSA modelling components")
    st.markdown(
        """
The network in this app represents **commercial energy flows**, not physical grid connections.
Each bus, generator, and link is chosen so that the optimiser's dispatch decisions reflect the
contractual economics of the PPA.

| Component | What it represents |
|---|---|
| **Bus** | A node where energy must balance each hour |
| **Generator** | A source of power (wind, solar) or a commercial construct (penalty, shortfall allowance) |
| **Load** | A fixed power demand — the PPA offtake obligation |
| **StorageUnit** | The BESS — absorbs and releases power with a state of charge that persists across hours |
| **Link** | A directed connection between buses, with optional marginal cost representing contract value |

The key parameter driving every dispatch decision is **`marginal_cost`**: the optimiser minimises
total cost across all components and all hours. Setting `marginal_cost = -ppa_price` on the PPA
delivery link makes the model treat delivery as commercially valuable — the core of the formulation.
        """
    )

    st.markdown("---")

    # ── Network structure ─────────────────────────────────────────────────────
    st.header("Network structure")
    st.markdown(
        "The six-bus commercial network used in this app connects physical generation assets "
        "to contractual outcomes through a central IPP aggregation point. "
        "The diagram below shows the base scenario configuration — it updates live "
        "to reflect the active case study once you select one."
    )

    from ui import state as _state
    active_scenario = _state.get_scenario() or BASE_SCENARIO
    st.plotly_chart(
        make_portfolio_flow_chart(active_scenario),
        use_container_width=True,
    )

    cols = st.columns([1, 1])
    with cols[0]:
        st.markdown(
            """
**Physical assets (left)**
- `Bus_OnshoreWind` → wind generator
- `Bus_PVBESS` → solar + battery storage
- `Bus_BuyFromMarket` → spot market purchase

**Commercial aggregation (centre)**
- `Bus_IPPGeneration` — all generation converges here before dispatch decisions are made

**Contractual outcomes (right)**
- `Bus_PPAOfftake` — PPA delivery point; load must balance each hour via delivery, shortfall, or penalty
- `Bus_SellToMarket` — excess generation sold at spot
            """
        )
    with cols[1]:
        st.markdown(
            """
**Key link: `IPPGen_to_PPAOfftake`**

This link carries `marginal_cost = −ppa_price`, meaning the optimiser *earns* the PPA tariff
for every MWh dispatched through it. This is what makes PPA delivery commercially preferable
to merchant sales in most hours.

**Balancing at `Bus_PPAOfftake`**

When the portfolio cannot fully deliver, two generators balance the load:
- `Gen_AllowedShortfall` — near-zero cost, but capped in aggregate (the permitted gap)
- `Gen_Penalty` — costs 1.5× the tariff; used only after the shortfall cap is exhausted
            """
        )
