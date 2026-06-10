"""Fetch and cache German day-ahead prices from ENTSO-E Transparency Platform."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

CACHE_DIR = Path(__file__).parent.parent.parent / "data" / "cache" / "entsoe"
DE_LU = "DE_LU"

# Historical years available — matches renewables.ninja CF range
AVAILABLE_YEARS: list[int] = [2018, 2019, 2020, 2021, 2022, 2023]


def fetch_day_ahead_prices(
    year: int,
    token: str,
    country_code: str = DE_LU,
    cache_dir: Path = CACHE_DIR,
) -> pd.Series:
    """
    Return hourly day-ahead prices (€/MWh) for a full calendar year.

    Results are cached to disk as Parquet to avoid repeated API calls.
    The returned Series has a UTC DatetimeIndex.
    """
    cache_file = cache_dir / f"da_prices_{country_code}_{year}.parquet"
    if cache_file.exists():
        series = pd.read_parquet(cache_file)["price"]
        return series.ffill().bfill()

    from entsoe import EntsoePandasClient  # deferred to avoid import error when token absent

    client = EntsoePandasClient(api_key=token)
    start = pd.Timestamp(f"{year}-01-01", tz="Europe/Berlin")
    end = pd.Timestamp(f"{year+1}-01-01", tz="Europe/Berlin")

    prices = client.query_day_ahead_prices(country_code, start=start, end=end)
    prices.index = prices.index.tz_convert("UTC")
    prices = prices.resample("h").mean()
    prices = prices.ffill().bfill()  # fill any DST-gap NaN
    prices.name = "price"

    cache_dir.mkdir(parents=True, exist_ok=True)
    prices.to_frame().to_parquet(cache_file)
    return prices


def escalate_prices(
    base_prices: pd.Series,
    from_year: int,
    to_year: int,
    rate: float,
) -> pd.Series:
    """Apply compound annual price escalation from `from_year` to `to_year`."""
    factor = (1.0 + rate) ** (to_year - from_year)
    return base_prices * factor


def get_prices_for_sim_year(
    sim_year: int,
    base_prices: pd.Series,
    base_year: int,
    escalation_rate: float,
) -> pd.Series:
    """
    Return market prices for a given simulation year.

    Uses the 2024 hourly price *shape* with dates shifted to sim_year,
    then applies compound escalation from base_year.
    """
    # Shift timestamps: replace year in index while preserving hourly shape
    shifted = _shift_to_year(base_prices, sim_year)
    return escalate_prices(shifted, base_year, sim_year, escalation_rate)


def _shift_to_year(prices: pd.Series, target_year: int) -> pd.Series:
    """Re-index a full-year price series onto target_year keeping hourly shape."""
    # Build a target index covering target_year at hourly resolution in UTC
    target_index = pd.date_range(
        start=f"{target_year}-01-01",
        end=f"{target_year+1}-01-01",
        freq="h",
        tz="UTC",
        inclusive="left",
    )
    # Map by day-of-year + hour to handle different year lengths gracefully
    # Easiest: just assign the values positionally, trimming/padding if leap year differs
    n = min(len(prices), len(target_index))
    result = pd.Series(prices.values[:n], index=target_index[:n], name=prices.name)
    if len(target_index) > n:
        # Leap year target but non-leap source: repeat last day
        pad = pd.Series(
            [prices.values[-1]] * (len(target_index) - n),
            index=target_index[n:],
            name=prices.name,
        )
        result = pd.concat([result, pad])
    return result


def list_cached_years(country_code: str = DE_LU, cache_dir: Path = CACHE_DIR) -> list[int]:
    return sorted(
        y for y in AVAILABLE_YEARS
        if (cache_dir / f"da_prices_{country_code}_{y}.parquet").exists()
    )


def is_cached(year: int, country_code: str = DE_LU, cache_dir: Path = CACHE_DIR) -> bool:
    return (cache_dir / f"da_prices_{country_code}_{year}.parquet").exists()
