from __future__ import annotations

import math
from dataclasses import dataclass

from scipy.optimize import brentq

from ppa.scenario import Scenario
from ppa.results import SummaryVolumes, RevenueBreakdown

HOURS_PER_YEAR = 8_760


@dataclass
class CapexBreakdown:
    capex_wind: float
    capex_pv: float
    capex_bess: float
    capex_total: float
    annual_opex: float


@dataclass
class FinancialResult:
    capex: CapexBreakdown
    scale_factor: float
    annual_gen_mwh: float
    annual_ppa_rev: float
    annual_merch_rev: float
    annual_buy_cost: float
    annual_net_rev: float
    annual_opex: float
    annual_cf: float
    lcoe: float
    simple_payback: float
    project_irr: float
    npv_at_wacc: float
    breakeven_ppa_price: float
    avg_merch_price: float
    avg_buy_price: float


def run_financial_analysis(
    scenario: Scenario,
    summary: SummaryVolumes,
    revenue: RevenueBreakdown,
    n_period_hours: int,
) -> FinancialResult:
    s = scenario
    scale = HOURS_PER_YEAR / n_period_hours

    # ── CAPEX / OPEX ──────────────────────────────────────────────────────────
    capex_wind = s.wind_capex_per_kw * s.onsw_mw * 1_000
    capex_pv = s.pv_capex_per_kw * s.pv_mw * 1_000
    capex_bess = s.bess_capex_per_kwh * s.effective_bess_mwh * 1_000
    capex_total = capex_wind + capex_pv + capex_bess
    annual_opex = capex_total * s.opex_rate

    capex = CapexBreakdown(
        capex_wind=capex_wind,
        capex_pv=capex_pv,
        capex_bess=capex_bess,
        capex_total=capex_total,
        annual_opex=annual_opex,
    )

    # ── Annualised volumes ─────────────────────────────────────────────────────
    annual_gen_mwh = (
        summary.wind_generation_mwh + summary.pv_generation_mwh + summary.bess_dispatch_mwh
    ) * scale
    annual_ppa_vol = summary.ppa_delivered_mwh * scale
    annual_merch_mwh = summary.sold_to_market_mwh * scale
    annual_buy_mwh = summary.market_buy_to_ppa_mwh * scale

    avg_merch_price = (
        revenue.excess_revenue / summary.sold_to_market_mwh
        if summary.sold_to_market_mwh > 0
        else 0.0
    )
    avg_buy_price = (
        revenue.market_purchase_cost / summary.market_buy_to_ppa_mwh
        if summary.market_buy_to_ppa_mwh > 0
        else 0.0
    )

    annual_ppa_rev = annual_ppa_vol * s.ppa_price
    annual_merch_rev = annual_merch_mwh * avg_merch_price
    annual_buy_cost = annual_buy_mwh * avg_buy_price
    annual_net_rev = annual_ppa_rev + annual_merch_rev - annual_buy_cost

    # ── LCOE ──────────────────────────────────────────────────────────────────
    annuity_wacc = (1 - (1 + s.discount_rate) ** -s.project_life_yrs) / s.discount_rate
    lcoe = (capex_total / annuity_wacc + annual_opex) / annual_gen_mwh if annual_gen_mwh > 0 else float("nan")

    # ── NPV / IRR ──────────────────────────────────────────────────────────────
    annual_cf = annual_net_rev - annual_opex
    cashflows = [-capex_total] + [annual_cf] * s.project_life_yrs

    def _npv(rate: float) -> float:
        return sum(cf / (1 + rate) ** t for t, cf in enumerate(cashflows))

    try:
        project_irr = brentq(_npv, -0.99, 10.0)
    except ValueError:
        project_irr = float("nan")

    simple_payback = capex_total / annual_cf if annual_cf > 0 else float("inf")
    npv_at_wacc = _npv(s.discount_rate)

    # ── Breakeven PPA price for target IRR ────────────────────────────────────
    annuity_target = (1 - (1 + s.target_irr) ** -s.project_life_yrs) / s.target_irr
    required_cf = capex_total / annuity_target
    required_rev = required_cf + annual_opex
    required_ppa_rev = required_rev - annual_merch_rev + annual_buy_cost
    breakeven_ppa_price = required_ppa_rev / annual_ppa_vol if annual_ppa_vol > 0 else float("nan")

    return FinancialResult(
        capex=capex,
        scale_factor=scale,
        annual_gen_mwh=annual_gen_mwh,
        annual_ppa_rev=annual_ppa_rev,
        annual_merch_rev=annual_merch_rev,
        annual_buy_cost=annual_buy_cost,
        annual_net_rev=annual_net_rev,
        annual_opex=annual_opex,
        annual_cf=annual_cf,
        lcoe=lcoe,
        simple_payback=simple_payback,
        project_irr=project_irr,
        npv_at_wacc=npv_at_wacc,
        breakeven_ppa_price=breakeven_ppa_price,
        avg_merch_price=avg_merch_price,
        avg_buy_price=avg_buy_price,
    )
