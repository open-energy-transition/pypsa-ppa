from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ppa.results import OptimizationResult
from ppa.scenario import Scenario


@dataclass
class CounterfactualResult:
    total_load_mwh: float

    # Period all-in costs ($)
    spot_cost: float
    cal_cost: float
    blended_cost: float
    ppa_offtaker_cost: float

    # Effective $/MWh for each strategy
    spot_avg_price: float
    cal_avg_price: float
    blended_avg_price: float
    ppa_effective_price: float

    # Savings relative to PPA (positive = that strategy is more expensive than PPA)
    ppa_saving_vs_spot: float
    ppa_saving_vs_blended: float

    # Hourly cumulative cost series (aligned to ts index, for time-series chart)
    cumulative_spot: pd.Series
    cumulative_ppa: pd.Series
    cumulative_cal: pd.Series


def compute_counterfactuals(
    ts: pd.DataFrame,
    scenario: Scenario,
    result: OptimizationResult,
) -> CounterfactualResult:
    """Compare PPA offtaker cost against spot-only and CAL Y+1 forward procurement.

    All strategies source the same flat load (scenario.ppaload_mw MW each hour).
    Costs are for the modelled period only (not annualised).
    """
    spot_price = ts["ts_MktPrice"]
    load_mw = scenario.ppaload_mw
    n_hours = len(ts)
    dt = 1.0  # hours per timestep (hourly data)
    total_load_mwh = load_mw * n_hours * dt

    # --- Spot-only ---
    hourly_spot_cost = spot_price * load_mw * dt
    spot_cost = float(hourly_spot_cost.sum())

    # --- CAL Y+1 fully hedged ---
    cal_cost = scenario.cal_forward_price * total_load_mwh

    # --- Blended (hedge_fraction at CAL Y+1, remainder at spot) ---
    # cal_hedge_fraction = 0 → pure spot; = 1 → fully CAL hedged
    blended_cost = (
        scenario.cal_hedge_fraction * cal_cost
        + (1.0 - scenario.cal_hedge_fraction) * spot_cost
    )

    # --- PPA (offtaker view) ---
    # Pay ppa_price for each MWh delivered; cover any undelivered load at real-time spot.
    ppa_delivery = result.dispatch.ppa_delivery  # hourly MW delivered by IPP
    undelivered = (load_mw - ppa_delivery).clip(lower=0.0)
    hourly_ppa_cost = (
        scenario.ppa_price * ppa_delivery * dt
        + spot_price * undelivered * dt
    )
    ppa_offtaker_cost = float(hourly_ppa_cost.sum())

    # --- Effective $/MWh ---
    spot_avg_price = spot_cost / total_load_mwh if total_load_mwh > 0 else 0.0
    blended_avg_price = blended_cost / total_load_mwh if total_load_mwh > 0 else 0.0
    ppa_effective_price = ppa_offtaker_cost / total_load_mwh if total_load_mwh > 0 else 0.0

    # --- Savings vs PPA (positive = that strategy costs more than PPA) ---
    ppa_saving_vs_spot = spot_cost - ppa_offtaker_cost
    ppa_saving_vs_blended = blended_cost - ppa_offtaker_cost

    # --- Cumulative cost series ---
    hourly_cal_cost = pd.Series(
        scenario.cal_forward_price * load_mw * dt, index=ts.index
    )
    cumulative_spot = hourly_spot_cost.cumsum()
    cumulative_ppa = hourly_ppa_cost.cumsum()
    cumulative_cal = hourly_cal_cost.cumsum()

    return CounterfactualResult(
        total_load_mwh=total_load_mwh,
        spot_cost=spot_cost,
        cal_cost=cal_cost,
        blended_cost=blended_cost,
        ppa_offtaker_cost=ppa_offtaker_cost,
        spot_avg_price=spot_avg_price,
        cal_avg_price=scenario.cal_forward_price,
        blended_avg_price=blended_avg_price,
        ppa_effective_price=ppa_effective_price,
        ppa_saving_vs_spot=ppa_saving_vs_spot,
        ppa_saving_vs_blended=ppa_saving_vs_blended,
        cumulative_spot=cumulative_spot,
        cumulative_ppa=cumulative_ppa,
        cumulative_cal=cumulative_cal,
    )
