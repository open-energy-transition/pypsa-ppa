"""Levered project-finance model for renewable PPA portfolios.

This is a streamlined Python port of the detailed ``Aus247RE_FM`` Excel financial
model. It keeps the substance of a project-finance appraisal — multi-year build,
indexed revenue, DSCR-sculpted debt sizing across contracted/uncontracted
tranches, book & tax depreciation, income tax with loss carry-forward, and a
full set of returns (Project IRR via FCFF, Equity IRR via FCFE) — while dropping
the workbook's Australian-specific scenario-sweep tables, working-capital
schedule and other fluff that the model's own *Simplifications* sheet already
flags as out of scope.

The model is driven by two input objects:

* :class:`EnergyInputs` — the per-year energy results coming out of the PyPSA
  optimisation (generation, PPA vs. excess split by solar/non-solar hours,
  capture prices, …). Build these from an ``OptimizationResult`` with
  :func:`energy_inputs_from_result`.
* :class:`ProjectFinanceInputs` — all the financial assumptions (costs, debt,
  tax, depreciation, timing). Defaults are European 2024 benchmarks; every value
  is user-editable in the dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

try:  # optional — only needed by energy_inputs_from_result
    from ppa.results import OptimizationResult
except Exception:  # pragma: no cover
    OptimizationResult = object  # type: ignore

SOLAR_HOUR_START = 9   # inclusive — "solar hours" defined as 09:00–17:00
SOLAR_HOUR_END = 17    # exclusive


# ── Inputs ─────────────────────────────────────────────────────────────────


@dataclass
class EnergyInputs:
    """Annualised energy-model results consumed by the financial model.

    Volumes are GWh per operating year; prices are €/MWh. The split between
    *solar hours* (09–17) and *non-solar hours* preserves the price distinction
    in the source model (solar-heavy hours capture lower merchant prices)."""

    onsw_mw: float
    pv_mw: float
    bess_mw: float
    bess_mwh: float
    load_mw: float

    # During the PPA contract
    ppa_gwh: float                 # delivered to offtaker under the PPA
    excess_solar_gwh: float        # surplus sold to market, solar hours
    excess_nonsolar_gwh: float     # surplus sold to market, non-solar hours
    penalty_gwh: float             # undelivered volume incurring penalty

    # After the PPA expires — all generation is sold merchant
    total_solar_gwh: float         # total generation in solar hours
    total_nonsolar_gwh: float      # total generation in non-solar hours

    # Capture / purchase prices (real, €/MWh)
    sell_solar_price: float
    sell_nonsolar_price: float
    purchase_price: float = 0.0
    marketbuy_gwh: float = 0.0

    name: str = "PyPSA scenario"


@dataclass
class ProjectFinanceInputs:
    """All financial assumptions. Defaults are European 2024 benchmarks.

    Costs are expressed as €m per MW (or per MWh for BESS energy) to mirror the
    source model's units; the dashboard converts the familiar €/kW figures."""

    # ── Build cost (€m/MW, €m/MWh for BESS) ─────────────────────────────────
    onsw_build_cost: float = 1.20      # €m/MW   (1200 €/kW)
    pv_build_cost: float = 0.75        # €m/MW   (750 €/kW)
    bess_build_cost: float = 0.38      # €m/MWh  (380 €/kWh)

    # ── Connection cost ─────────────────────────────────────────────────────
    onsw_connection_cost: float = 0.10
    pv_connection_cost: float = 0.08
    bess_connection_cost: float = 0.05  # €m/MWh

    # ── Project development cost (devex) ────────────────────────────────────
    onsw_devex: float = 0.13           # €m/MW   (~10% of build)
    pv_devex: float = 0.083            # €m/MW
    bess_devex: float = 0.043          # €m/MWh

    # ── Fixed O&M (€m/MW p.a., €m/MWh p.a. for BESS) ────────────────────────
    onsw_fixed_om: float = 0.025
    pv_fixed_om: float = 0.010
    bess_fixed_om: float = 0.010       # €m/MWh
    ancillary_pct: float = 0.01        # % of revenue

    # ── Timing (years) ──────────────────────────────────────────────────────
    model_duration: int = 40
    development_start: int = 1
    onsw_dev_years: int = 3
    pv_dev_years: int = 3
    bess_dev_years: int = 2
    onsw_constr_years: int = 2
    pv_constr_years: int = 1
    bess_constr_years: int = 1
    operating_life: int = 30

    # ── Revenue ─────────────────────────────────────────────────────────────
    ppa_tenor: int = 15                # PPA contract length (years)
    ppa_tariff: float = 100.0          # €/MWh (base, pre-indexation)
    penalty_multiple: float = 1.5      # penalty tariff = multiple × PPA tariff
    lgc_price: float = 5.0             # €/MWh green-certificate revenue on excess

    # ── Indexation (% p.a.) ─────────────────────────────────────────────────
    indexation_offset_years: int = 2   # years of escalation already elapsed at period 1
    cost_inflation: float = 0.02
    ppa_indexation: float = 0.02
    solar_price_inflation: float = 0.01
    nonsolar_price_inflation: float = 0.02
    # Whether the model escalates merchant capture prices over the project life.
    # Turn OFF when the energy inputs already come from a multi-year simulation that
    # escalated market prices per year, so price growth is not double-counted.
    escalate_merchant_prices: bool = True

    # ── Project finance ─────────────────────────────────────────────────────
    debt_tenor: int = 15
    debt_rate: float = 0.065
    dscr_contracted: float = 1.35
    dscr_uncontracted: float = 2.40
    max_gearing_contracted: float = 0.80
    max_gearing_uncontracted: float = 0.50

    # ── Depreciation & tax ──────────────────────────────────────────────────
    book_depreciation_rate: float = 0.04
    tax_depreciation_rate: float = 0.10
    corp_tax_rate: float = 0.30

    # Discount rate used for NPV reporting (project WACC)
    discount_rate: float = 0.08

    @property
    def penalty_tariff(self) -> float:
        return self.ppa_tariff * self.penalty_multiple


def project_finance_inputs_from_scenario(scenario) -> "ProjectFinanceInputs":
    """Seed :class:`ProjectFinanceInputs` from a :class:`~ppa.scenario.Scenario`.

    Carries across the overlapping assumptions (costs, PPA terms, life, discount
    rate, escalation) so the financial tab starts aligned with the run that
    produced the energy results. Costs convert €/kW → €m/MW (and €/kWh → €m/MWh)."""
    s = scenario
    return ProjectFinanceInputs(
        onsw_build_cost=s.wind_capex_per_kw / 1000.0,
        pv_build_cost=s.pv_capex_per_kw / 1000.0,
        bess_build_cost=s.bess_capex_per_kwh / 1000.0,
        operating_life=s.project_life_yrs,
        ppa_tariff=s.ppa_price,
        penalty_multiple=s.pen_mult,
        cost_inflation=s.price_escalation_rate,
        ppa_indexation=s.price_escalation_rate,
        nonsolar_price_inflation=s.price_escalation_rate,
        discount_rate=s.discount_rate,
    )


# ── Results ────────────────────────────────────────────────────────────────


@dataclass
class ProjectFinanceResult:
    inputs: ProjectFinanceInputs
    energy: EnergyInputs

    # Headline KPIs
    project_irr: float
    equity_irr: float
    npv_project: float
    gearing: float
    total_capex: float            # €m, nominal incl. devex & IDC
    total_debt: float             # €m, incl. IDC
    total_equity: float           # €m
    min_dscr: float
    avg_dscr: float
    payback_years: float
    lcoe: float                   # €/MWh

    # Per-period schedules (length = model_duration); index 0 = period 1
    periods: np.ndarray = field(repr=False, default=None)  # type: ignore
    schedule: dict[str, np.ndarray] = field(repr=False, default_factory=dict)


# ── Energy interface ─────────────────────────────────────────────────────────


def energy_inputs_from_result(
    result: "OptimizationResult",
    *,
    annualise: bool = True,
) -> EnergyInputs:
    """Map a PyPSA ``OptimizationResult`` onto :class:`EnergyInputs`.

    Splits merchant volumes/prices by solar (09–17) vs. non-solar hours and
    annualises the period (scaling by 8760 / period-hours) so that the financial
    model always sees full operating years."""

    import pandas as pd  # local import keeps module importable without pandas

    s = result.scenario
    d = result.dispatch
    summ = result.summary
    prices = result.market_prices

    n_hours = result.n_period_hours
    scale = (8760.0 / n_hours) if (annualise and n_hours) else 1.0
    to_gwh = scale / 1000.0  # MWh → GWh with annualisation

    idx = d.wind_gen.index
    hour = pd.Series(idx.hour, index=idx)
    solar_mask = (hour >= SOLAR_HOUR_START) & (hour < SOLAR_HOUR_END)

    total_gen = d.wind_gen + d.pv_gen + d.bess_dispatch

    def _gwh(series, mask=None) -> float:
        ser = series if mask is None else series.where(mask, 0.0)
        return float(ser.sum()) * to_gwh

    # Merchant capture price by hour-bucket (revenue-weighted)
    def _price(mask) -> float:
        vol = float(d.market_sell.where(mask, 0.0).sum())
        rev = float((d.market_sell.where(mask, 0.0) * prices).sum())
        return rev / vol if vol > 0 else float((prices.where(mask, 0.0)).mean() or 0.0)

    sell_solar = _price(solar_mask)
    sell_nonsolar = _price(~solar_mask)

    buy_vol = float(d.market_buy.sum())
    buy_price = (
        float((d.market_buy * prices).sum()) / buy_vol if buy_vol > 0 else 0.0
    )

    return EnergyInputs(
        onsw_mw=s.onsw_mw,
        pv_mw=s.pv_mw,
        bess_mw=s.effective_bess_mw,
        bess_mwh=s.effective_bess_mwh,
        load_mw=s.ppaload_mw,
        ppa_gwh=summ.ppa_delivered_mwh * to_gwh,
        excess_solar_gwh=_gwh(d.market_sell, solar_mask),
        excess_nonsolar_gwh=_gwh(d.market_sell, ~solar_mask),
        penalty_gwh=summ.penalty_mwh * to_gwh,
        total_solar_gwh=_gwh(total_gen, solar_mask),
        total_nonsolar_gwh=_gwh(total_gen, ~solar_mask),
        sell_solar_price=sell_solar,
        sell_nonsolar_price=sell_nonsolar,
        purchase_price=buy_price,
        marketbuy_gwh=buy_vol * to_gwh,
        name=s.name,
    )


# ── Timeline helpers ──────────────────────────────────────────────────────────


def energy_inputs_from_results(results: list) -> EnergyInputs:
    """Average annualised energy inputs across several per-year results.

    The financial model runs one representative operating year escalated by
    indexation, so a multi-year PyPSA run is collapsed to its mean year here."""
    per_year = [energy_inputs_from_result(r) for r in results]
    if not per_year:
        raise ValueError("no results provided")
    n = len(per_year)

    def avg(attr: str) -> float:
        return sum(getattr(x, attr) for x in per_year) / n

    first = per_year[0]
    return EnergyInputs(
        onsw_mw=first.onsw_mw,
        pv_mw=first.pv_mw,
        bess_mw=first.bess_mw,
        bess_mwh=first.bess_mwh,
        load_mw=first.load_mw,
        ppa_gwh=avg("ppa_gwh"),
        excess_solar_gwh=avg("excess_solar_gwh"),
        excess_nonsolar_gwh=avg("excess_nonsolar_gwh"),
        penalty_gwh=avg("penalty_gwh"),
        total_solar_gwh=avg("total_solar_gwh"),
        total_nonsolar_gwh=avg("total_nonsolar_gwh"),
        sell_solar_price=avg("sell_solar_price"),
        sell_nonsolar_price=avg("sell_nonsolar_price"),
        purchase_price=avg("purchase_price"),
        marketbuy_gwh=avg("marketbuy_gwh"),
        name=first.name,
    )


@dataclass
class _Timeline:
    duration: int
    dev_end: int          # period at which the longest development finishes
    constr_end: int       # period at which construction finishes
    ops_start: int        # first operating period
    ops_end: int
    ppa_end: int
    debt_end: int

    def tech_dev(self, dev_years: int) -> tuple[int, int]:
        """Development periods for a tech (back-aligned to dev_end)."""
        return self.dev_end - dev_years + 1, self.dev_end

    def tech_constr(self, constr_years: int) -> tuple[int, int]:
        """Construction periods for a tech (back-aligned to constr_end)."""
        return self.constr_end - constr_years + 1, self.constr_end


def _build_timeline(p: ProjectFinanceInputs) -> _Timeline:
    max_dev = max(p.onsw_dev_years, p.pv_dev_years, p.bess_dev_years)
    max_constr = max(p.onsw_constr_years, p.pv_constr_years, p.bess_constr_years)
    dev_end = p.development_start + max_dev - 1
    constr_end = dev_end + max_constr
    ops_start = constr_end + 1
    ops_end = ops_start + p.operating_life - 1
    ppa_end = ops_start + p.ppa_tenor - 1
    debt_end = ops_start + p.debt_tenor - 1
    return _Timeline(p.model_duration, dev_end, constr_end, ops_start, ops_end, ppa_end, debt_end)


def _spread(total: float, first: int, last: int, n: int, mult: np.ndarray) -> np.ndarray:
    """Spread ``total`` evenly across periods [first, last] (1-based, inclusive),
    indexing each instalment by the cost-inflation multiplier ``mult``."""
    out = np.zeros(n)
    if last < first:
        return out
    per = total / (last - first + 1)
    for period in range(first, last + 1):
        out[period - 1] = per * mult[period - 1]
    return out


def _irr(cashflows: np.ndarray) -> float:
    """IRR via bisection on NPV (robust, no SciPy dependency)."""
    def npv(rate: float) -> float:
        t = np.arange(len(cashflows))
        return float(np.sum(cashflows / (1.0 + rate) ** t))

    if np.all(cashflows >= 0) or np.all(cashflows <= 0):
        return float("nan")
    lo, hi = -0.99, 10.0
    flo, fhi = npv(lo), npv(hi)
    if flo * fhi > 0:
        return float("nan")
    for _ in range(200):
        mid = (lo + hi) / 2
        fmid = npv(mid)
        if abs(fmid) < 1e-9:
            return mid
        if flo * fmid < 0:
            hi, fhi = mid, fmid
        else:
            lo, flo = mid, fmid
    return (lo + hi) / 2


def _npv(rate: float, cashflows: np.ndarray, offset: int = 0) -> float:
    t = np.arange(len(cashflows)) + offset
    return float(np.sum(cashflows / (1.0 + rate) ** t))


# ── Core engine ───────────────────────────────────────────────────────────────


def run_project_finance(
    p: ProjectFinanceInputs,
    e: EnergyInputs,
) -> ProjectFinanceResult:
    n = p.model_duration
    tl = _build_timeline(p)
    periods = np.arange(1, n + 1)

    def zeros() -> np.ndarray:
        return np.zeros(n)

    # ── Flags ────────────────────────────────────────────────────────────────
    ops_flag = ((periods >= tl.ops_start) & (periods <= tl.ops_end)).astype(float)
    ppa_flag = ((periods >= tl.ops_start) & (periods <= tl.ppa_end)).astype(float)
    nonppa_flag = ((periods > tl.ppa_end) & (periods <= tl.ops_end)).astype(float)
    debt_flag = ((periods >= tl.ops_start) & (periods <= tl.debt_end)).astype(float)

    # ── Indexation multipliers (compounded from indexation start) ────────────
    def index_mult(rate: float) -> np.ndarray:
        return (1.0 + rate) ** (periods + p.indexation_offset_years - 1)

    cost_idx = index_mult(p.cost_inflation)
    ppa_idx = index_mult(p.ppa_indexation)
    # Merchant price escalation is skipped when the energy inputs already embed
    # per-year price escalation (avoids double-counting). PPA / LGC / cost
    # indexation are owned by the financial model and always apply.
    if p.escalate_merchant_prices:
        solar_idx = index_mult(p.solar_price_inflation)
        nonsolar_idx = index_mult(p.nonsolar_price_inflation)
    else:
        solar_idx = np.ones(n)
        nonsolar_idx = np.ones(n)

    # ── Schedule 1: Capital spend ────────────────────────────────────────────
    onsw_devex_tot = p.onsw_devex * e.onsw_mw
    pv_devex_tot = p.pv_devex * e.pv_mw
    bess_devex_tot = p.bess_devex * e.bess_mwh
    onsw_capex_tot = (p.onsw_build_cost + p.onsw_connection_cost) * e.onsw_mw
    pv_capex_tot = (p.pv_build_cost + p.pv_connection_cost) * e.pv_mw
    bess_capex_tot = (p.bess_build_cost + p.bess_connection_cost) * e.bess_mwh

    df, dl = tl.tech_dev(p.onsw_dev_years)
    devex = _spread(onsw_devex_tot, df, dl, n, cost_idx)
    df, dl = tl.tech_dev(p.pv_dev_years)
    devex += _spread(pv_devex_tot, df, dl, n, cost_idx)
    df, dl = tl.tech_dev(p.bess_dev_years)
    devex += _spread(bess_devex_tot, df, dl, n, cost_idx)

    cf, cl = tl.tech_constr(p.onsw_constr_years)
    capex = _spread(onsw_capex_tot, cf, cl, n, cost_idx)
    cf, cl = tl.tech_constr(p.pv_constr_years)
    capex += _spread(pv_capex_tot, cf, cl, n, cost_idx)
    cf, cl = tl.tech_constr(p.bess_constr_years)
    capex += _spread(bess_capex_tot, cf, cl, n, cost_idx)

    total_capital_spend = devex + capex  # nominal, excl. IDC

    # ── Schedule 2: Generation, revenue, opex ────────────────────────────────
    ppa_tariff = p.ppa_tariff * ppa_idx
    penalty_tariff = p.penalty_tariff * ppa_idx
    merch_solar = e.sell_solar_price * solar_idx
    merch_nonsolar = e.sell_nonsolar_price * nonsolar_idx
    lgc = p.lgc_price * ppa_idx

    GWh = 1000.0  # GWh → MWh
    M = 1e6       # €/€m

    # PPA period revenue
    ppa_rev = ppa_flag * e.ppa_gwh * GWh * ppa_tariff / M
    penalty_cost = ppa_flag * e.penalty_gwh * GWh * penalty_tariff / M  # cost (positive €m)
    merch_solar_rev = ppa_flag * e.excess_solar_gwh * GWh * merch_solar / M
    merch_nonsolar_rev = ppa_flag * e.excess_nonsolar_gwh * GWh * merch_nonsolar / M
    lgc_rev = ppa_flag * (e.excess_solar_gwh + e.excess_nonsolar_gwh) * GWh * lgc / M

    # Post-PPA period — all generation sold merchant
    post_solar_rev = nonppa_flag * e.total_solar_gwh * GWh * merch_solar / M
    post_nonsolar_rev = nonppa_flag * e.total_nonsolar_gwh * GWh * merch_nonsolar / M
    post_lgc_rev = nonppa_flag * (e.total_solar_gwh + e.total_nonsolar_gwh) * GWh * lgc / M

    net_contracted_rev = ppa_rev - penalty_cost
    net_uncontracted_rev = (
        merch_solar_rev + merch_nonsolar_rev + lgc_rev
        + post_solar_rev + post_nonsolar_rev + post_lgc_rev
    )
    total_rev = net_contracted_rev + net_uncontracted_rev

    # Opex: fixed O&M (flat real) + ancillary (% of revenue)
    fixed_om = (
        p.onsw_fixed_om * e.onsw_mw
        + p.pv_fixed_om * e.pv_mw
        + p.bess_fixed_om * e.bess_mwh
    )
    opex = ops_flag * fixed_om + p.ancillary_pct * total_rev
    ebitda = total_rev - opex

    # ── Schedule 3: Debt sizing ──────────────────────────────────────────────
    # Opex allocated to tranches in proportion to revenue
    with np.errstate(divide="ignore", invalid="ignore"):
        contracted_frac = np.where(total_rev > 0, net_contracted_rev / total_rev, 0.0)
    contracted_opex = opex * contracted_frac
    uncontracted_opex = opex - contracted_opex

    cfads_contracted = net_contracted_rev - contracted_opex
    cfads_uncontracted = net_uncontracted_rev - uncontracted_opex

    # Target debt service = CFADS / DSCR, only during debt repayment window
    tgt_ds_contracted = debt_flag * cfads_contracted / p.dscr_contracted
    tgt_ds_uncontracted = debt_flag * cfads_uncontracted / p.dscr_uncontracted

    # Max debt by DSCR = NPV of target debt service discounted at debt rate to ops_start
    def npv_to_ops(series: np.ndarray) -> float:
        total = 0.0
        for period in range(tl.ops_start, tl.debt_end + 1):
            total += series[period - 1] / (1.0 + p.debt_rate) ** (period - tl.ops_start + 1)
        return total

    contracted_debt_cap = npv_to_ops(tgt_ds_contracted)
    uncontracted_debt_cap = npv_to_ops(tgt_ds_uncontracted)
    dscr_debt = contracted_debt_cap + uncontracted_debt_cap

    nominal_capex_total = float(total_capital_spend.sum())
    gearing_cap = p.max_gearing_contracted * nominal_capex_total

    # Total debt (pre-IDC target). IDC is added below via simple iteration.
    target_debt = min(gearing_cap, dscr_debt)

    # ── Funding & IDC ────────────────────────────────────────────────────────
    # Funding waterfall: equity funds development spend; at financial close (the
    # first construction period) debt is drawn and front-loaded — it refinances
    # the development spend and funds construction up to the debt limit, with
    # equity supplying the residual at the end. Front-loading debt makes interest
    # during construction (IDC) accrue from financial close; IDC is charged on the
    # closing balance (opening + drawdown) and capitalised at the operations
    # start. The pre-IDC debt limit is solved iteratively so drawdowns + IDC equal
    # the sized debt.
    max_constr = max(p.onsw_constr_years, p.pv_constr_years, p.bess_constr_years)
    fc_period = tl.constr_end - max_constr + 1  # financial close = first construction period
    cum_spend = np.cumsum(total_capital_spend)
    total_debt = target_debt

    debt_draw = zeros()
    idc = zeros()
    for _ in range(100):
        pre_idc_limit = max(total_debt - float(idc.sum()), 0.0)
        # Greedy front-loaded drawdown from financial close onward
        debt_draw = zeros()
        remaining = pre_idc_limit
        funded = 0.0
        for period in range(fc_period, tl.constr_end + 1):
            target = max(cum_spend[period - 1] - funded, 0.0)
            draw = min(target, remaining)
            debt_draw[period - 1] = draw
            funded += draw
            remaining -= draw
        # Roll balance forward; IDC charged on closing balance (opening + draw)
        bal = 0.0
        new_idc = zeros()
        for period in range(1, tl.ops_start):
            draw = debt_draw[period - 1]
            interest = (bal + draw) * p.debt_rate
            new_idc[period - 1] = interest
            bal += draw + interest
        if abs(float(new_idc.sum()) - float(idc.sum())) < 1e-9:
            idc = new_idc
            break
        idc = new_idc

    debt_at_ops = float(debt_draw.sum()) + float(idc.sum())

    # Equity funds devex + capex not covered by debt drawdown
    equity_spend = total_capital_spend - debt_draw
    total_equity = float(equity_spend.sum())
    total_funding = debt_at_ops + total_equity
    gearing = debt_at_ops / total_funding if total_funding > 0 else 0.0

    # ── Debt repayment schedule (sculpted to target debt service) ────────────
    # Split the drawn debt into contracted / uncontracted tranches by their caps.
    if dscr_debt > 0:
        contracted_debt = debt_at_ops * (contracted_debt_cap / dscr_debt)
    else:
        contracted_debt = debt_at_ops
    uncontracted_debt = debt_at_ops - contracted_debt

    def repay_tranche(opening: float, tgt_ds: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        bal = opening
        interest = zeros()
        repay = zeros()
        closing = zeros()
        for period in range(tl.ops_start, tl.debt_end + 1):
            i = period - 1
            intr = bal * p.debt_rate
            principal = max(tgt_ds[i] - intr, 0.0)
            principal = min(principal, bal)
            interest[i] = intr
            repay[i] = principal
            bal -= principal
            closing[i] = bal
        return interest, repay, closing

    int_c, rep_c, _ = repay_tranche(contracted_debt, tgt_ds_contracted)
    int_u, rep_u, _ = repay_tranche(uncontracted_debt, tgt_ds_uncontracted)
    interest_exp = int_c + int_u
    loan_repay = rep_c + rep_u

    # ── Schedule 4: Depreciation ─────────────────────────────────────────────
    book_base = nominal_capex_total + float(idc.sum())  # devex + capex + IDC capitalised
    tax_base = float(capex.sum())                       # capex only (devex expensed for tax)
    book_dep = ops_flag * min(1.0, 1.0) * book_base * p.book_depreciation_rate
    tax_dep = ops_flag * tax_base * p.tax_depreciation_rate
    # cap cumulative depreciation at the asset base
    book_dep = _cap_depreciation(book_dep, book_base)
    tax_dep = _cap_depreciation(tax_dep, tax_base)

    # ── Schedule 5: Income tax (with loss carry-forward) ─────────────────────
    pbt = ebitda - interest_exp - book_dep
    tax = zeros()
    carry = 0.0
    for i in range(n):
        gross_income = pbt[i] + book_dep[i]      # add back book dep
        taxable = gross_income - tax_dep[i]       # deduct tax dep
        taxable_after = taxable + carry
        if taxable_after < 0:
            carry = taxable_after
            tax[i] = 0.0
        else:
            carry = 0.0
            tax[i] = taxable_after * p.corp_tax_rate
    pat = pbt - tax

    # ── Returns ──────────────────────────────────────────────────────────────
    # FCFF = EBITDA − cash tax − total capital investment (devex + capex)
    fcff = ops_flag * (ebitda - tax) - total_capital_spend
    project_irr = _irr(fcff)
    npv_project = _npv(p.discount_rate, fcff)

    # FCFE = PAT + book dep − loan repayment − equity investment during build
    fcfe = ops_flag * (pat + book_dep - loan_repay) - equity_spend
    equity_irr = _irr(fcfe)

    # DSCR = CFADS / debt service (during repayment)
    debt_service = interest_exp + loan_repay
    cfads_total = cfads_contracted + cfads_uncontracted
    with np.errstate(divide="ignore", invalid="ignore"):
        dscr_series = np.where(debt_service > 1e-9, cfads_total / debt_service, np.nan)
    dscr_vals = dscr_series[(periods >= tl.ops_start) & (periods <= tl.debt_end)]
    dscr_vals = dscr_vals[~np.isnan(dscr_vals)]
    min_dscr = float(np.min(dscr_vals)) if len(dscr_vals) else float("nan")
    avg_dscr = float(np.mean(dscr_vals)) if len(dscr_vals) else float("nan")

    # Simple payback on FCFE (years from ops start to cumulative >= 0)
    payback = _payback(fcfe)

    # LCOE — annuitised capital + opex over generation
    annuity = (1 - (1 + p.discount_rate) ** -p.operating_life) / p.discount_rate
    annual_gen_mwh = (e.total_solar_gwh + e.total_nonsolar_gwh) * 1000.0
    lcoe = (
        (nominal_capex_total * M / annuity + fixed_om * M) / annual_gen_mwh
        if annual_gen_mwh > 0 else float("nan")
    )

    schedule = {
        "period": periods.astype(float),
        "ops_flag": ops_flag,
        "ppa_flag": ppa_flag,
        "devex": devex,
        "capex": capex,
        "total_capital_spend": total_capital_spend,
        "debt_draw": debt_draw,
        "idc": idc,
        "net_contracted_rev": net_contracted_rev,
        "net_uncontracted_rev": net_uncontracted_rev,
        "total_rev": total_rev,
        "opex": opex,
        "ebitda": ebitda,
        "interest": interest_exp,
        "loan_repay": loan_repay,
        "book_dep": book_dep,
        "tax_dep": tax_dep,
        "pbt": pbt,
        "tax": tax,
        "pat": pat,
        "cfads": cfads_total,
        "dscr": dscr_series,
        "fcff": fcff,
        "fcfe": fcfe,
    }

    return ProjectFinanceResult(
        inputs=p,
        energy=e,
        project_irr=project_irr,
        equity_irr=equity_irr,
        npv_project=npv_project,
        gearing=gearing,
        total_capex=nominal_capex_total + float(idc.sum()),
        total_debt=debt_at_ops,
        total_equity=total_equity,
        min_dscr=min_dscr,
        avg_dscr=avg_dscr,
        payback_years=payback,
        lcoe=lcoe,
        periods=periods,
        schedule=schedule,
    )


def _cap_depreciation(dep: np.ndarray, base: float) -> np.ndarray:
    """Limit cumulative straight-line depreciation to the asset base."""
    out = dep.copy()
    cum = 0.0
    for i in range(len(out)):
        if cum + out[i] > base:
            out[i] = max(base - cum, 0.0)
        cum += out[i]
    return out


def _payback(fcfe: np.ndarray) -> float:
    """Years until cumulative equity cash flow turns — and stays — positive.

    Uses the *last* sign change so that transient swings during construction
    (e.g. development costs refinanced by debt at financial close) don't produce
    a spuriously short payback."""
    cum = np.cumsum(fcfe)
    crossing = None
    for i in range(1, len(cum)):
        if cum[i] >= 0 and cum[i - 1] < 0:
            prev = cum[i - 1]
            frac = (-prev) / (cum[i] - prev) if cum[i] != prev else 0.0
            crossing = i + frac  # 1-based period of the (latest) crossing
    return float(crossing) if crossing is not None else float("inf")
