import numpy as np
import pandas as pd
import pytest

from ppa.industrial_profiles import PROFILE_KEYS, get_load_series


@pytest.fixture(scope="module")
def year_index() -> pd.DatetimeIndex:
    return pd.date_range("2023-01-01", periods=8760, freq="h")


@pytest.mark.parametrize("profile", PROFILE_KEYS)
def test_all_profiles_are_normalized_between_zero_and_one(profile, year_index):
    series = get_load_series(profile, year_index)
    assert len(series) == len(year_index)
    assert series.index.equals(year_index)
    assert (series >= 0.0).all()
    assert (series <= 1.0 + 1e-9).all()


_EXPECTED_PEAK = {
    "flat": 1.0,
    "cement_plant": 1.0,
    "steel_eaf": 1.0,
    "green_hydrogen": 1.0,
    "data_center": 1.0,
    "aluminum_smelter": 0.97,  # never reaches 1.0: capped by the near-baseload profile itself
}


@pytest.mark.parametrize("profile", PROFILE_KEYS)
def test_all_profiles_peak_at_their_expected_maximum(profile, year_index):
    series = get_load_series(profile, year_index)
    assert series.max() == pytest.approx(_EXPECTED_PEAK[profile], abs=1e-6)


def test_flat_profile_is_constant_one():
    idx = pd.date_range("2023-01-01", periods=24, freq="h")
    series = get_load_series("flat", idx)
    assert (series == 1.0).all()


def test_unknown_profile_falls_back_to_flat():
    idx = pd.date_range("2023-01-01", periods=24, freq="h")
    series = get_load_series("totally_unknown_profile", idx)
    assert (series == 1.0).all()


def test_ffe_profiles_repeat_seasonal_and_weekday_pattern(year_index):
    """Cement/steel loads come from a lookup by (month, dow, hour): the same
    (month, weekday, hour) triplet must always yield the same normalized load."""
    series = get_load_series("cement_plant", year_index)
    keys = pd.DataFrame(
        {"month": year_index.month, "dow": year_index.dayofweek, "hour": year_index.hour}
    )
    df = pd.DataFrame({"value": series.values, **keys})
    # For any triplet appearing more than once, all occurrences must match.
    grouped = df.groupby(["month", "dow", "hour"])["value"].nunique()
    assert (grouped == 1).all()


def test_green_hydrogen_weekend_boost_never_exceeds_one():
    idx = pd.date_range("2023-01-07", periods=7 * 24, freq="h")  # a full week incl. weekend
    series = get_load_series("green_hydrogen", idx)
    assert (series <= 1.0 + 1e-9).all()


def test_data_center_weekend_is_lower_than_weekday_at_same_hour():
    idx = pd.date_range("2023-01-02", periods=14 * 24, freq="h")  # Mon..following Sun x2
    series = get_load_series("data_center", idx)
    df = pd.DataFrame({"value": series.values, "hour": idx.hour, "dow": idx.dayofweek})
    weekday_noon = df[(df.hour == 12) & (df.dow < 5)]["value"].iloc[0]
    weekend_noon = df[(df.hour == 12) & (df.dow >= 5)]["value"].iloc[0]
    assert weekend_noon < weekday_noon


def test_aluminum_smelter_dips_only_during_anode_window():
    idx = pd.date_range("2023-01-01", periods=28 * 24, freq="h")
    series = get_load_series("aluminum_smelter", idx)
    day_of_year = idx.dayofyear
    hour = idx.hour
    anode_window = (day_of_year % 28 == 0) & (hour >= 2) & (hour < 6)
    assert np.all(series[anode_window].values == pytest.approx(0.78))
    assert np.all(series[~anode_window].values == pytest.approx(0.97))
