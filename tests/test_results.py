from __future__ import annotations

import pytest

from ppa.results import build_24h_avg, build_ops_day_df, build_supply_mix_df


def test_extract_results_volumes_balance_against_load(solved_result, tiny_ts):
    summ = solved_result.summary
    total_load = float(tiny_ts["ppaload_mw"].sum())
    assert summ.total_load_mwh == pytest.approx(total_load)
    # Delivered + shortfall + penalty must reconstruct the load exactly
    # (the PPA offtake bus balances delivery, shortfall and penalty inflows).
    assert (
        summ.ppa_delivered_mwh + summ.allowed_shortfall_mwh + summ.penalty_mwh
        == pytest.approx(total_load, rel=1e-6)
    )


def test_extract_results_shares_are_between_zero_and_one(solved_result):
    summ = solved_result.summary
    assert 0.0 <= summ.fulfilled_share <= 1.0 + 1e-9
    assert 0.0 <= summ.allowed_shortfall_share_actual <= 1.0 + 1e-9
    assert 0.0 <= summ.penalty_share_of_load <= 1.0 + 1e-9


def test_extract_results_revenue_breakdown_is_internally_consistent(solved_result):
    rev = solved_result.revenue
    expected_net = (
        rev.ppa_revenue + rev.excess_revenue - rev.market_purchase_cost
        - rev.penalty_cost - rev.transmission_cost
    )
    assert rev.net_revenue == pytest.approx(expected_net, rel=1e-6)


def test_extract_results_solver_status_recorded(solved_result):
    assert solved_result.solver_status == "ok"
    assert solved_result.solver_condition == "optimal"


def test_build_supply_mix_df_is_additive_to_total_generation(solved_result, tiny_ts):
    df = build_supply_mix_df(solved_result.dispatch, tiny_ts)
    stack_cols = ["Wind (direct)", "PV (direct)", "BESS discharge", "Buy from market"]
    stacked_total = df[stack_cols].sum(axis=1)

    d = solved_result.dispatch
    delivered_total = (d.wind_gen + d.pv_gen + d.bess_dispatch + d.market_buy - d.bess_store).values
    # Direct wind/PV (net of BESS charging) + BESS discharge + market buy should
    # reconstruct total supply net of battery charging, hour by hour.
    assert stacked_total.to_numpy() == pytest.approx(delivered_total, abs=1e-6)


def test_build_supply_mix_df_has_hour_column(solved_result, tiny_ts):
    df = build_supply_mix_df(solved_result.dispatch, tiny_ts)
    assert "hour" in df.columns
    assert set(df["hour"].unique()).issubset(set(range(24)))


def test_build_24h_avg_groups_by_hour_of_day(solved_result, tiny_ts):
    supply_mix = build_supply_mix_df(solved_result.dispatch, tiny_ts)
    avg = build_24h_avg(supply_mix)
    assert len(avg) == 24
    assert list(avg["hour"]) == list(range(24))


def test_build_ops_day_df_slices_chosen_day(solved_result, tiny_ts):
    chosen_day = str(tiny_ts.index[0].date())
    df = build_ops_day_df(solved_result.dispatch, chosen_day)
    assert len(df) > 0
    assert set(df.columns) == {
        "PPA delivery (MW)",
        "Sell to market (MW)",
        "Allowed shortfall (MW)",
        "Penalty (MW)",
        "BESS SoC (MWh)",
    }
