from __future__ import annotations

import pandas as pd
import pytest

from ppa.data_loader import (
    find_default_csv,
    get_available_days,
    load_timeseries,
    prepare_timeseries,
)
from ppa.scenario import Scenario


def _write_csv(tmp_path, columns: dict):
    df = pd.DataFrame(columns)
    path = tmp_path / "ts.csv"
    df.to_csv(path, index=False)
    return path


def test_load_timeseries_raises_on_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_timeseries(tmp_path / "does_not_exist.csv")


def test_load_timeseries_raises_on_missing_columns(tmp_path):
    path = _write_csv(
        tmp_path, {"timestamp": ["2023-01-01 00:00:00"], "ts_PVGen": [0.1]}
    )
    with pytest.raises(ValueError, match="Missing required columns"):
        load_timeseries(path)


def test_load_timeseries_parses_and_sorts_by_timestamp(tmp_path):
    path = _write_csv(
        tmp_path,
        {
            "timestamp": ["2023-01-01 01:00:00", "2023-01-01 00:00:00"],
            "ts_PVGen": [0.2, 0.1],
            "ts_WindGen": [0.5, 0.4],
            "ts_NSWPrice": [60.0, 50.0],
        },
    )
    ts = load_timeseries(path)
    assert list(ts.index) == sorted(ts.index)
    assert ts.index.name == "snapshot"
    assert ts["ts_PVGen"].iloc[0] == 0.1  # the earlier timestamp, after sorting


def test_prepare_timeseries_maps_legacy_price_column():
    idx = pd.date_range("2023-01-01", periods=24, freq="h")
    ts = pd.DataFrame({"ts_NSWPrice": [50.0] * 24}, index=idx)
    scenario = Scenario(load_profile="flat", ppaload_mw=100.0)

    prepared = prepare_timeseries(ts, scenario)
    assert "ts_MktPrice" in prepared.columns
    assert (prepared["ts_MktPrice"] == 50.0).all()
    assert (prepared["ppaload_mw"] == 100.0).all()


def test_prepare_timeseries_keeps_existing_mkt_price_column():
    idx = pd.date_range("2023-01-01", periods=24, freq="h")
    ts = pd.DataFrame(
        {"ts_MktPrice": [70.0] * 24, "ts_NSWPrice": [999.0] * 24}, index=idx
    )
    scenario = Scenario(load_profile="flat", ppaload_mw=50.0)

    prepared = prepare_timeseries(ts, scenario)
    assert (prepared["ts_MktPrice"] == 70.0).all()  # not overwritten by legacy column


def test_prepare_timeseries_applies_load_profile_scaling():
    idx = pd.date_range("2023-01-01", periods=24, freq="h")
    ts = pd.DataFrame({"ts_MktPrice": [50.0] * 24}, index=idx)
    scenario = Scenario(load_profile="data_center", ppaload_mw=200.0)

    prepared = prepare_timeseries(ts, scenario)
    assert prepared["ppaload_mw"].max() <= 200.0 + 1e-9
    assert prepared["ppaload_mw"].max() > 0.0


def test_get_available_days_returns_sorted_unique_dates():
    idx = pd.date_range("2023-01-01", periods=48, freq="h")  # spans two calendar days
    ts = pd.DataFrame({"x": range(48)}, index=idx)
    days = get_available_days(ts)
    assert days == ["2023-01-01", "2023-01-02"]


def test_find_default_csv_returns_none_or_existing_path():
    result = find_default_csv()
    assert result is None or result.exists()
