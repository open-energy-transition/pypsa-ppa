from __future__ import annotations

import dataclasses

import pytest

from ppa.network import build_network


EXPECTED_BUSES = {
    "Bus_OnshoreWind",
    "Bus_PV",
    "Bus_REBESS",
    "Bus_IPPGeneration",
    "Bus_BuyFromMarket",
    "Bus_SellToMarket",
    "Bus_PPAOfftake",
}


def test_build_network_dispatch_mode_has_expected_topology(tiny_ts, base_scenario):
    n = build_network(tiny_ts, base_scenario)

    assert set(n.buses.static.index) == EXPECTED_BUSES
    assert len(n.snapshots) == len(tiny_ts)
    assert "Gen_OnshoreWind" in n.generators.static.index
    assert "SU_BESS" in n.storage_units.static.index
    assert "IPPGen_to_PPAOfftake" in n.links.static.index


def test_build_network_dispatch_mode_fixes_capacities_from_scenario(
    tiny_ts, base_scenario
):
    n = build_network(tiny_ts, base_scenario)
    gens = n.generators.static
    assert gens.loc["Gen_OnshoreWind", "p_nom"] == pytest.approx(base_scenario.onsw_mw)
    assert gens.loc["Gen_PV", "p_nom"] == pytest.approx(base_scenario.pv_mw)
    assert not gens.loc["Gen_OnshoreWind", "p_nom_extendable"]
    assert n.storage_units.static.loc["SU_BESS", "p_nom"] == pytest.approx(
        base_scenario.effective_bess_mw
    )


def test_build_network_sizing_mode_makes_capacities_extendable(tiny_ts, base_scenario):
    sizing_scn = dataclasses.replace(
        base_scenario,
        optimize_capacity=True,
        max_build_wind_mw=500.0,
        max_build_pv_mw=500.0,
        max_build_bess_mw=200.0,
    )
    n = build_network(tiny_ts, sizing_scn)
    gens = n.generators.static
    assert gens.loc["Gen_OnshoreWind", "p_nom"] == 0.0
    assert gens.loc["Gen_OnshoreWind", "p_nom_extendable"]
    assert gens.loc["Gen_OnshoreWind", "p_nom_max"] == pytest.approx(500.0)
    assert gens.loc["Gen_OnshoreWind", "capital_cost"] > 0.0
    # Sizing mode: selling merchant power earns no revenue (curtailment sink only).
    assert gens.loc["Gen_SellToMarket", "marginal_cost"] == 0.0


def test_build_network_disabled_market_buy_zeroes_capacity(tiny_ts, base_scenario):
    scn = dataclasses.replace(base_scenario, enable_market_buy=False)
    n = build_network(tiny_ts, scn)
    assert n.generators.static.loc["Gen_BuyFromMarket", "p_nom"] == 0.0


def test_build_network_disabled_market_sell_zeroes_capacity(tiny_ts, base_scenario):
    scn = dataclasses.replace(base_scenario, enable_market_sell=False)
    n = build_network(tiny_ts, scn)
    assert n.generators.static.loc["Gen_SellToMarket", "p_nom"] == 0.0


def test_build_network_no_bess_zeros_storage_capacity(tiny_ts, base_scenario):
    scn = dataclasses.replace(base_scenario, include_bess=False)
    n = build_network(tiny_ts, scn)
    assert n.storage_units.static.loc["SU_BESS", "p_nom"] == 0.0


def test_build_network_coarse_resolution_sets_snapshot_weightings(
    tiny_ts, base_scenario
):
    n = build_network(tiny_ts, base_scenario, resolution_h=3.0)
    assert (n.snapshot_weightings.objective == 3.0).all()
    assert (n.snapshot_weightings.stores == 3.0).all()


def test_build_network_passes_consistency_check(tiny_ts, base_scenario):
    # build_network calls n.consistency_check() internally; constructing it at
    # all (without raising) is the assertion here.
    build_network(tiny_ts, base_scenario)
