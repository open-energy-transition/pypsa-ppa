from __future__ import annotations

import pandas as pd
import pypsa

from ppa.scenario import Scenario


def build_network(ts: pd.DataFrame, scenario: Scenario, resolution_h: float = 1.0) -> pypsa.Network:
    """Build an unsolved PyPSA network from prepared timeseries and scenario.

    When `scenario.optimize_capacity` is True, wind/PV/BESS capacities become
    extendable investment variables (bounded by the per-tech max-build caps) and
    carry an annualized capital cost scaled to the LP horizon. Market sales earn
    no revenue in that mode, so the objective is least-cost-to-serve-the-PPA
    rather than merchant profit maximization (which would build to the caps).

    `resolution_h` is the hours each snapshot represents (>1 for the coarse
    sizing LP). It sets the snapshot weightings so marginal costs and storage
    state-of-charge integrate over real hours, not snapshot counts.
    """
    s = scenario
    n = pypsa.Network()
    n.set_snapshots(ts.index)
    if resolution_h != 1.0:
        n.snapshot_weightings.loc[:, :] = float(resolution_h)

    sizing = s.optimize_capacity
    # Annualized €/MW/yr (or €/MW-of-BESS/yr via fixed duration), scaled by the
    # fraction of a year the LP covers so capex and operational costs are summed
    # over the same horizon. crf annualizes overnight capex; opex_rate adds fixed O&M.
    horizon_years = len(ts) * resolution_h / 8760.0
    wind_cc = s.wind_capex_per_kw * 1_000 * (s.crf + s.opex_rate) * horizon_years
    pv_cc = s.pv_capex_per_kw * 1_000 * (s.crf + s.opex_rate) * horizon_years
    bess_cc = s.bess_capex_per_kwh * 1_000 * s.bess_max_hours * (s.crf + s.opex_rate) * horizon_years
    # Generous transport bound so links never constrain optimized builds
    build_cap_sum = s.max_build_wind_mw + s.max_build_pv_mw + s.max_build_bess_mw

    # ── Carriers ─────────────────────────────────────────────────────────────────
    n.add("Carrier", "AC")

    # ── Buses ─────────────────────────────────────────────────────────────────
    for bus_name in [
        "Bus_OnshoreWind",
        "Bus_PVBESS",
        "Bus_IPPGeneration",
        "Bus_BuyFromMarket",
        "Bus_SellToMarket",
        "Bus_PPAOfftake",
    ]:
        n.add(
            "Bus", 
            bus_name, 
            carrier="AC"
        )

    # ── Load ──────────────────────────────────────────────────────────────────
    n.add(
        "Load",
        "Load_PPAOfftake",
        bus="Bus_PPAOfftake",
        p_set=ts["ppaload_mw"],
    )

    # ── Generators ────────────────────────────────────────────────────────────
    n.add(
        "Generator",
        "Gen_OnshoreWind",
        bus="Bus_OnshoreWind",
        p_nom=0.0 if sizing else s.onsw_mw,
        p_nom_extendable=sizing,
        p_nom_max=s.max_build_wind_mw if sizing else float("inf"),
        capital_cost=wind_cc if sizing else 0.0,
        p_max_pu=ts["ts_WindGen"],
        marginal_cost=0.1,
    )

    n.add(
        "Generator",
        "Gen_PV",
        bus="Bus_PVBESS",
        p_nom=0.0 if sizing else s.pv_mw,
        p_nom_extendable=sizing,
        p_nom_max=s.max_build_pv_mw if sizing else float("inf"),
        capital_cost=pv_cc if sizing else 0.0,
        p_max_pu=ts["ts_PVGen"],
        marginal_cost=0.01,
    )

    n.add(
        "Generator",
        "Gen_BuyFromMarket",
        bus="Bus_BuyFromMarket",
        p_nom=s.maxbuy_mw,
        p_max_pu=1.0,
        marginal_cost=ts["ts_MktPrice"] + s.market_spread,
    )

    # sign=-1: acts as a sink at Bus_SellToMarket; negative marginal_cost = revenue.
    # In sizing mode the revenue is zeroed (free curtailment sink only) so the
    # optimizer doesn't build extra capacity purely to sell merchant power.
    n.add(
        "Generator",
        "Gen_SellToMarket",
        bus="Bus_SellToMarket",
        p_nom=build_cap_sum if sizing else s.maxsell_mw,
        p_max_pu=1.0,
        sign=-1.0,
        marginal_cost=0.0 if sizing else -(ts["ts_MktPrice"] - s.market_spread),
    )

    n.add(
        "Generator",
        "Gen_Penalty",
        bus="Bus_PPAOfftake",
        p_nom=s.ppaload_mw,
        p_max_pu=1.0,
        marginal_cost=s.penalty_price,
    )

    n.add(
        "Generator",
        "Gen_AllowedShortfall",
        bus="Bus_PPAOfftake",
        p_nom=s.ppaload_mw,
        p_max_pu=1.0,
        marginal_cost=0.001,
    )

    # ── Storage ───────────────────────────────────────────────────────────────
    # In sizing mode BESS power is optimized at fixed duration (max_hours);
    # energy = optimized MW × max_hours, priced via bess_cc (€/kWh × hours).
    n.add(
        "StorageUnit",
        "SU_BESS",
        bus="Bus_PVBESS",
        p_nom=0.0 if sizing else s.effective_bess_mw,
        p_nom_extendable=sizing,
        p_nom_max=s.max_build_bess_mw if sizing else float("inf"),
        capital_cost=bess_cc if sizing else 0.0,
        max_hours=s.bess_max_hours,
        efficiency_store=s.bess_efficiency_store,
        efficiency_dispatch=s.bess_efficiency_dispatch,
        cyclic_state_of_charge=True,
        marginal_cost=0.0,
    )

    # ── Links ─────────────────────────────────────────────────────────────────
    # In sizing mode transport links get a generous fixed bound so they never
    # constrain the optimized capacities; the PPA offtake link stays at load size.
    wind_link_mw = build_cap_sum if sizing else s.onsw_mw
    pvbess_link_mw = build_cap_sum if sizing else (s.pv_mw + s.effective_bess_mw)
    sell_link_mw = build_cap_sum if sizing else s.maxsell_mw

    link_defs = [
        ("OnshoreWind_to_IPPGeneration",   "Bus_OnshoreWind",   "Bus_IPPGeneration", wind_link_mw,   0.0),
        ("PVBESS_to_IPPGeneration",        "Bus_PVBESS",        "Bus_IPPGeneration", pvbess_link_mw, 0.0),
        ("BuyFromMarket_to_IPPGeneration", "Bus_BuyFromMarket", "Bus_IPPGeneration", s.maxbuy_mw,    0.0),
        ("IPPGen_to_SellToMarket",         "Bus_IPPGeneration", "Bus_SellToMarket",  sell_link_mw,   0.0),
        ("IPPGen_to_PPAOfftake",           "Bus_IPPGeneration", "Bus_PPAOfftake",    s.ppaload_mw,   -s.ppa_price),
    ]

    for name, bus0, bus1, p_nom, marginal_cost in link_defs:
        n.add(
            "Link",
            name,
            bus0=bus0,
            bus1=bus1,
            p_nom=p_nom,
            efficiency=1.0,
            marginal_cost=marginal_cost,
        )

    n.consistency_check()
    return n
