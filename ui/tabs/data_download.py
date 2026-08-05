"""Download European market and weather data for the active scenario locations."""
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
        "Download market prices and wind/solar hourly profiles for the locations defined in "
        "your active scenario. Data is cached locally per bidding zone and per asset location — "
        "downloads only happen once per zone/location. "
        "**Currently supported locations are in Europe only and cover the years 2018 until 2024.**"
    )

    # ── Active locations & bidding zone ───────────────────────────────────────
    scenario = state.get_scenario()
    if scenario is None:
        st.info("Define a scenario in the **Case Study & Simulation** tab first.")
        return

    lat, lon = scenario.lat, scenario.lon
    pv_lat, pv_lon = scenario.pv_location
    wind_lat, wind_lon = scenario.wind_location
    zone = scenario.bidding_zone

    from ppa.data.bidding_zones import zone_label
    from ppa.data.entsoe_client import list_cached_years as list_cached_price_years, AVAILABLE_YEARS as PRICE_YEARS
    from ppa.data.renewables_ninja import list_cached_pv_years, list_cached_wind_years, AVAILABLE_YEARS

    cached_price_years = list_cached_price_years(country_code=zone)
    missing_prices = [y for y in PRICE_YEARS if y not in cached_price_years]
    cached_pv_years = list_cached_pv_years(lat=pv_lat, lon=pv_lon)
    missing_pv = [y for y in AVAILABLE_YEARS if y not in cached_pv_years]
    cached_wind_years = list_cached_wind_years(lat=wind_lat, lon=wind_lon)
    missing_wind = [y for y in AVAILABLE_YEARS if y not in cached_wind_years]
    needs_download = bool(missing_prices) or bool(missing_pv) or bool(missing_wind)

    with st.expander("**Scenario locations**", expanded=False):
        cols = st.columns([2, 2])
        with cols[0]:
            st.markdown(
                f"Offtaker: **{lat:.2f}°N, {lon:.2f}°E** — bidding zone "
                f"**{zone}** ({zone_label(zone)})"
            )
            st.markdown(f"PV asset: **{pv_lat:.2f}°N, {pv_lon:.2f}°E**")
            st.markdown(f"Wind asset: **{wind_lat:.2f}°N, {wind_lon:.2f}°E**")
            st.info(
                "To change locations or override the bidding zone see **Case Setup** tab: "
                "*Customise parameters* → *Project Locations & Market Zone*."
            )
        with cols[1]:
            points = pd.DataFrame(
                {
                    "lat": [lat, pv_lat, wind_lat],
                    "lon": [lon, pv_lon, wind_lon],
                    "color": ["#1565C0", "#F9A825", "#2E7D32"],
                }
            ).drop_duplicates(subset=["lat", "lon"])
            st.map(points, zoom=5, height=400, color="color")
            st.caption("🔵 Offtaker · 🟡 PV · 🟢 Wind")

    # ── API tokens ────────────────────────────────────────────────────────────
    expanded_status = True if needs_download else False
    with st.expander("**API tokens**", expanded=expanded_status):
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

    tokens_present = bool(entsoe_token) and bool(ninja_token)

    # ── Data status ───────────────────────────────────────────────────────────
    expanded_status = True if needs_download else False
    with st.expander("**Cache status**", expanded=expanded_status):
        cols = st.columns(4)
        with cols[0]:
            st.markdown(f"**ENTSO-E day-ahead (DA) prices — {zone}**")

        with cols[1]:
            if not missing_prices:
                st.success(f"All {len(PRICE_YEARS)} years cached ✓ ")
                st.caption(f"Available: {', '.join(str(y) for y in cached_price_years)}")
            elif cached_price_years:
                st.warning(f"{len(cached_price_years)}/{len(PRICE_YEARS)} years cached. Missing: {missing_prices}")
            else:
                st.warning(f"No years cached for zone {zone}. Will download: {PRICE_YEARS}")

        with cols[2]:
            st.markdown("**Renewables.ninja normalized renewable profiles**")

        with cols[3]:
            for label, cached, missing in [
                (f"PV ({pv_lat:.2f}, {pv_lon:.2f})", cached_pv_years, missing_pv),
                (f"Wind ({wind_lat:.2f}, {wind_lon:.2f})", cached_wind_years, missing_wind),
            ]:
                if not missing:
                    st.success(f"{label}: all {len(AVAILABLE_YEARS)} years cached ✓")
                elif cached:
                    st.warning(f"{label}: {len(cached)}/{len(AVAILABLE_YEARS)} years cached. Missing: {missing}")
                else:
                    st.warning(f"{label}: no years cached. Will download: {AVAILABLE_YEARS}")

    # ── Custom timeseries import ────────────────────────────────────────────────
    from ppa.data.custom_timeseries import (
        TEMPLATE_YEARS,
        TemplateValidationError,
        build_template,
        parse_and_validate,
        template_to_csv_bytes,
    )

    custom = state.get_custom_timeseries()
    custom_expanded = bool(custom)
    with st.expander("**Import custom timeseries**", expanded=custom_expanded):
        st.markdown(
            "Rather than using the publicly available ENTSO-E / renewables.ninja data, you "
            "can substitute your own day-ahead price and PV/wind capacity-factor data for "
            f"any of the weather years this app cycles through ({TEMPLATE_YEARS[0]}–{TEMPLATE_YEARS[-1]})."
        )

        if custom:
            active_years = sorted(
                set(custom.get("price", {}))
                | set(custom.get("pv_cf", {}))
                | set(custom.get("wind_cf", {}))
            )
            st.success(f"Custom timeseries active for weather year(s): {active_years}")
            if st.button("Clear custom timeseries", key="dd_clear_custom"):
                state.clear_custom_timeseries()
                st.session_state.pop("_dd_custom_upload_fp", None)
                st.rerun()

        st.markdown(
            "1. **Download the template** below — it's pre-filled with whatever is already "
            "cached for this scenario's zone/locations (blank where nothing is cached yet).\n"
            "2. Edit `price_eur_mwh` (€/MWh), `pv_capacity_factor` and `wind_capacity_factor` "
            "(both 0–1) for the year(s) you want to override. Leave other years untouched, or "
            "delete their rows entirely — only years present in the re-uploaded file are "
            "overridden, every other year keeps using downloaded/cached data.\n"
            "3. Don't edit `year`, `hour_of_year` or `timestamp_utc` — rows are matched back "
            "positionally by hour-of-year, and edits there will fail validation.\n"
            "4. Re-upload the edited CSV below."
        )

        template_df = build_template(zone, (pv_lat, pv_lon), (wind_lat, wind_lon))
        st.download_button(
            "Download template CSV",
            data=template_to_csv_bytes(template_df),
            file_name=f"custom_timeseries_template_{zone}.csv",
            mime="text/csv",
            key="dd_download_custom_template",
        )

        uploaded = st.file_uploader("Re-upload edited CSV", type=["csv"], key="dd_custom_upload")
        if uploaded is not None:
            # file_uploader keeps the last upload across reruns, so only (re)process
            # it once per distinct file — otherwise the post-success st.rerun() below
            # would re-trigger this branch forever.
            fingerprint = (uploaded.name, uploaded.size)
            if st.session_state.get("_dd_custom_upload_fp") != fingerprint:
                st.session_state["_dd_custom_upload_fp"] = fingerprint
                try:
                    parsed = parse_and_validate(uploaded.getvalue())
                except TemplateValidationError as exc:
                    st.session_state["_dd_custom_upload_error"] = exc.errors
                else:
                    st.session_state.pop("_dd_custom_upload_error", None)
                    state.set_custom_timeseries(parsed)
                    st.rerun()

            errors = st.session_state.get("_dd_custom_upload_error")
            if errors:
                st.error("Upload rejected — fix the following issue(s) and re-upload:")
                for msg in errors[:15]:
                    st.markdown(f"- {msg}")
                if len(errors) > 15:
                    st.caption(f"...and {len(errors) - 15} more issue(s).")

    # ── Download button ───────────────────────────────────────────────────────
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
        _do_download(
            entsoe_token,
            ninja_token,
            zone,
            (pv_lat, pv_lon),
            (wind_lat, wind_lon),
            missing_prices,
            missing_pv,
            missing_wind,
        )
        st.rerun()


def _do_download(
    entsoe_token: str,
    ninja_token: str,
    zone: str,
    pv_location: tuple[float, float],
    wind_location: tuple[float, float],
    missing_price_years: list[int],
    missing_pv_years: list[int],
    missing_wind_years: list[int],
) -> None:
    total_steps = len(missing_price_years) + len(missing_pv_years) + len(missing_wind_years)
    done = 0
    bar = st.progress(0, text="Preparing…")

    # ENTSO-E prices — all missing years for the scenario's bidding zone
    from ppa.data.entsoe_client import fetch_day_ahead_prices
    for year in missing_price_years:
        bar.progress(done / total_steps, text=f"Fetching {year} {zone} day-ahead prices…")
        try:
            fetch_day_ahead_prices(year, entsoe_token, country_code=zone)
            done += 1
            bar.progress(done / total_steps, text=f"ENTSO-E {zone} {year} prices downloaded ✓")
        except Exception as exc:
            st.error(f"ENTSO-E {zone} {year} download failed: {exc}")
            return

    # renewables.ninja CF profiles — PV and wind at their own asset locations
    from ppa.data import renewables_ninja as rn
    pv_lat, pv_lon = pv_location
    for year in missing_pv_years:
        bar.progress(done / total_steps, text=f"Downloading solar PV CF for {year}…")
        try:
            rn.download_pv_cf(year, ninja_token, lat=pv_lat, lon=pv_lon)
        except Exception as exc:
            st.error(f"PV CF download failed for {year}: {exc}")
            return
        done += 1
        time.sleep(2)  # respect renewables.ninja rate limit

    wind_lat, wind_lon = wind_location
    for year in missing_wind_years:
        bar.progress(done / total_steps, text=f"Downloading wind CF for {year}…")
        try:
            rn.download_wind_cf(year, ninja_token, lat=wind_lat, lon=wind_lon)
        except Exception as exc:
            st.error(f"Wind CF download failed for {year}: {exc}")
            return
        done += 1
        time.sleep(2)

    bar.progress(1.0, text="All data downloaded and cached ✓")
    st.success("Download complete. Cached at data/cache/")
