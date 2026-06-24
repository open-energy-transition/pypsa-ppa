"""Assemble a full-year hourly timeseries for one simulation year from cached CF + price data."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ppa.data.entsoe_client import escalate_prices, CACHE_DIR as ENTSOE_CACHE, DE_LU
from ppa.data.renewables_ninja import AVAILABLE_YEARS, CACHE_DIR as NINJA_CACHE
from ppa.industrial_profiles import get_load_series


def load_illustration_ts(
    year: int = 2023,
    lat: float = 51.5,
    lon: float = 10.0,
) -> pd.DataFrame | None:
    """Assemble a representative European hourly timeseries from cached data.

    Reads cached ENTSO-E German (DE-LU) day-ahead prices and renewables.ninja
    wind/solar capacity factors for ``year`` at ``lat``/``lon`` (central Germany
    by default) and returns a DataFrame with ``ts_MktPrice``, ``ts_WindGen`` and
    ``ts_PVGen`` on a common hourly index. Cache-only (no network); returns
    ``None`` if the required files are not present so callers can degrade
    gracefully."""
    price_file = Path(ENTSOE_CACHE) / f"da_prices_{DE_LU}_{year}.parquet"
    pv_file = Path(NINJA_CACHE) / f"pv_{lat:.2f}_{lon:.2f}_{year}.parquet"
    wind_file = Path(NINJA_CACHE) / f"wind_{lat:.2f}_{lon:.2f}_{year}.parquet"
    if not (price_file.exists() and pv_file.exists() and wind_file.exists()):
        return None

    price = pd.read_parquet(price_file)["price"]
    pv = pd.read_parquet(pv_file)["cf"]
    wind = pd.read_parquet(wind_file)["cf"]

    # Align all three on a clean hourly index for the year (positional align is
    # robust to small index/timezone differences between the two sources).
    n = min(len(price), len(pv), len(wind))
    index = pd.date_range(f"{year}-01-01", periods=n, freq="h")
    return pd.DataFrame(
        {
            "ts_MktPrice": price.to_numpy()[:n],
            "ts_WindGen": wind.to_numpy()[:n],
            "ts_PVGen": pv.to_numpy()[:n],
        },
        index=index,
    )


def build_year_timeseries(
    sim_year: int,
    weather_year: int,
    ppa_load_mw: float,
    pv_cf_by_year: dict[int, pd.Series],
    wind_cf_by_year: dict[int, pd.Series],
    prices_by_year: dict[int, pd.Series],
    price_escalation_rate: float,
    load_profile: str = "flat",
) -> pd.DataFrame:
    """
    Build a full-year hourly timeseries ready for build_network / solve.

    Both CF profiles and market prices are drawn from `weather_year` so that
    price–weather correlations are preserved (e.g. 2021: high prices + low wind).
    Prices are then escalated from that historical year to sim_year.
    """
    pv_cf = pv_cf_by_year[weather_year]
    wind_cf = wind_cf_by_year[weather_year]
    base_prices = prices_by_year[weather_year]

    # Build the canonical hourly index for this simulation year (UTC)
    year_index = pd.date_range(
        start=f"{sim_year}-01-01",
        periods=_hours_in_year(sim_year),
        freq="h",
        tz="UTC",
    )

    pv_series = _align_to_index(pv_cf, year_index, fill_value=0.0)
    wind_series = _align_to_index(wind_cf, year_index, fill_value=0.0)

    escalated = escalate_prices(base_prices, from_year=weather_year, to_year=sim_year, rate=price_escalation_rate)
    price_series = _align_to_index(escalated, year_index, fill_value=float(escalated.median()))

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
