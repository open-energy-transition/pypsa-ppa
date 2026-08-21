"""Data-download tests for renewables.ninja and ENTSO-E clients.

No real network calls: HTTP is mocked and the on-disk parquet cache is
exercised directly (via tmp_path), matching the project's caching contract.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from ppa.data import renewables_ninja as rn
from ppa.data import entsoe_client as ec


def _fake_ninja_csv(n_hours: int = 24, value: float = 0.42) -> bytes:
    lines = ["# some comment header", "# generated for testing"]
    lines.append("time,local_time,electricity")
    idx = pd.date_range("2020-01-01", periods=n_hours, freq="h")
    for ts in idx:
        lines.append(f"{ts.isoformat()},{ts.isoformat()},{value}")
    return "\n".join(lines).encode("utf-8")


# ── renewables_ninja ─────────────────────────────────────────────────────────


def test_parse_ninja_csv_strips_comments_and_clips_to_unit_interval():
    raw = _fake_ninja_csv(n_hours=5, value=1.5)  # out-of-range value must be clipped
    series = rn._parse_ninja_csv(raw)
    assert len(series) == 5
    assert (series == 1.0).all()  # clipped from 1.5 down to 1.0
    assert series.index.tz is not None


def test_download_pv_cf_uses_cache_when_present(tmp_path, monkeypatch):
    cache_dir = tmp_path / "ninja"
    cache_dir.mkdir()
    cache_file = cache_dir / f"pv_{rn.DEFAULT_LAT:.2f}_{rn.DEFAULT_LON:.2f}_2022.parquet"
    expected = pd.Series([0.1, 0.2, 0.3], name="cf")
    expected.to_frame().to_parquet(cache_file)

    mock_get = MagicMock(side_effect=AssertionError("should not hit the network on cache hit"))
    monkeypatch.setattr(rn.requests, "get", mock_get)

    series = rn.download_pv_cf(2022, token="unused", cache_dir=cache_dir)
    pd.testing.assert_series_equal(series, expected)
    mock_get.assert_not_called()


def test_download_pv_cf_fetches_and_caches_on_miss(tmp_path, monkeypatch):
    cache_dir = tmp_path / "ninja"
    raw = _fake_ninja_csv(n_hours=10, value=0.55)

    mock_response = MagicMock()
    mock_response.content = raw
    mock_response.raise_for_status = MagicMock()
    mock_get = MagicMock(return_value=mock_response)
    monkeypatch.setattr(rn.requests, "get", mock_get)

    series = rn.download_pv_cf(2022, token="secret-token", cache_dir=cache_dir)

    assert mock_get.called
    called_headers = mock_get.call_args.kwargs["headers"]
    assert called_headers == {"Authorization": "Token secret-token"}
    assert (series == 0.55).all()

    cache_file = cache_dir / f"pv_{rn.DEFAULT_LAT:.2f}_{rn.DEFAULT_LON:.2f}_2022.parquet"
    assert cache_file.exists()
    cached = pd.read_parquet(cache_file)["cf"]
    pd.testing.assert_series_equal(cached, series, check_names=False, check_freq=False)


def test_download_wind_cf_raises_on_http_error(tmp_path, monkeypatch):
    cache_dir = tmp_path / "ninja"
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = rn.requests.exceptions.HTTPError("boom")
    monkeypatch.setattr(rn.requests, "get", MagicMock(return_value=mock_response))

    with pytest.raises(rn.requests.exceptions.HTTPError):
        rn.download_wind_cf(2022, token="x", cache_dir=cache_dir)


def test_download_all_years_skips_sleep_for_cached_years(tmp_path, monkeypatch):
    cache_dir = tmp_path / "ninja"
    cache_dir.mkdir()
    for prefix in ("pv", "wind"):
        f = cache_dir / f"{prefix}_{rn.DEFAULT_LAT:.2f}_{rn.DEFAULT_LON:.2f}_2020.parquet"
        pd.Series([0.5], name="cf").to_frame().to_parquet(f)

    monkeypatch.setattr(rn.requests, "get", MagicMock(side_effect=AssertionError("no network")))
    sleep_mock = MagicMock()
    monkeypatch.setattr(rn.time, "sleep", sleep_mock)

    pv_by_year, wind_by_year = rn.download_all_years(
        token="x", years=[2020], cache_dir=cache_dir
    )
    assert set(pv_by_year) == {2020}
    assert set(wind_by_year) == {2020}
    sleep_mock.assert_not_called()


def test_list_cached_years_intersection(tmp_path):
    cache_dir = tmp_path / "ninja"
    cache_dir.mkdir()
    lat, lon = rn.DEFAULT_LAT, rn.DEFAULT_LON
    for year in (2018, 2019):
        pd.Series([0.1], name="cf").to_frame().to_parquet(
            cache_dir / f"pv_{lat:.2f}_{lon:.2f}_{year}.parquet"
        )
    for year in (2019, 2020):
        pd.Series([0.1], name="cf").to_frame().to_parquet(
            cache_dir / f"wind_{lat:.2f}_{lon:.2f}_{year}.parquet"
        )

    assert rn.list_cached_pv_years(lat, lon, cache_dir) == [2018, 2019]
    assert rn.list_cached_wind_years(lat, lon, cache_dir) == [2019, 2020]
    assert rn.list_cached_years(lat, lon, cache_dir) == [2019]


def test_list_cached_years_empty_when_dir_missing(tmp_path):
    missing = tmp_path / "does_not_exist"
    assert rn.list_cached_pv_years(cache_dir=missing) == []


# ── entsoe_client ────────────────────────────────────────────────────────────


def test_fetch_day_ahead_prices_uses_cache_when_present(tmp_path):
    cache_dir = tmp_path / "entsoe"
    cache_dir.mkdir()
    cache_file = cache_dir / f"da_prices_{ec.DE_LU}_2022.parquet"
    expected = pd.Series([40.0, 41.0, float("nan"), 43.0], name="price")
    expected.to_frame().to_parquet(cache_file)

    series = ec.fetch_day_ahead_prices(2022, token="unused", cache_dir=cache_dir)
    # NaNs are forward/backward filled on read.
    assert not series.isna().any()
    assert series.iloc[2] == pytest.approx(41.0)  # ffilled from the prior value


def test_fetch_day_ahead_prices_downloads_and_caches_on_miss(tmp_path, monkeypatch):
    cache_dir = tmp_path / "entsoe"

    fake_index = pd.date_range("2022-01-01", periods=8760, freq="h", tz="Europe/Berlin")
    fake_prices = pd.Series(50.0, index=fake_index)

    fake_client = MagicMock()
    fake_client.query_day_ahead_prices.return_value = fake_prices
    fake_client_cls = MagicMock(return_value=fake_client)
    monkeypatch.setattr("entsoe.EntsoePandasClient", fake_client_cls)

    series = ec.fetch_day_ahead_prices(2022, token="secret", cache_dir=cache_dir)

    fake_client_cls.assert_called_once_with(api_key="secret")
    assert (series == 50.0).all()
    assert (cache_dir / f"da_prices_{ec.DE_LU}_2022.parquet").exists()


def test_escalate_prices_compounds_correctly():
    base = pd.Series([100.0, 200.0])
    escalated = ec.escalate_prices(base, from_year=2020, to_year=2022, rate=0.10)
    expected_factor = 1.10 ** 2
    pd.testing.assert_series_equal(escalated, base * expected_factor)


def test_escalate_prices_same_year_is_identity():
    base = pd.Series([100.0, 200.0])
    escalated = ec.escalate_prices(base, from_year=2020, to_year=2020, rate=0.10)
    pd.testing.assert_series_equal(escalated, base)


def test_get_prices_for_sim_year_shifts_and_escalates():
    base_year = 2020
    base_prices = pd.Series(
        60.0, index=pd.date_range("2020-01-01", periods=8760, freq="h", tz="UTC")
    )
    result = ec.get_prices_for_sim_year(2025, base_prices, base_year, escalation_rate=0.02)
    assert result.index[0].year == 2025
    assert result.iloc[0] == pytest.approx(60.0 * 1.02 ** 5)


def test_list_cached_years_and_is_cached(tmp_path):
    cache_dir = tmp_path / "entsoe"
    cache_dir.mkdir()
    (cache_dir / f"da_prices_{ec.DE_LU}_2021.parquet").write_bytes(b"stub")
    assert ec.is_cached(2021, cache_dir=cache_dir)
    assert not ec.is_cached(2022, cache_dir=cache_dir)
    assert ec.list_cached_years(cache_dir=cache_dir) == [2021]
