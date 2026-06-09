"""Assemble a full-year hourly timeseries for one simulation year from cached CF + price data."""
from __future__ import annotations

import pandas as pd

from ppa.data.entsoe_client import get_prices_for_sim_year
from ppa.data.renewables_ninja import AVAILABLE_YEARS
from ppa.industrial_profiles import get_load_series


def build_year_timeseries(
    sim_year: int,
    weather_year: int,
    ppa_load_mw: float,
    pv_cf_by_year: dict[int, pd.Series],
    wind_cf_by_year: dict[int, pd.Series],
    base_prices: pd.Series,
    base_price_year: int,
    price_escalation_rate: float,
    load_profile: str = "flat",
) -> pd.DataFrame:
    """
    Build a full-year hourly timeseries ready for build_network / solve.

    The resulting DataFrame has a UTC DatetimeIndex named 'snapshot' and columns:
      ts_PVGen, ts_WindGen, ts_MktPrice, ppaload_mw
    """
    pv_cf = pv_cf_by_year[weather_year]
    wind_cf = wind_cf_by_year[weather_year]

    # Build the canonical hourly index for this simulation year (UTC)
    year_index = pd.date_range(
        start=f"{sim_year}-01-01",
        periods=_hours_in_year(sim_year),
        freq="h",
        tz="UTC",
    )

    pv_series = _align_to_index(pv_cf, year_index, fill_value=0.0)
    wind_series = _align_to_index(wind_cf, year_index, fill_value=0.0)

    prices = get_prices_for_sim_year(sim_year, base_prices, base_price_year, price_escalation_rate)
    price_series = _align_to_index(prices, year_index, fill_value=float(prices.median()))

    # PyPSA requires timezone-naive snapshots; strip UTC tz while keeping UTC semantics
    naive_index = year_index.tz_localize(None)

    profile = get_load_series(load_profile, naive_index)

    ts = pd.DataFrame(
        {
            "ts_PVGen": pv_series.values,
            "ts_WindGen": wind_series.values,
            "ts_MktPrice": price_series.values,
            "ppaload_mw": (profile * ppa_load_mw).values,
        },
        index=naive_index,
    )
    ts.index.name = "snapshot"
    return ts


def pick_weather_year(sim_year_idx: int, available_years: list[int]) -> int:
    """Cycle over available historical weather years for simulation year index (0-based)."""
    return available_years[sim_year_idx % len(available_years)]


def _hours_in_year(year: int) -> int:
    import calendar
    return 8784 if calendar.isleap(year) else 8760


def _align_to_index(series: pd.Series, target_index: pd.DatetimeIndex, fill_value: float) -> pd.Series:
    """
    Assign CF values positionally onto target_index (hour-of-year semantics, not calendar date).

    This is intentional: a 2018 CF profile assigned to a 2025 target index simply
    replays the same hourly weather pattern under a new set of timestamps.
    """
    import numpy as np

    n_src = len(series)
    n_tgt = len(target_index)

    if n_src >= n_tgt:
        values = series.values[:n_tgt]
    else:
        # Leap-year target but non-leap source: tile last 24 h to pad the extra day
        extra_len = n_tgt - n_src
        pad = np.tile(series.values[-24:], (extra_len // 24 + 1))[:extra_len]
        values = np.concatenate([series.values, pad])

    return pd.Series(values, index=target_index, name=series.name)
