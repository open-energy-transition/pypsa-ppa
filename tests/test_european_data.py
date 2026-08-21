from __future__ import annotations

import pandas as pd
import pytest

from ppa.data.european_data import (
    _align_to_index,
    _hours_in_year,
    build_year_timeseries,
    load_illustration_ts,
    load_reference_month_ts,
    pick_weather_year,
)


def test_hours_in_year_leap_vs_common():
    assert _hours_in_year(2024) == 8784
    assert _hours_in_year(2025) == 8760


def test_pick_weather_year_cycles_over_available_years():
    years = [2019, 2020, 2021]
    assert pick_weather_year(0, years) == 2019
    assert pick_weather_year(2, years) == 2021
    assert pick_weather_year(3, years) == 2019  # wraps around


def test_align_to_index_truncates_longer_source():
    target = pd.date_range("2023-01-01", periods=5, freq="h")
    source = pd.Series(range(10), name="cf")
    aligned = _align_to_index(source, target, fill_value=0.0)
    assert list(aligned.values) == [0, 1, 2, 3, 4]
    assert aligned.index.equals(target)


def test_align_to_index_pads_shorter_source_by_tiling_last_day():
    target = pd.date_range("2023-01-01", periods=48, freq="h")  # 2 days
    source = pd.Series(range(24), name="cf")  # only 1 day
    aligned = _align_to_index(source, target, fill_value=0.0)
    assert len(aligned) == 48
    assert list(aligned.values[:24]) == list(range(24))
    # padded values are the tiled last day, not the fill_value
    assert list(aligned.values[24:]) == list(range(24))


def test_build_year_timeseries_produces_expected_columns_and_length():
    weather_year = 2020
    idx = pd.date_range(
        f"{weather_year}-01-01", periods=_hours_in_year(weather_year), freq="h"
    )
    pv_cf = pd.Series(0.3, index=idx)
    wind_cf = pd.Series(0.4, index=idx)
    prices = pd.Series(50.0, index=idx)

    ts = build_year_timeseries(
        sim_year=2025,
        weather_year=weather_year,
        ppa_load_mw=100.0,
        pv_cf_by_year={weather_year: pv_cf},
        wind_cf_by_year={weather_year: wind_cf},
        prices_by_year={weather_year: prices},
        price_escalation_rate=0.02,
        load_profile="flat",
    )

    assert list(ts.columns) == ["ts_PVGen", "ts_WindGen", "ts_MktPrice", "ppaload_mw"]
    assert len(ts) == _hours_in_year(2025)
    assert ts.index.tz is None  # PyPSA requires timezone-naive snapshots
    assert (ts["ts_PVGen"] == 0.3).all()
    assert (ts["ppaload_mw"] == 100.0).all()
    # Prices escalated 5 years at 2%
    assert ts["ts_MktPrice"].iloc[0] == pytest.approx(50.0 * 1.02**5)


def test_build_year_timeseries_applies_load_profile():
    weather_year = 2020
    idx = pd.date_range(
        f"{weather_year}-01-01", periods=_hours_in_year(weather_year), freq="h"
    )
    flat = pd.Series(0.5, index=idx)

    ts = build_year_timeseries(
        sim_year=2025,
        weather_year=weather_year,
        ppa_load_mw=100.0,
        pv_cf_by_year={weather_year: flat},
        wind_cf_by_year={weather_year: flat},
        prices_by_year={weather_year: flat},
        price_escalation_rate=0.0,
        load_profile="data_center",
    )
    assert ts["ppaload_mw"].max() <= 100.0 + 1e-9
    assert ts["ppaload_mw"].nunique() > 1  # data_center profile isn't flat


def test_load_illustration_ts_returns_none_when_cache_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("ppa.data.european_data.ENTSOE_CACHE", tmp_path / "entsoe")
    monkeypatch.setattr("ppa.data.european_data.NINJA_CACHE", tmp_path / "ninja")
    assert load_illustration_ts(year=2099) is None


def test_load_reference_month_ts_returns_none_when_cache_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("ppa.data.european_data.ENTSOE_CACHE", tmp_path / "entsoe")
    monkeypatch.setattr("ppa.data.european_data.NINJA_CACHE", tmp_path / "ninja")
    assert load_reference_month_ts(year=2099, month=3) is None


def test_load_illustration_ts_assembles_from_cache(tmp_path, monkeypatch):
    entsoe_dir = tmp_path / "entsoe"
    ninja_dir = tmp_path / "ninja"
    entsoe_dir.mkdir()
    ninja_dir.mkdir()
    monkeypatch.setattr("ppa.data.european_data.ENTSOE_CACHE", entsoe_dir)
    monkeypatch.setattr("ppa.data.european_data.NINJA_CACHE", ninja_dir)

    year = 2023
    lat, lon = 51.5, 10.0
    zone = "DE_LU"
    n = 24
    idx = pd.date_range(f"{year}-01-01", periods=n, freq="h")

    pd.Series(50.0, index=idx, name="price").to_frame().to_parquet(
        entsoe_dir / f"da_prices_{zone}_{year}.parquet"
    )
    pd.Series(0.3, index=idx, name="cf").to_frame().to_parquet(
        ninja_dir / f"pv_{lat:.2f}_{lon:.2f}_{year}.parquet"
    )
    pd.Series(0.4, index=idx, name="cf").to_frame().to_parquet(
        ninja_dir / f"wind_{lat:.2f}_{lon:.2f}_{year}.parquet"
    )

    ts = load_illustration_ts(year=year, lat=lat, lon=lon, zone=zone)
    assert ts is not None
    assert len(ts) == n
    assert (ts["ts_MktPrice"] == 50.0).all()
    assert (ts["ts_PVGen"] == 0.3).all()
    assert (ts["ts_WindGen"] == 0.4).all()
