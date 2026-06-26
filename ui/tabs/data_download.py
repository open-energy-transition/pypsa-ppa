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
        "Download market prices and wind/solar hourly profiles for the location defined in "
        "your active scenario. Data is cached locally — downloads only happen once per location."
    )

    # ── Active location ───────────────────────────────────────────────────────
    scenario = state.get_scenario()
    if scenario is None:
        st.info("Define a scenario in the **Case Study & Simulation** tab first.")
        return

    lat, lon = scenario.lat, scenario.lon

    cols = st.columns([2, 2])
    with cols[0]:
        st.subheader("Active scenario location")
        st.markdown(f"Location 1: **{lat:.2f}°N, {lon:.2f}°E**")
        st.info(
            "To change location see **Case Study Definition** tab: "
            "see *Customise parameters* → *Project Location*."
        )
    with cols[1]:
        st.map(pd.DataFrame({"lat": [lat], "lon": [lon]}), zoom=6, height=300)

    #st.markdown("---")

    # ── API tokens ────────────────────────────────────────────────────────────
    st.subheader("API tokens")
    cols = st.columns(4)

    with cols[0]:
        st.markdown("**ENTSO-E Transparency Platform**")
        st.caption("Free registration: [ENTSO-E's Transparency Platform](https://transparency.entsoe.eu/)")

    with cols[1]:
        entsoe_token = st.text_input(
            "ENTSO-E token",
            value=_get_token("entsoe"),
            type="password",
            key="dd_entsoe_token",
            placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        )
        _save_token("entsoe", entsoe_token)

    with cols[2]:
        st.markdown("**Renewables.ninja**")
        st.caption("Free registration: [Renewables.ninja](https://www.renewables.ninja/register)")

    with cols[3]:
        ninja_token = st.text_input(
            "Renewables.ninja token",
            value=_get_token("ninja"),
            type="password",
            key="dd_ninja_token",
            placeholder="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        )
        _save_token("ninja", ninja_token)

    # ── Data status ───────────────────────────────────────────────────────────
    st.subheader("Cache status")

    from ppa.data.entsoe_client import list_cached_years as list_cached_price_years, AVAILABLE_YEARS as PRICE_YEARS
    from ppa.data.renewables_ninja import list_cached_years, AVAILABLE_YEARS

    cached_price_years = list_cached_price_years()
    missing_prices = [y for y in PRICE_YEARS if y not in cached_price_years]
    cached_cf_years = list_cached_years(lat=lat, lon=lon)
    missing_cf = [y for y in AVAILABLE_YEARS if y not in cached_cf_years]

    cols = st.columns(4)
    with cols[0]:
        st.markdown("**ENTSO-E day-ahead (DA) prices**")

    with cols[1]:
        if not missing_prices:
            st.success(f"All {len(PRICE_YEARS)} years cached ✓ ")
            st.caption(f"Available: {', '.join(str(y) for y in cached_price_years)}")
        elif cached_price_years:
            st.warning(f"{len(cached_price_years)}/{len(PRICE_YEARS)} years cached. Missing: {missing_prices}")
        else:
            st.warning(f"No years cached. Will download: {PRICE_YEARS}")

    with cols[2]:
        st.markdown(f"**Renewables.ninja normalized renewable profiles**")

    with cols[3]:
        if not missing_cf:
            st.success(f"All {len(AVAILABLE_YEARS)} years cached ✓ ")
            st.caption(f"Available: {', '.join(str(y) for y in cached_cf_years)}")
        elif cached_cf_years:
            st.warning(f"{len(cached_cf_years)}/{len(AVAILABLE_YEARS)} years cached. Missing: {missing_cf}")
        else:
            st.warning(f"No years cached for this location. Will download: {AVAILABLE_YEARS}")

    # ── Download button ───────────────────────────────────────────────────────
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
