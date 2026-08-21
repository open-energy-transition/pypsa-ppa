"""Tests for the user-uploadable custom timeseries CSV template (validation logic)."""
from __future__ import annotations

import calendar

import pandas as pd
import pytest

from ppa.data.custom_timeseries import (
    REQUIRED_COLUMNS,
    TEMPLATE_YEARS,
    TemplateValidationError,
    _hours_in_year,
    _year_index,
    parse_and_validate,
    template_to_csv_bytes,
)


def _valid_year_df(year: int, price: float = 50.0, pv: float = 0.3, wind: float = 0.4) -> pd.DataFrame:
    n = _hours_in_year(year)
    idx = _year_index(year)
    return pd.DataFrame(
        {
            "year": year,
            "hour_of_year": range(n),
            "timestamp_utc": idx.tz_localize(None).astype(str),
            "price_eur_mwh": price,
            "pv_capacity_factor": pv,
            "wind_capacity_factor": wind,
        }
    )


def test_hours_in_year_leap_vs_common():
    assert _hours_in_year(2020) == 8784  # leap year
    assert _hours_in_year(2021) == 8760


def test_template_years_is_intersection_of_price_and_cf_years():
    assert TEMPLATE_YEARS == sorted(TEMPLATE_YEARS)
    assert len(TEMPLATE_YEARS) > 0


def test_parse_and_validate_accepts_a_well_formed_template():
    year = TEMPLATE_YEARS[0]
    df = _valid_year_df(year)
    csv_bytes = template_to_csv_bytes(df)

    result = parse_and_validate(csv_bytes)
    assert set(result.keys()) == {"price", "pv_cf", "wind_cf"}
    assert year in result["price"]
    assert len(result["price"][year]) == _hours_in_year(year)
    assert (result["pv_cf"][year] == 0.3).all()


def test_parse_and_validate_rejects_missing_columns():
    df = _valid_year_df(TEMPLATE_YEARS[0]).drop(columns=["pv_capacity_factor"])
    with pytest.raises(TemplateValidationError):
        parse_and_validate(template_to_csv_bytes(df))


def test_parse_and_validate_rejects_empty_file():
    df = pd.DataFrame(columns=REQUIRED_COLUMNS)
    with pytest.raises(TemplateValidationError):
        parse_and_validate(template_to_csv_bytes(df))


def test_parse_and_validate_rejects_unsupported_year():
    bad_year = 1999
    df = _valid_year_df(bad_year)
    with pytest.raises(TemplateValidationError, match="not a supported weather year"):
        parse_and_validate(template_to_csv_bytes(df))


def test_parse_and_validate_rejects_missing_hours():
    year = TEMPLATE_YEARS[0]
    df = _valid_year_df(year).iloc[:-1]  # drop the last hour
    with pytest.raises(TemplateValidationError, match="expected exactly"):
        parse_and_validate(template_to_csv_bytes(df))


def test_parse_and_validate_rejects_duplicate_hours():
    year = TEMPLATE_YEARS[0]
    df = _valid_year_df(year)
    df.loc[1, "hour_of_year"] = 0  # duplicate the first hour
    with pytest.raises(TemplateValidationError, match="duplicate hour_of_year"):
        parse_and_validate(template_to_csv_bytes(df))


def test_parse_and_validate_rejects_out_of_range_capacity_factor():
    year = TEMPLATE_YEARS[0]
    df = _valid_year_df(year, pv=1.5)
    with pytest.raises(TemplateValidationError, match="PV capacity factor"):
        parse_and_validate(template_to_csv_bytes(df))


def test_parse_and_validate_rejects_non_numeric_price():
    year = TEMPLATE_YEARS[0]
    df = _valid_year_df(year)
    df["price_eur_mwh"] = df["price_eur_mwh"].astype(object)
    df.loc[0, "price_eur_mwh"] = "not-a-number"
    with pytest.raises(TemplateValidationError, match="price_eur_mwh"):
        parse_and_validate(template_to_csv_bytes(df))


def test_parse_and_validate_rejects_reordered_timestamps():
    year = TEMPLATE_YEARS[0]
    df = _valid_year_df(year)
    # Scramble timestamp_utc while keeping hour_of_year sequential/complete.
    df["timestamp_utc"] = df["timestamp_utc"].iloc[::-1].to_numpy()
    with pytest.raises(TemplateValidationError, match="timestamp_utc doesn't match"):
        parse_and_validate(template_to_csv_bytes(df))


def test_parse_and_validate_multiple_years_all_valid():
    years = TEMPLATE_YEARS[:2]
    df = pd.concat([_valid_year_df(y) for y in years], ignore_index=True)
    result = parse_and_validate(template_to_csv_bytes(df))
    assert set(result["price"].keys()) == set(years)


def test_parse_and_validate_reports_errors_for_all_bad_years_at_once():
    good_year, bad_year = TEMPLATE_YEARS[0], 1999
    df = pd.concat([_valid_year_df(good_year), _valid_year_df(bad_year)], ignore_index=True)
    with pytest.raises(TemplateValidationError) as excinfo:
        parse_and_validate(template_to_csv_bytes(df))
    assert str(bad_year) in str(excinfo.value)
