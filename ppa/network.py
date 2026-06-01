from __future__ import annotations

import pandas as pd
import pypsa

from ppa.scenario import Scenario


def build_network(ts: pd.DataFrame, scenario: Scenario) -> pypsa.Network:
    """Build an unsolved PyPSA network from prepared timeseries and scenario."""
    s = scenario
    n = pypsa.Network()
    n.set_snapshots(ts.index)

    # ── Buses ─────────────────────────────────────────────────────────────────
    for bus_name in [
        "Bus_OnshoreWind",
        "Bus_PVBESS",
        "Bus_IPPGeneration",
        "Bus_BuyFromMarket",
        "Bus_SellToMarket",
        "Bus_PPAOfftake",
    ]:
        n.add("Bus", bus_name)

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
        p_nom=s.onsw_mw,
        p_max_pu=ts["ts_WindGen"],
        marginal_cost=0.1,
    )

    n.add(
        "Generator",
        "Gen_PV",
        bus="Bus_PVBESS",
        p_nom=s.pv_mw,
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

    # sign=-1: acts as a sink at Bus_SellToMarket; negative marginal_cost = revenue
    n.add(
        "Generator",
        "Gen_SellToMarket",
        bus="Bus_SellToMarket",
        p_nom=s.maxsell_mw,
        p_max_pu=1.0,
        sign=-1.0,
        marginal_cost=-(ts["ts_MktPrice"] - s.market_spread),
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
    n.add(
        "StorageUnit",
        "SU_BESS",
        bus="Bus_PVBESS",
        p_nom=s.effective_bess_mw,
        max_hours=s.bess_max_hours,
        efficiency_store=s.bess_efficiency_store,
        efficiency_dispatch=s.bess_efficiency_dispatch,
        cyclic_state_of_charge=True,
        marginal_cost=0.0,
    )

    # ── Links ─────────────────────────────────────────────────────────────────
    link_defs = [
        ("OnshoreWind_to_IPPGeneration",   "Bus_OnshoreWind",   "Bus_IPPGeneration", s.onsw_mw,                      0.0),
        ("PVBESS_to_IPPGeneration",        "Bus_PVBESS",        "Bus_IPPGeneration", s.pv_mw + s.effective_bess_mw,  0.0),
        ("BuyFromMarket_to_IPPGeneration", "Bus_BuyFromMarket", "Bus_IPPGeneration", s.maxbuy_mw,                    0.0),
        ("IPPGen_to_SellToMarket",         "Bus_IPPGeneration", "Bus_SellToMarket",  s.maxsell_mw,                   0.0),
        ("IPPGen_to_PPAOfftake",           "Bus_IPPGeneration", "Bus_PPAOfftake",    s.ppaload_mw,                   -s.ppa_price),
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
