"""Temporal matching of PPA delivery against the offtaker load.

`Scenario.matching_period` sets the window within which delivered energy is
netted against load: "hourly" (no netting, the original behavior), "monthly"
or "annual". The distinguishing fixtures put a zero-renewables day next to an
abundant day, either in the same month or straddling a month boundary, so each
mode produces a different, hand-computable outcome.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from ppa.counterfactuals import compute_counterfactuals
from ppa.network import build_network
from ppa.results import extract_results
from ppa.scenario import (
    MATCHING_PERIODS,
    Scenario,
    scenario_from_excel,
    validate_scenario,
)
from ppa.solver import matching_period_groups, solve


def _two_day_ts(start: str, price: float = 50.0) -> pd.DataFrame:
    """Day 1: no renewable output at all. Day 2: wind at full output."""
    idx = pd.date_range(start, periods=48, freq="h", name="snapshot")
    wind = np.r_[np.zeros(24), np.ones(24)]
    return pd.DataFrame(
        {
            "ts_PVGen": np.zeros(48),
            "ts_WindGen": wind,
            "ts_MktPrice": np.full(48, price),
            "ppaload_mw": np.full(48, 100.0),
        },
        index=idx,
    )


@pytest.fixture
def wind_only_scenario() -> Scenario:
    # 300 MW of wind against a 100 MW flat load: day 2 alone produces three
    # times its own load, i.e. enough to cover both days if netting is allowed.
    # No shortfall allowance and no market buy, so every unmatched MWh is a
    # penalty and the outcome is fully determined by the matching period.
    return Scenario(
        onsw_mw=300.0,
        pv_mw=0.0,
        include_bess=False,
        bess_mw=0.0,
        bess_mwh=0.0,
        enable_market_buy=False,
        required_delivery_share=1.0,
        ppaload_mw=100.0,
    )


def _run(ts: pd.DataFrame, scenario: Scenario, matching_period: str):
    scn = dataclasses.replace(scenario, matching_period=matching_period)
    n = build_network(ts, scn)
    status, condition = solve(n, scn, ts)
    assert (status, condition) == ("ok", "optimal")
    return n, extract_results(n, scn, ts, status, condition)


# ── Scenario / validation ─────────────────────────────────────────────────────


def test_default_matching_period_is_hourly():
    assert Scenario().matching_period == "hourly"


@pytest.mark.parametrize("period", MATCHING_PERIODS)
def test_validate_scenario_accepts_every_matching_period(period):
    assert validate_scenario(Scenario(matching_period=period)) == []


def test_validate_scenario_rejects_unknown_matching_period():
    errors = validate_scenario(Scenario(matching_period="weekly"))
    assert any("matching period" in e for e in errors)


def test_scenario_from_excel_reads_matching_period(tmp_path):
    # scenario_from_excel reads the value from column B and the parameter name
    # from column E of the "Scenario" sheet.
    path = tmp_path / "scenario.xlsx"
    pd.DataFrame([[None, "Annual", None, None, "matching_period"]]).to_excel(
        path, sheet_name="Scenario", header=False, index=False
    )
    assert scenario_from_excel(path).matching_period == "annual"


def test_scenario_from_excel_defaults_to_hourly_matching(tmp_path):
    path = tmp_path / "scenario.xlsx"
    pd.DataFrame([[None, 100.0, None, None, "ppa_price"]]).to_excel(
        path, sheet_name="Scenario", header=False, index=False
    )
    assert scenario_from_excel(path).matching_period == "hourly"


# ── Period grouping ───────────────────────────────────────────────────────────


def test_matching_period_groups_hourly_has_no_groups():
    idx = pd.date_range("2023-01-31", periods=48, freq="h")
    assert matching_period_groups(idx, "hourly") == []


def test_matching_period_groups_monthly_splits_at_month_boundary():
    idx = pd.date_range("2023-01-31", periods=48, freq="h")
    groups = matching_period_groups(idx, "monthly")
    assert [suffix for suffix, _ in groups] == ["_202301", "_202302"]
    assert [len(snaps) for _, snaps in groups] == [24, 24]


def test_matching_period_groups_annual_splits_per_calendar_year():
    idx = pd.date_range("2023-12-31", periods=48, freq="h")
    groups = matching_period_groups(idx, "annual")
    assert [suffix for suffix, _ in groups] == ["_2023", "_2024"]
    # Months of the same year stay together.
    idx = pd.date_range("2023-01-31", periods=48, freq="h")
    assert len(matching_period_groups(idx, "annual")) == 1


def test_matching_period_groups_rejects_unknown_period():
    idx = pd.date_range("2023-01-01", periods=2, freq="h")
    with pytest.raises(ValueError):
        matching_period_groups(idx, "weekly")


# ── Network construction ──────────────────────────────────────────────────────


def test_hourly_network_has_no_matching_account_and_caps_delivery_at_load(
    tiny_ts, base_scenario
):
    n = build_network(tiny_ts, base_scenario)
    assert "Gen_MatchingBank" not in n.generators.static.index
    assert "Gen_MatchingDraw" not in n.generators.static.index
    assert n.links.static.p_nom["IPPGen_to_PPAOfftake"] == base_scenario.ppaload_mw


@pytest.mark.parametrize("period", ["monthly", "annual"])
def test_netted_network_adds_matching_account_and_lifts_delivery_cap(
    tiny_ts, base_scenario, period
):
    scn = dataclasses.replace(base_scenario, matching_period=period)
    n = build_network(tiny_ts, scn)
    gens = n.generators.static
    bank, draw = gens.loc["Gen_MatchingBank"], gens.loc["Gen_MatchingDraw"]
    assert bank.bus == draw.bus == "Bus_PPAOfftake"
    assert bank.sign == -1.0  # absorbs over-delivery
    assert draw.sign == 1.0  # supplies load in deficit hours
    # Delivery is bounded by everything that can physically reach the hub.
    expected_cap = scn.onsw_mw + scn.pv_mw + scn.effective_bess_mw + scn.maxbuy_mw
    assert n.links.static.p_nom["IPPGen_to_PPAOfftake"] == pytest.approx(expected_cap)


# ── Dispatch behavior ─────────────────────────────────────────────────────────


def test_hourly_matching_never_delivers_more_than_hourly_load(tiny_ts, base_scenario):
    _, res = _run(tiny_ts, base_scenario, "hourly")
    assert (res.dispatch.ppa_delivery <= tiny_ts["ppaload_mw"] + 1e-6).all()
    assert res.summary.netted_delivery_mwh == 0.0


def test_surplus_day_covers_deficit_day_in_same_month_only_with_netting(
    wind_only_scenario,
):
    """Both days in January: monthly and annual netting let day 2's surplus
    cover day 1 completely; hourly matching penalises all of day 1."""
    ts = _two_day_ts("2023-01-10")
    day_load = 24 * 100.0

    _, hourly = _run(ts, wind_only_scenario, "hourly")
    assert hourly.summary.penalty_mwh == pytest.approx(day_load, rel=1e-6)
    assert hourly.summary.fulfilled_share == pytest.approx(0.5, rel=1e-6)

    for period in ("monthly", "annual"):
        _, res = _run(ts, wind_only_scenario, period)
        assert res.summary.penalty_mwh == pytest.approx(0.0, abs=1e-6)
        assert res.summary.fulfilled_share == pytest.approx(1.0, rel=1e-6)
        # Day 1's whole load was served from day 2's banked surplus...
        assert res.summary.netted_delivery_mwh == pytest.approx(day_load, rel=1e-6)
        # ...which needed day 2 to over-deliver beyond its hourly load.
        day2 = ts.index.day == ts.index[-1].day
        assert res.dispatch.ppa_delivery[day2].sum() == pytest.approx(
            2 * day_load, rel=1e-6
        )
        assert res.dispatch.ppa_delivery.max() > 100.0


def test_monthly_matching_cannot_carry_surplus_across_a_month_boundary(
    wind_only_scenario,
):
    """Deficit day on Jan 31, surplus day on Feb 1: monthly matching can't net
    them (each month settles on its own) while annual matching can."""
    ts = _two_day_ts("2023-01-31")
    day_load = 24 * 100.0

    _, monthly = _run(ts, wind_only_scenario, "monthly")
    assert monthly.summary.penalty_mwh == pytest.approx(day_load, rel=1e-6)
    assert monthly.summary.fulfilled_share == pytest.approx(0.5, rel=1e-6)
    feb = ts.index.month == 2
    # February can't over-deliver to pre-pay January's deficit.
    assert monthly.dispatch.ppa_delivery[feb].sum() == pytest.approx(
        ts.loc[feb, "ppaload_mw"].sum(), rel=1e-6
    )

    _, annual = _run(ts, wind_only_scenario, "annual")
    assert annual.summary.penalty_mwh == pytest.approx(0.0, abs=1e-6)
    assert annual.summary.fulfilled_share == pytest.approx(1.0, rel=1e-6)


def test_annual_matching_carries_across_months_but_not_across_years(
    wind_only_scenario,
):
    ts = _two_day_ts("2023-12-31")
    _, annual = _run(ts, wind_only_scenario, "annual")
    assert annual.summary.penalty_mwh == pytest.approx(24 * 100.0, rel=1e-6)


@pytest.mark.parametrize("period", MATCHING_PERIODS)
def test_volumes_balance_against_load_within_every_matching_period(
    wind_only_scenario, period
):
    """delivered + shortfall + penalty == load per period (per hour for hourly),
    and the matching account closes (bank == draw) within every period."""
    ts = _two_day_ts("2023-01-31")
    # Partial wind on day 1 gives a mix of shortfall, penalty and netting.
    ts["ts_WindGen"] = np.r_[np.full(24, 0.2), np.full(24, 0.6)]
    scn = dataclasses.replace(wind_only_scenario, required_delivery_share=0.8)
    n, res = _run(ts, scn, period)
    d = res.dispatch
    served = d.ppa_delivery + d.allowed_shortfall + d.penalty_gen
    keys = {
        "hourly": ts.index,
        "monthly": ts.index.month,
        "annual": ts.index.year,
    }[period]
    pd.testing.assert_series_equal(
        served.groupby(keys).sum(),
        ts["ppaload_mw"].groupby(keys).sum(),
        check_names=False,
        rtol=1e-6,
    )
    if period != "hourly":
        p = n.generators.dynamic.p
        net = (p["Gen_MatchingDraw"] - p["Gen_MatchingBank"]).groupby(keys).sum()
        assert np.allclose(net, 0.0, atol=1e-6)


def test_looser_matching_is_never_worse_for_the_ipp(tiny_ts, base_scenario):
    """Hourly ⊂ monthly ⊂ annual as feasible sets, so the (minimised) objective
    can only fall and delivery can only rise as the matching window widens."""
    scn = dataclasses.replace(base_scenario, required_delivery_share=0.95)
    objectives, fulfilled = [], []
    for period in MATCHING_PERIODS:
        n, res = _run(tiny_ts, scn, period)
        objectives.append(n.objective)
        fulfilled.append(res.summary.fulfilled_share)
    assert objectives[0] >= objectives[1] - 1e-6 >= objectives[2] - 2e-6
    assert fulfilled[0] <= fulfilled[1] + 1e-9 <= fulfilled[2] + 2e-9


def test_annual_matching_shifts_delivery_into_cheap_hours():
    """With constant output and prices alternating around the PPA tariff,
    annual netting lets the IPP sell every expensive hour at spot and deliver
    the full contract volume in the cheap hours; hourly matching can't (the
    penalty is set above the spot peak so hourly can't just pay it instead)."""
    idx = pd.date_range("2023-03-01", periods=48, freq="h", name="snapshot")
    expensive = np.arange(48) % 2 == 1
    ts = pd.DataFrame(
        {
            "ts_PVGen": np.zeros(48),
            "ts_WindGen": np.ones(48),
            "ts_MktPrice": np.where(expensive, 300.0, 30.0),
            "ppaload_mw": np.full(48, 100.0),
        },
        index=idx,
    )
    scn = Scenario(
        onsw_mw=200.0,
        pv_mw=0.0,
        include_bess=False,
        bess_mw=0.0,
        bess_mwh=0.0,
        enable_market_buy=False,
        ppa_price=100.0,
        pen_mult=4.0,
        required_delivery_share=1.0,
    )

    _, hourly = _run(ts, scn, "hourly")
    assert hourly.dispatch.ppa_delivery[expensive].min() == pytest.approx(100.0)

    _, annual = _run(ts, scn, "annual")
    assert annual.dispatch.ppa_delivery[expensive].max() == pytest.approx(0.0, abs=1e-6)
    assert annual.dispatch.ppa_delivery[~expensive].min() == pytest.approx(200.0)
    assert annual.summary.fulfilled_share == pytest.approx(1.0)
    assert annual.revenue.net_revenue > hourly.revenue.net_revenue


# ── Sizing LP ─────────────────────────────────────────────────────────────────


def test_sizing_lp_enforces_matching_balance_per_calendar_year(wind_only_scenario):
    """In a multi-year sizing horizon the matching balance must close each
    calendar year, not once over the whole horizon."""
    ts = _two_day_ts("2023-12-31")
    scn = dataclasses.replace(
        wind_only_scenario,
        matching_period="annual",
        optimize_capacity=True,
        max_build_wind_mw=500.0,
        max_build_pv_mw=0.0,
        max_build_bess_mw=0.0,
    )
    n = build_network(ts, scn)
    status, _ = solve(n, scn, ts)
    assert status == "ok"
    assert {"MatchingBalance_2023", "MatchingBalance_2024"} <= set(n.model.constraints)
    p = n.generators.dynamic.p
    yearly_net = (
        (p["Gen_MatchingDraw"] - p["Gen_MatchingBank"]).groupby(ts.index.year).sum()
    )
    assert np.allclose(yearly_net, 0.0, atol=1e-6)
    # Each year is settled on its own: the dark 2023 day is fully penalised
    # however much wind the LP builds for 2024.
    assert float(p["Gen_Penalty"][ts.index.year == 2023].sum()) == pytest.approx(
        24 * 100.0, rel=1e-6
    )


# ── Counterfactuals ───────────────────────────────────────────────────────────


def test_counterfactual_offtaker_cost_resells_over_delivery_at_spot(
    wind_only_scenario,
):
    ts = _two_day_ts("2023-01-10")
    ts["ts_MktPrice"] = np.linspace(20.0, 80.0, 48)
    scn = dataclasses.replace(wind_only_scenario, matching_period="annual")
    _, res = _run(ts, scn, "annual")
    cf = compute_counterfactuals(ts, scn, res)

    delivery = res.dispatch.ppa_delivery
    assert (delivery > scn.ppaload_mw + 1e-6).any()  # over-delivery happened
    expected = float(
        (
            scn.ppa_price * delivery + ts["ts_MktPrice"] * (scn.ppaload_mw - delivery)
        ).sum()
    )
    assert cf.ppa_offtaker_cost == pytest.approx(expected, rel=1e-9)
