"""Download and cache wind/solar capacity-factor profiles from renewables.ninja."""
from __future__ import annotations

import io
import time
from pathlib import Path

import pandas as pd
import requests

CACHE_DIR = Path(__file__).parent.parent.parent / "data" / "cache" / "renewables_ninja"
_BASE_URL = "https://www.renewables.ninja/api/data"

# Representative German location (central Germany, good mix of wind + solar)
DEFAULT_LAT = 51.5
DEFAULT_LON = 10.0

# Historical weather years to cycle over for multi-year simulations
AVAILABLE_YEARS = list(range(2018, 2024))  # 2018–2023


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Token {token}"}


def _parse_ninja_csv(raw: bytes) -> pd.Series:
    """Parse the renewables.ninja CSV response (has comment header lines starting with #).

    The API returns timestamps in UTC already (column name: 'time').
    Values are capacity factors in kW per kW_installed (i.e. 0–1).
    """
    text = raw.decode("utf-8")
    lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    df = pd.read_csv(io.StringIO("\n".join(lines)), parse_dates=["time"])
    df = df.set_index("time")
    df.index = pd.to_datetime(df.index, utc=True)
    series = df["electricity"].rename("cf")
    # Resample to ensure clean hourly UTC index (handles any duplicates)
    series = series.resample("h").mean()
    return series.clip(0.0, 1.0)


def download_pv_cf(
    year: int,
    token: str,
    lat: float = DEFAULT_LAT,
    lon: float = DEFAULT_LON,
    cache_dir: Path = CACHE_DIR,
) -> pd.Series:
    """Return hourly solar PV capacity factors for `year` (UTC index, 0–1)."""
    cache_file = cache_dir / f"pv_{lat:.2f}_{lon:.2f}_{year}.parquet"
    if cache_file.exists():
        return pd.read_parquet(cache_file)["cf"]

    params = {
        "lat": lat,
        "lon": lon,
        "date_from": f"{year}-01-01",
        "date_to": f"{year}-12-31",
        "dataset": "merra2",
        "capacity": 1,
        "system_loss": 0.1,
        "tracking": 0,
        "tilt": 35,
        "azim": 180,
        "format": "csv",
    }
    resp = requests.get(
        f"{_BASE_URL}/pv",
        params=params,
        headers=_auth_headers(token),
        timeout=60,
    )
    resp.raise_for_status()

    series = _parse_ninja_csv(resp.content)
    cache_dir.mkdir(parents=True, exist_ok=True)
    series.to_frame().to_parquet(cache_file)
    return series


def download_wind_cf(
    year: int,
    token: str,
    lat: float = DEFAULT_LAT,
    lon: float = DEFAULT_LON,
    cache_dir: Path = CACHE_DIR,
) -> pd.Series:
    """Return hourly onshore wind capacity factors for `year` (UTC index, 0–1)."""
    cache_file = cache_dir / f"wind_{lat:.2f}_{lon:.2f}_{year}.parquet"
    if cache_file.exists():
        return pd.read_parquet(cache_file)["cf"]

    params = {
        "lat": lat,
        "lon": lon,
        "date_from": f"{year}-01-01",
        "date_to": f"{year}-12-31",
        "dataset": "merra2",
        "capacity": 1,
        "height": 100,
        "turbine": "Vestas V90 2000",
        "format": "csv",
    }
    resp = requests.get(
        f"{_BASE_URL}/wind",
        params=params,
        headers=_auth_headers(token),
        timeout=60,
    )
    resp.raise_for_status()

    series = _parse_ninja_csv(resp.content)
    cache_dir.mkdir(parents=True, exist_ok=True)
    series.to_frame().to_parquet(cache_file)
    return series


def download_all_years(
    token: str,
    lat: float = DEFAULT_LAT,
    lon: float = DEFAULT_LON,
    years: list[int] | None = None,
    cache_dir: Path = CACHE_DIR,
    inter_request_delay: float = 2.0,
) -> tuple[dict[int, pd.Series], dict[int, pd.Series]]:
    """
    Download PV and wind CF profiles for all requested years.

    Returns (pv_by_year, wind_by_year) dicts mapping year → hourly CF Series.
    Adds a delay between requests to respect renewables.ninja rate limits.
    """
    if years is None:
        years = AVAILABLE_YEARS

    pv_by_year: dict[int, pd.Series] = {}
    wind_by_year: dict[int, pd.Series] = {}

    for year in years:
        pv_cached = (cache_dir / f"pv_{lat:.2f}_{lon:.2f}_{year}.parquet").exists()
        pv_by_year[year] = download_pv_cf(year, token, lat, lon, cache_dir)
        if not pv_cached:
            time.sleep(inter_request_delay)

        wind_cached = (cache_dir / f"wind_{lat:.2f}_{lon:.2f}_{year}.parquet").exists()
        wind_by_year[year] = download_wind_cf(year, token, lat, lon, cache_dir)
        if not wind_cached:
            time.sleep(inter_request_delay)

    return pv_by_year, wind_by_year


def list_cached_years(
    lat: float = DEFAULT_LAT,
    lon: float = DEFAULT_LON,
    cache_dir: Path = CACHE_DIR,
) -> list[int]:
    """Return years for which both PV and wind CF files are already cached."""
    if not cache_dir.exists():
        return []
    result = []
    for year in AVAILABLE_YEARS:
        pv_ok = (cache_dir / f"pv_{lat:.2f}_{lon:.2f}_{year}.parquet").exists()
        wind_ok = (cache_dir / f"wind_{lat:.2f}_{lon:.2f}_{year}.parquet").exists()
        if pv_ok and wind_ok:
            result.append(year)
    return sorted(result)
