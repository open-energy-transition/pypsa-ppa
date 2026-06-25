"""Sensitivity analysis helpers for the project-finance model.

Scales EnergyInputs proportionally to capacity changes and rebalances
PPA/merchant split for a revised delivery share, without re-running the
PyPSA optimisation. Suitable for directional sensitivity analysis.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import pandas as pd

from ppa.financial_model import (
    EnergyInputs,
    ProjectFinanceInputs,
    ProjectFinanceResult,
    run_project_finance,
)

_HOURS_PER_YEAR = 8760.0


def scale_energy_inputs(
    base: EnergyInputs,
    *,
    wind_mw: float | None = None,
    solar_mw: float | None = None,
    bess_mw: float | None = None,
    delivery_share: float | None = None,
) -> EnergyInputs:
    """Return a proportionally scaled copy of *base* for sensitivity analysis.

    Generation volumes scale with the total generation capacity ratio
    (wind + solar). BESS scales its own capacity/energy without affecting
    net generation volumes — it shifts timing, not total energy. Delivery
    share re-balances ppa_gwh against excess while holding total dispatched
    generation constant.
    """
    new_wind = wind_mw if wind_mw is not None else base.onsw_mw
    new_solar = solar_mw if solar_mw is not None else base.pv_mw
    new_bess = bess_mw if bess_mw is not None else base.bess_mw

    orig_gen = base.onsw_mw + base.pv_mw
    new_gen = new_wind + new_solar
    gen_scale = (new_gen / orig_gen) if orig_gen > 0 else 1.0

    ppa_gwh = base.ppa_gwh * gen_scale
    excess_solar = base.excess_solar_gwh * gen_scale
    excess_nonsolar = base.excess_nonsolar_gwh * gen_scale
    penalty_gwh = base.penalty_gwh * gen_scale
    total_solar = base.total_solar_gwh * gen_scale
    total_nonsolar = base.total_nonsolar_gwh * gen_scale
    marketbuy = base.marketbuy_gwh * gen_scale

    bess_ratio = (new_bess / base.bess_mw) if base.bess_mw > 0 else 1.0
    new_bess_mwh = base.bess_mwh * bess_ratio

    if delivery_share is not None:
        # Total dispatched generation available for PPA delivery or merchant sale
        total_available = ppa_gwh + excess_solar + excess_nonsolar
        new_obligation = base.load_mw * delivery_share * _HOURS_PER_YEAR / 1000.0

        new_ppa = min(new_obligation, total_available)
        penalty_gwh = max(0.0, new_obligation - total_available)
        new_excess = total_available - new_ppa

        old_excess = excess_solar + excess_nonsolar
        solar_frac = (excess_solar / old_excess) if old_excess > 0 else 0.5
        excess_solar = new_excess * solar_frac
        excess_nonsolar = new_excess * (1.0 - solar_frac)
        ppa_gwh = new_ppa

    return EnergyInputs(
        onsw_mw=new_wind,
        pv_mw=new_solar,
        bess_mw=new_bess,
        bess_mwh=new_bess_mwh,
        load_mw=base.load_mw,
        ppa_gwh=ppa_gwh,
        excess_solar_gwh=excess_solar,
        excess_nonsolar_gwh=excess_nonsolar,
        penalty_gwh=penalty_gwh,
        total_solar_gwh=total_solar,
        total_nonsolar_gwh=total_nonsolar,
        sell_solar_price=base.sell_solar_price,
        sell_nonsolar_price=base.sell_nonsolar_price,
        purchase_price=base.purchase_price,
        marketbuy_gwh=marketbuy,
        name=base.name,
    )


def implied_delivery_share(energy: EnergyInputs) -> float:
    """Derive the delivery share implied by *energy* (ppa + penalty vs. load obligation).

    Returns a value in [0, 1], clamped if the optimiser over-delivered or the
    load_mw field is zero.
    """
    if energy.load_mw <= 0:
        return 0.75
    annual_load = energy.load_mw * _HOURS_PER_YEAR / 1000.0
    share = (energy.ppa_gwh + energy.penalty_gwh) / annual_load
    return float(min(max(share, 0.0), 1.0))


def run_what_if(
    base_energy: EnergyInputs,
    base_finance: ProjectFinanceInputs,
    *,
    wind_mw: float | None = None,
    solar_mw: float | None = None,
    bess_mw: float | None = None,
    delivery_share: float | None = None,
    ppa_tariff: float | None = None,
) -> ProjectFinanceResult:
    """Financial model run for one sensitivity scenario."""
    energy = scale_energy_inputs(
        base_energy,
        wind_mw=wind_mw,
        solar_mw=solar_mw,
        bess_mw=bess_mw,
        delivery_share=delivery_share,
    )
    finance = base_finance
    if ppa_tariff is not None:
        finance = dataclasses.replace(finance, ppa_tariff=ppa_tariff)
    return run_project_finance(finance, energy)


@dataclass
class TornadoRow:
    param: str
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
    *,
    wind_range: tuple[float, float] | None = None,
    solar_range: tuple[float, float] | None = None,
    bess_range: tuple[float, float] | None = None,
    delivery_range: tuple[float, float] | None = None,
    tariff_range: tuple[float, float] | None = None,
    metric: str = "project_irr",
) -> tuple[list[TornadoRow], float]:
    """Vary each parameter independently and collect *metric* at low and high.

    Returns ``(rows, base_metric)`` with rows sorted by swing (largest first).
    """
    base_result = run_project_finance(base_finance, base_energy)
    base_val = float(getattr(base_result, metric))

    specs = [
        ("Wind capacity (MW)", "wind_mw", wind_range),
        ("Solar capacity (MW)", "solar_mw", solar_range),
        ("BESS capacity (MW)", "bess_mw", bess_range),
        ("Delivery share", "delivery_share", delivery_range),
        ("PPA tariff (€/MWh)", "ppa_tariff", tariff_range),
    ]

    rows: list[TornadoRow] = []
    for label, kwarg, rng in specs:
        if rng is None:
            continue
        lo, hi = rng
        r_lo = run_what_if(base_energy, base_finance, **{kwarg: lo})
        r_hi = run_what_if(base_energy, base_finance, **{kwarg: hi})
        rows.append(TornadoRow(
            param=label,
            low_val=lo,
            high_val=hi,
            low_metric=float(getattr(r_lo, metric)),
            high_metric=float(getattr(r_hi, metric)),
        ))

    rows.sort(key=lambda r: r.swing, reverse=True)
    return rows, base_val


def tornado_to_dataframe(rows: list[TornadoRow], base_val: float, metric: str = "project_irr") -> pd.DataFrame:
    """Convert tornado rows to a tidy DataFrame for charting or display."""
    is_pct = metric in ("project_irr", "equity_irr", "gearing")
    scale = 100.0 if is_pct else 1.0
    records = []
    for r in rows:
        records.append({
            "Parameter": r.param,
            "Low value": r.low_val,
            "High value": r.high_val,
            "Low result": r.low_metric * scale,
            "High result": r.high_metric * scale,
            "Swing (pp)" if is_pct else "Swing": r.swing * scale,
        })
    return pd.DataFrame(records)
