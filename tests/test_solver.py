from __future__ import annotations

import dataclasses

import pandas as pd
import pytest

from ppa.network import build_network
from ppa.scenario import Scenario
from ppa.solver import solve


def test_solve_dispatch_network_reaches_optimum(tiny_ts, base_scenario):
    n = build_network(tiny_ts, base_scenario)
    status, condition = solve(n, base_scenario, tiny_ts)
    assert status == "ok"
    assert condition == "optimal"


def test_solve_respects_allowed_shortfall_cap(tiny_ts, base_scenario):
    """AllowedShortfall_Limit constraint: shortfall energy <= allowed_shortfall_share * load."""
    scn = dataclasses.replace(base_scenario, required_delivery_share=0.5, enable_shortfall=True)
    n = build_network(tiny_ts, scn)
    solve(n, scn, tiny_ts)

    shortfall_mwh = float(n.generators.dynamic.p["Gen_AllowedShortfall"].sum())
    total_load_mwh = float(tiny_ts["ppaload_mw"].sum())
    cap = scn.allowed_shortfall_share * total_load_mwh
    assert shortfall_mwh <= cap + 1e-6


def test_solve_respects_market_buy_share_cap(tiny_ts, base_scenario):
    """BuyFromMarket_Limit constraint: buy volume <= market_buy_share * PPA delivery."""
    scn = dataclasses.replace(
        base_scenario, enable_market_buy=True, market_buy_share=0.05, onsw_mw=10.0, pv_mw=10.0
    )
    n = build_network(tiny_ts, scn)
    solve(n, scn, tiny_ts)

    buy_mwh = float(n.generators.dynamic.p["Gen_BuyFromMarket"].sum())
    delivered_mwh = float(-n.links.dynamic.p1["IPPGen_to_PPAOfftake"].sum())
    assert buy_mwh <= scn.market_buy_share * delivered_mwh + 1e-6


def test_solve_with_market_buy_disabled_forces_zero_purchases(tiny_ts, base_scenario):
    scn = dataclasses.replace(base_scenario, enable_market_buy=False)
    n = build_network(tiny_ts, scn)
    status, condition = solve(n, scn, tiny_ts)
    assert status == "ok"
    assert float(n.generators.dynamic.p["Gen_BuyFromMarket"].sum()) == pytest.approx(0.0)


def test_solve_full_bess_charge_discharge_cycle_is_energy_consistent(tiny_ts, base_scenario):
    n = build_network(tiny_ts, base_scenario)
    solve(n, base_scenario, tiny_ts)

    soc = n.storage_units.dynamic.state_of_charge["SU_BESS"]
    assert (soc >= -1e-6).all()
    assert (soc <= base_scenario.bess_mwh + 1e-6).all()


def test_solve_multi_year_snapshot_groups_bind_shortfall_per_calendar_year(base_scenario):
    """The allowed-shortfall cap must bind separately for each calendar year,
    not in aggregate across the whole sizing horizon (see solver.py's
    per-year snapshot_groups). Distinguishing scenario: year 2023 has zero
    renewable output (forcing it to rely entirely on AllowedShortfall +
    Penalty), year 2024 has abundant renewable output (needing neither).
    An aggregate (non-per-year) cap would let 2023 borrow 2024's unused
    shortfall allowance and cover its whole day for free; the per-year cap
    forces real Penalty cost in 2023 instead."""
    idx = pd.date_range("2023-12-31", periods=48, freq="h")  # 24h in 2023, 24h in 2024
    is_2023 = idx.year == 2023
    ts = pd.DataFrame(
        {
            "ts_PVGen": [0.0 if y else 1.0 for y in is_2023],
            "ts_WindGen": [0.0 if y else 1.0 for y in is_2023],
            "ts_MktPrice": [50.0] * 48,
            "ppaload_mw": [100.0] * 48,
        },
        index=idx,
    )
    # optimize_capacity=True is required: solver.py only splits the shortfall
    # cap into per-year snapshot_groups in sizing mode (see solver.py, `years =
    # pd.Index(ts.index.year); if s.optimize_capacity and years.nunique() > 1`);
    # a fixed-capacity dispatch run always uses one aggregate constraint.
    scn = dataclasses.replace(
        base_scenario,
        optimize_capacity=True,
        max_build_wind_mw=0.0,
        max_build_pv_mw=200.0,
        max_build_bess_mw=0.0,
        include_bess=False,
        enable_market_buy=False,
        enable_shortfall=True,
        enable_penalty=True,
        required_delivery_share=0.5,
    )
    n = build_network(ts, scn)
    status, condition = solve(n, scn, ts)
    assert status == "ok"

    shortfall = n.generators.dynamic.p["Gen_AllowedShortfall"]
    penalty = n.generators.dynamic.p["Gen_Penalty"]
    load_2023 = float(ts.loc[is_2023, "ppaload_mw"].sum())

    shortfall_2023 = float(shortfall[is_2023].sum())
    penalty_2023 = float(penalty[is_2023].sum())
    cap_2023 = scn.allowed_shortfall_share * load_2023

    # Per-year cap enforced: 2023's shortfall alone can't exceed its own cap,
    # and (being free) the optimizer uses exactly up to that cap...
    assert shortfall_2023 <= cap_2023 + 1e-6
    assert shortfall_2023 == pytest.approx(cap_2023, rel=1e-6)
    # ...so with zero renewables and no market buy, the *rest* of 2023's load
    # must flow through the (expensive) Penalty generator. If the cap were
    # wrongly aggregated over both years instead, 2024's unused allowance
    # would cover all of 2023 for free and this would be ~0.
    assert penalty_2023 == pytest.approx(load_2023 - cap_2023, rel=1e-6)
    assert shortfall_2023 + penalty_2023 == pytest.approx(load_2023, rel=1e-6)

    # 2024 is fully covered by abundant renewables: no shortfall, no penalty.
    assert float(shortfall[~is_2023].sum()) == pytest.approx(0.0, abs=1e-6)
    assert float(penalty[~is_2023].sum()) == pytest.approx(0.0, abs=1e-6)
