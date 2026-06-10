"""Download European market and weather data for the active scenario location."""
from __future__ import annotations

import time

import pandas as pd
import streamlit as st

from ui import state


def _token_key(name: str) -> str:
    return f"_token_{name}"


def _get_token(name: str) -> str:
    return st.session_state.get(_token_key(name), "")


def _save_token(name: str, value: str) -> None:
    if value:
        st.session_state[_token_key(name)] = value


def render() -> None:
    st.title("📡 Download Data")
    st.markdown(
        "Download European market prices (ENTSO-E) and wind/solar capacity-factor profiles "
        "(renewables.ninja) for the location defined in your active scenario. "
        "Data is cached locally — downloads only happen once per location."
    )

    # ── Active location ───────────────────────────────────────────────────────
    scenario = state.get_scenario()
    if scenario is None:
        st.info("Define a scenario in the **Case Study & Simulation** tab first.")
        return

    lat, lon = scenario.lat, scenario.lon

    col_info, col_map = st.columns([2, 2])
    with col_info:
        st.subheader("Active scenario location")
        st.markdown(f"**{lat:.2f}°N, {lon:.2f}°E**")
        st.caption(
            "Change the location in the *Project Location* section of the scenario form "
            "(**Case Study Definition** → Customise parameters → Project Location)."
        )
    with col_map:
        st.map(pd.DataFrame({"lat": [lat], "lon": [lon]}), zoom=4)

    st.markdown("---")

    # ── API tokens ────────────────────────────────────────────────────────────
    st.subheader("API tokens")
    tc1, tc2 = st.columns(2)

    with tc1:
        st.markdown("**ENTSO-E Transparency Platform**")
        st.caption("Free — register at transparency.entsoe.eu")
        entsoe_token = st.text_input(
            "ENTSO-E token",
            value=_get_token("entsoe"),
            type="password",
            key="dd_entsoe_token",
            placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        )
        _save_token("entsoe", entsoe_token)

    with tc2:
        st.markdown("**Renewables.ninja**")
        st.caption("Free — register at renewables.ninja")
        ninja_token = st.text_input(
            "Renewables.ninja token",
            value=_get_token("ninja"),
            type="password",
            key="dd_ninja_token",
            placeholder="your-ninja-api-token",
        )
        _save_token("ninja", ninja_token)

    # ── Data status ───────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Cache status")

    from ppa.data.entsoe_client import list_cached_years as list_cached_price_years, AVAILABLE_YEARS as PRICE_YEARS
    from ppa.data.renewables_ninja import list_cached_years, AVAILABLE_YEARS

    cached_price_years = list_cached_price_years()
    missing_prices = [y for y in PRICE_YEARS if y not in cached_price_years]
    cached_cf_years = list_cached_years(lat=lat, lon=lon)
    missing_cf = [y for y in AVAILABLE_YEARS if y not in cached_cf_years]

    sc1, sc2 = st.columns(2)
    with sc1:
        st.markdown("**ENTSO-E day-ahead prices (DE-LU)**")
        if not missing_prices:
            st.success(f"All {len(PRICE_YEARS)} years cached ✓  ({', '.join(str(y) for y in cached_price_years)})")
        elif cached_price_years:
            st.warning(f"{len(cached_price_years)}/{len(PRICE_YEARS)} years cached. Missing: {missing_prices}")
        else:
            st.warning(f"No years cached. Will download: {PRICE_YEARS}")

    with sc2:
        st.markdown(f"**Renewables.ninja CF profiles** — ({lat:.2f}°N, {lon:.2f}°E)")
        if not missing_cf:
            st.success(f"All {len(AVAILABLE_YEARS)} years cached ✓  ({', '.join(str(y) for y in cached_cf_years)})")
        elif cached_cf_years:
            st.warning(f"{len(cached_cf_years)}/{len(AVAILABLE_YEARS)} years cached. Missing: {missing_cf}")
        else:
            st.warning(f"No years cached for this location. Will download: {AVAILABLE_YEARS}")

    # ── Download button ───────────────────────────────────────────────────────
    st.markdown("---")

    needs_download = bool(missing_prices) or bool(missing_cf)
    tokens_present = bool(entsoe_token) and bool(ninja_token)

    if not needs_download:
        st.success("All data already cached — nothing to download.")
        return

    if not tokens_present:
        st.info("Enter both API tokens above to enable downloading.")

    if st.button(
        "Download Data",
        type="primary",
        disabled=not tokens_present,
        key="dd_download",
        help="Downloads missing ENTSO-E prices and renewables.ninja CF profiles.",
    ):
        _do_download(entsoe_token, ninja_token, lat, lon, missing_prices, missing_cf)
        st.rerun()


def _do_download(
    entsoe_token: str,
    ninja_token: str,
    lat: float,
    lon: float,
    missing_price_years: list[int],
    missing_cf_years: list[int],
) -> None:
    total_steps = len(missing_price_years) + len(missing_cf_years) * 2
    done = 0
    bar = st.progress(0, text="Preparing…")

    # ENTSO-E prices — all missing years
    from ppa.data.entsoe_client import fetch_day_ahead_prices
    for year in missing_price_years:
        bar.progress(done / total_steps, text=f"Fetching {year} DE-LU day-ahead prices…")
        try:
            fetch_day_ahead_prices(year, entsoe_token)
            done += 1
            bar.progress(done / total_steps, text=f"ENTSO-E {year} prices downloaded ✓")
        except Exception as exc:
            st.error(f"ENTSO-E {year} download failed: {exc}")
            return

    # renewables.ninja CF profiles
    from ppa.data import renewables_ninja as rn
    for year in missing_cf_years:
        bar.progress(done / total_steps, text=f"Downloading solar PV CF for {year}…")
        try:
            rn.download_pv_cf(year, ninja_token, lat=lat, lon=lon)
        except Exception as exc:
            st.error(f"PV CF download failed for {year}: {exc}")
            return
        done += 1
        time.sleep(2)  # respect renewables.ninja rate limit

        bar.progress(done / total_steps, text=f"Downloading wind CF for {year}…")
        try:
            rn.download_wind_cf(year, ninja_token, lat=lat, lon=lon)
        except Exception as exc:
            st.error(f"Wind CF download failed for {year}: {exc}")
            return
        done += 1
        time.sleep(2)

    bar.progress(1.0, text="All data downloaded and cached ✓")
    st.success("Download complete. Cached at data/cache/")
