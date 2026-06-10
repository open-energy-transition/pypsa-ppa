from __future__ import annotations

import math
from dataclasses import dataclass, field

from scipy.optimize import brentq

from ppa.scenario import Scenario
from ppa.results import SummaryVolumes, RevenueBreakdown, OptimizationResult

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


# ── Multi-year financial analysis ─────────────────────────────────────────────


@dataclass
class YearlyFinancials:
    year: int
    ppa_revenue: float
    merch_revenue: float
    market_buy_cost: float
    penalty_cost: float
    net_revenue: float
    opex: float
    net_cashflow: float
    fulfilled_share: float
    wind_gen_mwh: float
    pv_gen_mwh: float


@dataclass
class MultiYearFinancialResult:
    capex: CapexBreakdown
    annual_opex: float

    yearly: list[YearlyFinancials] = field(default_factory=list)

    # Aggregate KPIs
    npv: float = 0.0
    irr: float = float("nan")
    lcoe: float = float("nan")
    simple_payback: float = float("inf")
    total_lifetime_revenue: float = 0.0
    total_lifetime_generation_mwh: float = 0.0

    # Running NPV series (index = year number 1..N, value = cumulative NPV)
    cumulative_npv: list[float] = field(default_factory=list)


def run_multi_year_financial_analysis(
    scenario: Scenario,
    year_results: list[OptimizationResult],
    first_sim_year: int = 2025,
) -> MultiYearFinancialResult:
    """
    Compute project-level financials from per-year LP results.

    Each year's revenue is computed from the actual optimised dispatch.
    CAPEX is invested at year 0; OPEX is charged each year.
    """
    s = scenario

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

    yearly: list[YearlyFinancials] = []
    cashflows: list[float] = [-capex_total]
    total_revenue = 0.0
    total_gen_mwh = 0.0

    for idx, res in enumerate(year_results):
        rev = res.revenue
        summ = res.summary
        net_rev = rev.net_revenue
        net_cf = net_rev - annual_opex

        yearly.append(
            YearlyFinancials(
                year=first_sim_year + idx,
                ppa_revenue=rev.ppa_revenue,
                merch_revenue=rev.excess_revenue,
                market_buy_cost=rev.market_purchase_cost,
                penalty_cost=rev.penalty_cost,
                net_revenue=net_rev,
                opex=annual_opex,
                net_cashflow=net_cf,
                fulfilled_share=summ.fulfilled_share,
                wind_gen_mwh=summ.wind_generation_mwh,
                pv_gen_mwh=summ.pv_generation_mwh,
            )
        )
        cashflows.append(net_cf)
        total_revenue += net_rev
        total_gen_mwh += summ.wind_generation_mwh + summ.pv_generation_mwh + summ.bess_dispatch_mwh

    # Extend cashflows to project_life_yrs if fewer years were simulated.
    # The average of the simulated years is used for the remaining periods so that
    # NPV/IRR always reflect the full project life regardless of simulation_years.
    n_sim = len(year_results)
    n_life = s.project_life_yrs
    if n_sim < n_life:
        avg_simulated_cf = sum(cashflows[1:]) / n_sim
        cashflows.extend([avg_simulated_cf] * (n_life - n_sim))

    # ── NPV ──────────────────────────────────────────────────────────────────
    def _npv(rate: float) -> float:
        return sum(cf / (1 + rate) ** t for t, cf in enumerate(cashflows))

    npv = _npv(s.discount_rate)

    try:
        irr = brentq(_npv, -0.99, 10.0)
    except ValueError:
        irr = float("nan")

    # ── LCOE (using WACC annuity over project life) ───────────────────────────
    annuity_wacc = (1 - (1 + s.discount_rate) ** -s.project_life_yrs) / s.discount_rate
    avg_annual_gen = total_gen_mwh / len(year_results) if year_results else 0.0
    lcoe = (
        (capex_total / annuity_wacc + annual_opex) / avg_annual_gen
        if avg_annual_gen > 0
        else float("nan")
    )

    # ── Simple payback ────────────────────────────────────────────────────────
    avg_cf = sum(c for c in cashflows[1:]) / len(cashflows[1:]) if len(cashflows) > 1 else 0.0
    simple_payback = capex_total / avg_cf if avg_cf > 0 else float("inf")

    # ── Cumulative NPV series ─────────────────────────────────────────────────
    cumulative_npv: list[float] = []
    running = -capex_total
    for t, cf in enumerate(cashflows[1:], start=1):
        running += cf / (1 + s.discount_rate) ** t
        cumulative_npv.append(running)

    return MultiYearFinancialResult(
        capex=capex,
        annual_opex=annual_opex,
        yearly=yearly,
        npv=npv,
        irr=irr,
        lcoe=lcoe,
        simple_payback=simple_payback,
        total_lifetime_revenue=total_revenue,
        total_lifetime_generation_mwh=total_gen_mwh,
        cumulative_npv=cumulative_npv,
    )
