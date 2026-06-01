from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pypsa

from ppa.scenario import Scenario


@dataclass
class DispatchSeries:
    wind_gen: pd.Series
    pv_gen: pd.Series
    market_buy: pd.Series
    allowed_shortfall: pd.Series
    penalty_gen: pd.Series
    market_sell: pd.Series
    bess_dispatch: pd.Series
    bess_store: pd.Series
    soc: pd.Series
    ppa_delivery: pd.Series


@dataclass
class SummaryVolumes:
    total_load_mwh: float
    ppa_delivered_mwh: float
    renewable_and_storage_to_ppa_mwh: float
    market_buy_to_ppa_mwh: float
    allowed_shortfall_mwh: float
    penalty_mwh: float
    sold_to_market_mwh: float
    wind_generation_mwh: float
    pv_generation_mwh: float
    bess_dispatch_mwh: float
    bess_charge_mwh: float
    fulfilled_share: float
    allowed_shortfall_share_actual: float
    buy_share_of_ppa_delivery: float
    penalty_share_of_load: float


@dataclass
class RevenueBreakdown:
    ppa_revenue: float
    excess_revenue: float
    market_purchase_cost: float
    penalty_cost: float
    net_revenue: float
    effective_capture_price: float


@dataclass
class OptimizationResult:
    scenario: Scenario
    dispatch: DispatchSeries
    summary: SummaryVolumes
    revenue: RevenueBreakdown
    solver_status: str
    solver_condition: str
    n_period_hours: int


def extract_results(
    n: pypsa.Network,
    scenario: Scenario,
    ts: pd.DataFrame,
    solver_status: str,
    solver_condition: str,
) -> OptimizationResult:
    s = scenario

    # ── Dispatch series ───────────────────────────────────────────────────────
    wind_gen = n.generators_t.p["Gen_OnshoreWind"]
    pv_gen = n.generators_t.p["Gen_PV"]
    market_buy = n.generators_t.p["Gen_BuyFromMarket"]
    allowed_shortfall = n.generators_t.p["Gen_AllowedShortfall"]
    penalty_gen = n.generators_t.p["Gen_Penalty"]
    market_sell = n.generators_t.p["Gen_SellToMarket"]

    bess_dispatch = n.storage_units_t.p_dispatch["SU_BESS"]
    bess_store = n.storage_units_t.p_store["SU_BESS"]
    soc = n.storage_units_t.state_of_charge["SU_BESS"]

    # Links: p1 is negative when supplying to bus1 — negate for positive delivered MW
    ppa_delivery = -n.links_t.p1["IPPGen_to_PPAOfftake"]

    dispatch = DispatchSeries(
        wind_gen=wind_gen,
        pv_gen=pv_gen,
        market_buy=market_buy,
        allowed_shortfall=allowed_shortfall,
        penalty_gen=penalty_gen,
        market_sell=market_sell,
        bess_dispatch=bess_dispatch,
        bess_store=bess_store,
        soc=soc,
        ppa_delivery=ppa_delivery,
    )

    # ── Volumes ───────────────────────────────────────────────────────────────
    total_load_mwh = float(ts["ppaload_mw"].sum())
    ppa_delivered_mwh = float(ppa_delivery.sum())
    market_buy_to_ppa_mwh = float(market_buy.sum())
    renewable_and_storage_to_ppa_mwh = float((ppa_delivery - market_buy).clip(lower=0).sum())
    allowed_shortfall_mwh = float(allowed_shortfall.sum())
    penalty_mwh = float(penalty_gen.sum())
    sold_to_market_mwh = float(market_sell.sum())
    wind_generation_mwh = float(wind_gen.sum())
    pv_generation_mwh = float(pv_gen.sum())
    bess_dispatch_mwh = float(bess_dispatch.sum())
    bess_charge_mwh = float(bess_store.sum())

    fulfilled_share = ppa_delivered_mwh / total_load_mwh if total_load_mwh > 0 else 0.0
    allowed_shortfall_share_actual = allowed_shortfall_mwh / total_load_mwh if total_load_mwh > 0 else 0.0
    buy_share_of_ppa_delivery = (
        market_buy_to_ppa_mwh / ppa_delivered_mwh if ppa_delivered_mwh > 0 else 0.0
    )
    penalty_share_of_load = penalty_mwh / total_load_mwh if total_load_mwh > 0 else 0.0

    summary = SummaryVolumes(
        total_load_mwh=total_load_mwh,
        ppa_delivered_mwh=ppa_delivered_mwh,
        renewable_and_storage_to_ppa_mwh=renewable_and_storage_to_ppa_mwh,
        market_buy_to_ppa_mwh=market_buy_to_ppa_mwh,
        allowed_shortfall_mwh=allowed_shortfall_mwh,
        penalty_mwh=penalty_mwh,
        sold_to_market_mwh=sold_to_market_mwh,
        wind_generation_mwh=wind_generation_mwh,
        pv_generation_mwh=pv_generation_mwh,
        bess_dispatch_mwh=bess_dispatch_mwh,
        bess_charge_mwh=bess_charge_mwh,
        fulfilled_share=fulfilled_share,
        allowed_shortfall_share_actual=allowed_shortfall_share_actual,
        buy_share_of_ppa_delivery=buy_share_of_ppa_delivery,
        penalty_share_of_load=penalty_share_of_load,
    )

    # ── Revenue ───────────────────────────────────────────────────────────────
    ppa_revenue = ppa_delivered_mwh * s.ppa_price
    excess_revenue = float((market_sell * ts["ts_MktPrice"]).sum())
    market_purchase_cost = float((market_buy * ts["ts_MktPrice"]).sum())
    penalty_cost = penalty_mwh * s.penalty_price
    net_revenue = ppa_revenue + excess_revenue - market_purchase_cost - penalty_cost

    total_gen_mwh = wind_generation_mwh + pv_generation_mwh + bess_dispatch_mwh
    effective_capture_price = net_revenue / total_gen_mwh if total_gen_mwh > 0 else 0.0

    revenue = RevenueBreakdown(
        ppa_revenue=ppa_revenue,
        excess_revenue=excess_revenue,
        market_purchase_cost=market_purchase_cost,
        penalty_cost=penalty_cost,
        net_revenue=net_revenue,
        effective_capture_price=effective_capture_price,
    )

    return OptimizationResult(
        scenario=scenario,
        dispatch=dispatch,
        summary=summary,
        revenue=revenue,
        solver_status=solver_status,
        solver_condition=solver_condition,
        n_period_hours=len(ts),
    )


def build_supply_mix_df(dispatch: DispatchSeries, ts: pd.DataFrame) -> pd.DataFrame:
    pv_direct = dispatch.pv_gen - dispatch.bess_store
    df = pd.DataFrame(
        {
            "Wind": dispatch.wind_gen,
            "PV (direct)": pv_direct.clip(lower=0),
            "BESS discharge": dispatch.bess_dispatch,
            "Buy from market": dispatch.market_buy,
            "BESS charging": -dispatch.bess_store,
        },
        index=ts.index,
    )
    df["hour"] = df.index.hour
    return df


def build_24h_avg(supply_mix_df: pd.DataFrame) -> pd.DataFrame:
    return supply_mix_df.groupby("hour").mean().reset_index()


def build_ops_day_df(dispatch: DispatchSeries, chosen_day: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "PPA delivery (MW)": dispatch.ppa_delivery.loc[chosen_day].round(1),
            "Sell to market (MW)": dispatch.market_sell.loc[chosen_day].round(1),
            "Allowed shortfall (MW)": dispatch.allowed_shortfall.loc[chosen_day].round(1),
            "Penalty (MW)": dispatch.penalty_gen.loc[chosen_day].round(1),
            "BESS SoC (MWh)": dispatch.soc.loc[chosen_day].round(1),
        }
    )
