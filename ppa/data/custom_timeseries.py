"""Build/validate user-editable CSV templates for custom price & CF timeseries.

Lets users substitute their own day-ahead price / PV capacity-factor / wind
capacity-factor data for the historical weather years the app otherwise
downloads from ENTSO-E and renewables.ninja (see ``entsoe_client`` and
``renewables_ninja``). The template is a single long-format CSV covering all
supported weather years so it can be edited in a spreadsheet and re-uploaded
in one shot; any subset of years may be filled in, the rest keep using
downloaded/cached data.
"""

from __future__ import annotations

import calendar
import io

import pandas as pd

from ppa.data.entsoe_client import AVAILABLE_YEARS as _PRICE_YEARS
from ppa.data.renewables_ninja import AVAILABLE_YEARS as _CF_YEARS

# Weather years the rest of the app can cycle through (prices ∩ CF availability).
TEMPLATE_YEARS: list[int] = sorted(set(_PRICE_YEARS) & set(_CF_YEARS))

REQUIRED_COLUMNS = [
    "year",
    "hour_of_year",
    "timestamp_utc",
    "price_eur_mwh",
    "pv_capacity_factor",
    "wind_capacity_factor",
]


class TemplateValidationError(Exception):
    """Raised when an uploaded custom-timeseries CSV fails validation."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def _hours_in_year(year: int) -> int:
    return 8784 if calendar.isleap(year) else 8760


def _year_index(year: int) -> pd.DatetimeIndex:
    return pd.date_range(
        f"{year}-01-01", periods=_hours_in_year(year), freq="h", tz="UTC"
    )


def build_template(
    zone: str,
    pv_location: tuple[float, float],
    wind_location: tuple[float, float],
    years: list[int] | None = None,
) -> pd.DataFrame:
    """Build a long-format CSV template, pre-filled with cached data where available.

    Years with no cached data for a given series are left blank (NaN) for the
    user to fill in. Cache-only reads: never triggers a network download.
    """
    from ppa.data import renewables_ninja as rn
    from ppa.data.entsoe_client import (
        fetch_day_ahead_prices,
        list_cached_years as list_cached_price_years,
    )

    years = years or TEMPLATE_YEARS
    pv_lat, pv_lon = pv_location
    wind_lat, wind_lon = wind_location

    cached_price_years = set(list_cached_price_years(country_code=zone))
    cached_pv_years = set(rn.list_cached_pv_years(lat=pv_lat, lon=pv_lon))
    cached_wind_years = set(rn.list_cached_wind_years(lat=wind_lat, lon=wind_lon))

    frames = []
    for year in years:
        idx = _year_index(year)
        n_hours = len(idx)

        price = (
            fetch_day_ahead_prices(year, "", country_code=zone).reindex(idx).to_numpy()
            if year in cached_price_years
            else float("nan")
        )
        pv = (
            rn.download_pv_cf(year, "", lat=pv_lat, lon=pv_lon).reindex(idx).to_numpy()
            if year in cached_pv_years
            else float("nan")
        )
        wind = (
            rn.download_wind_cf(year, "", lat=wind_lat, lon=wind_lon)
            .reindex(idx)
            .to_numpy()
            if year in cached_wind_years
            else float("nan")
        )

        frames.append(
            pd.DataFrame(
                {
                    "year": year,
                    "hour_of_year": range(n_hours),
                    "timestamp_utc": idx.tz_localize(None).astype(str),
                    "price_eur_mwh": price,
                    "pv_capacity_factor": pv,
                    "wind_capacity_factor": wind,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def template_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def _validate_year(year: int, group: pd.DataFrame) -> list[str]:
    errors: list[str] = []

    if year not in TEMPLATE_YEARS:
        return [
            f"Year {year}: not a supported weather year (supported: {TEMPLATE_YEARS})."
        ]

    n_hours = _hours_in_year(year)
    expected_hours = set(range(n_hours))
    try:
        actual_hours = set(group["hour_of_year"].astype(int))
    except (ValueError, TypeError):
        return [f"Year {year}: hour_of_year column contains non-integer values."]

    if group["hour_of_year"].duplicated().any():
        errors.append(f"Year {year}: duplicate hour_of_year values found.")
    if actual_hours != expected_hours:
        missing = sorted(expected_hours - actual_hours)[:5]
        extra = sorted(actual_hours - expected_hours)[:5]
        detail = []
        if missing:
            detail.append(f"missing hour_of_year e.g. {missing}")
        if extra:
            detail.append(f"unexpected hour_of_year e.g. {extra}")
        errors.append(
            f"Year {year}: expected exactly {n_hours} hourly rows (0..{n_hours - 1}); "
            + "; ".join(detail)
        )
    if errors:
        return errors  # can't reliably check further without a clean row set

    group = group.sort_values("hour_of_year")
    idx = _year_index(year)
    expected_ts = idx.tz_localize(None).astype(str).to_numpy()
    actual_ts = group["timestamp_utc"].astype(str).to_numpy()
    if not (actual_ts == expected_ts).all():
        errors.append(
            f"Year {year}: timestamp_utc doesn't match the expected hourly sequence: "
            "don't edit or reorder the year/hour_of_year/timestamp_utc columns."
        )

    for col, lo, hi, label in [
        ("pv_capacity_factor", 0.0, 1.0, "PV capacity factor"),
        ("wind_capacity_factor", 0.0, 1.0, "wind capacity factor"),
    ]:
        values = pd.to_numeric(group[col], errors="coerce")
        if values.isna().any():
            errors.append(f"Year {year}: {label} has missing or non-numeric values.")
        elif ((values < lo) | (values > hi)).any():
            bad = values[(values < lo) | (values > hi)].iloc[0]
            errors.append(
                f"Year {year}: {label} must be between {lo} and {hi} (found {bad:.4g})."
            )

    price_values = pd.to_numeric(group["price_eur_mwh"], errors="coerce")
    if price_values.isna().any() or not price_values.apply(lambda v: v == v).all():
        errors.append(f"Year {year}: price_eur_mwh has missing or non-numeric values.")

    return errors


def parse_and_validate(csv_bytes: bytes) -> dict[str, dict[int, pd.Series]]:
    """Parse an uploaded custom-timeseries CSV and validate it strictly.

    Returns ``{"price": {year: Series}, "pv_cf": {year: Series}, "wind_cf": {year: Series}}``
    for the years present in the file. Raises ``TemplateValidationError`` (with a
    list of human-readable issues) if anything is missing, misaligned, or out of
    range: no partial results are applied on failure.
    """
    try:
        df = pd.read_csv(io.BytesIO(csv_bytes), sep=None, engine="python")
    except Exception as exc:
        raise TemplateValidationError([f"Could not parse CSV: {exc}"]) from exc

    missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_cols:
        raise TemplateValidationError([f"Missing required column(s): {missing_cols}"])

    if df.empty:
        raise TemplateValidationError(["The uploaded file has no data rows."])

    try:
        df["year"] = df["year"].astype(int)
    except (ValueError, TypeError):
        raise TemplateValidationError(
            ["The 'year' column contains non-integer values."]
        )

    errors: list[str] = []
    result: dict[str, dict[int, pd.Series]] = {"price": {}, "pv_cf": {}, "wind_cf": {}}

    for year, group in df.groupby("year"):
        year_errors = _validate_year(int(year), group)
        if year_errors:
            errors.extend(year_errors)
            continue

        idx = _year_index(int(year))
        group = group.sort_values("hour_of_year")
        result["price"][int(year)] = pd.Series(
            group["price_eur_mwh"].astype(float).to_numpy(), index=idx, name="price"
        )
        result["pv_cf"][int(year)] = pd.Series(
            group["pv_capacity_factor"].astype(float).to_numpy(), index=idx, name="cf"
        )
        result["wind_cf"][int(year)] = pd.Series(
            group["wind_capacity_factor"].astype(float).to_numpy(), index=idx, name="cf"
        )

    if errors:
        raise TemplateValidationError(errors)
    if not result["price"]:
        raise TemplateValidationError(
            ["No valid year rows found in the uploaded file."]
        )

    return result
