"""Sensitivity analysis helpers for the project-finance model.

All parameters here are pure financial-model inputs — no PyPSA re-run is
needed. Parameters that would require a new optimisation (capacities,
delivery share, BESS round-trip efficiency) are intentionally excluded.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

import pandas as pd

from ppa.financial_model import (
    EnergyInputs,
    ProjectFinanceInputs,
    ProjectFinanceResult,
    run_project_finance,
)


# ── Tornado parameter catalogue ────────────────────────────────────────────────

@dataclass(frozen=True)
class SensParam:
    """Specification of one sensitivity parameter."""
    label: str          # human-readable name for charts/tables
    field: str          # field name on ProjectFinanceInputs
    group: str          # grouping for display (CAPEX, OPEX, Debt, Revenue, …)
    pct: float = 25.0   # default ±% range around the base value
    fmt: str = ".2f"    # numeric format for display


# Full catalogue — ordered by group then impact
PARAMS: list[SensParam] = [
    # CAPEX
    SensParam("Wind build cost (€m/MW)",  "onsw_build_cost",   "CAPEX"),
    SensParam("Solar build cost (€m/MW)", "pv_build_cost",     "CAPEX"),
    SensParam("BESS build cost (€m/MWh)", "bess_build_cost",   "CAPEX"),
    # OPEX
    SensParam("Wind fixed O&M (€m/MW)",   "onsw_fixed_om",     "OPEX"),
    SensParam("Solar fixed O&M (€m/MW)",  "pv_fixed_om",       "OPEX"),
    SensParam("BESS fixed O&M (€m/MWh)",  "bess_fixed_om",     "OPEX"),
    SensParam("Ancillary cost (% rev)",   "ancillary_pct",     "OPEX"),
    # Revenue
    SensParam("PPA tariff (€/MWh)",       "ppa_tariff",        "Revenue"),
    SensParam("Penalty multiple (×)",     "penalty_multiple",  "Revenue", pct=30),
    SensParam("LGC / GO price (€/MWh)",   "lgc_price",         "Revenue", pct=50),
    # Indexation
    SensParam("PPA indexation (%/yr)",    "ppa_indexation",    "Indexation", pct=50),
    SensParam("Cost inflation (%/yr)",    "cost_inflation",    "Indexation", pct=50),
    SensParam("Solar price infl. (%/yr)", "solar_price_inflation",   "Indexation", pct=50),
    SensParam("Non-solar price infl. (%/yr)", "nonsolar_price_inflation", "Indexation", pct=50),
    # Debt & sizing
    SensParam("Debt rate (%)",            "debt_rate",         "Debt", pct=20),
    SensParam("Debt tenor (yrs)",         "debt_tenor",        "Debt", pct=20),
    SensParam("DSCR — contracted",        "dscr_contracted",   "Debt", pct=20),
    SensParam("DSCR — uncontracted",      "dscr_uncontracted", "Debt", pct=20),
    SensParam("Max gearing — contracted", "max_gearing_contracted",   "Debt", pct=15),
    SensParam("Max gearing — uncontracted", "max_gearing_uncontracted", "Debt", pct=20),
    # Tax & depreciation
    SensParam("Corporate tax rate",       "corp_tax_rate",     "Tax / Dep.", pct=25),
    SensParam("Book depreciation rate",   "book_depreciation_rate", "Tax / Dep.", pct=25),
    SensParam("Tax depreciation rate",    "tax_depreciation_rate",  "Tax / Dep.", pct=25),
    SensParam("WACC / discount rate",     "discount_rate",     "Tax / Dep.", pct=20),
]

PARAM_BY_FIELD: dict[str, SensParam] = {p.field: p for p in PARAMS}


# ── Core helpers ───────────────────────────────────────────────────────────────

def run_what_if(
    base_energy: EnergyInputs,
    base_finance: ProjectFinanceInputs,
    **overrides: Any,
) -> ProjectFinanceResult:
    """Run the financial model with *overrides* applied to *base_finance*.

    Keys of *overrides* must be valid field names on :class:`ProjectFinanceInputs`.
    No PyPSA re-run is required — only financial parameters are modified.
    """
    finance = dataclasses.replace(base_finance, **overrides)
    return run_project_finance(finance, base_energy)


@dataclass
class TornadoRow:
    param: str
    field: str
    group: str
    base_val: float
    low_val: float
    high_val: float
    low_metric: float
    high_metric: float

    @property
    def swing(self) -> float:
        return abs(self.high_metric - self.low_metric)


def run_tornado(
    base_energy: EnergyInputs,
    base_finance: ProjectFinanceInputs,
    params: list[SensParam] | None = None,
    metric: str = "project_irr",
) -> tuple[list[TornadoRow], float]:
    """Vary each parameter independently and collect *metric* at low and high.

    For each param the range is ``base_value ± param.pct%``.
    Returns ``(rows, base_metric)`` with rows sorted by swing descending.
    """
    if params is None:
        params = PARAMS

    base_result = run_project_finance(base_finance, base_energy)
    base_val = float(getattr(base_result, metric))

    rows: list[TornadoRow] = []
    for p in params:
        bv = float(getattr(base_finance, p.field))
        delta = bv * p.pct / 100.0
        lo = bv - delta
        hi = bv + delta
        # Integer fields (e.g. debt_tenor) must stay integers
        field_type = type(getattr(base_finance, p.field))
        if field_type is int:
            lo = max(int(round(lo)), 1)
            hi = int(round(hi))

        r_lo = run_what_if(base_energy, base_finance, **{p.field: lo})
        r_hi = run_what_if(base_energy, base_finance, **{p.field: hi})
        rows.append(TornadoRow(
            param=p.label,
            field=p.field,
            group=p.group,
            base_val=bv,
            low_val=lo,
            high_val=hi,
            low_metric=float(getattr(r_lo, metric)),
            high_metric=float(getattr(r_hi, metric)),
        ))

    rows.sort(key=lambda r: r.swing, reverse=True)
    return rows, base_val


def tornado_to_dataframe(rows: list[TornadoRow], base_val: float, metric: str) -> pd.DataFrame:
    """Tidy DataFrame suitable for display or export."""
    is_pct = metric in ("project_irr", "equity_irr", "gearing")
    scale = 100.0 if is_pct else 1.0
    unit = "%" if is_pct else ""
    records = []
    for r in rows:
        records.append({
            "Group": r.group,
            "Parameter": r.param,
            "Base": r.base_val,
            "Low (−)": r.low_val,
            "High (+)": r.high_val,
            f"Result @ low {unit}".strip(): r.low_metric * scale,
            f"Result @ high {unit}".strip(): r.high_metric * scale,
            f"Swing {unit}".strip(): r.swing * scale,
        })
    return pd.DataFrame(records)
