import dataclasses

import pytest

from ppa.scenario import (
    BASE_SCENARIO,
    CASE_STUDIES,
    CASE_STUDIES_BY_ID,
    Scenario,
    load_case_study,
    validate_scenario,
)


def test_effective_bess_zero_when_disabled():
    s = Scenario(include_bess=False, bess_mw=60.0, bess_mwh=240.0)
    assert s.effective_bess_mw == 0.0
    assert s.effective_bess_mwh == 0.0


def test_effective_bess_passthrough_when_enabled():
    s = Scenario(include_bess=True, bess_mw=60.0, bess_mwh=240.0)
    assert s.effective_bess_mw == 60.0
    assert s.effective_bess_mwh == 240.0


def test_bess_max_hours_derived_from_power_and_energy():
    s = Scenario(include_bess=True, bess_mw=60.0, bess_mwh=240.0)
    assert s.bess_max_hours == pytest.approx(4.0)


def test_bess_max_hours_defaults_when_no_bess():
    s = Scenario(include_bess=False, bess_mw=0.0, bess_mwh=0.0)
    assert s.bess_max_hours == 4.0


def test_allowed_shortfall_share_disabled():
    s = Scenario(enable_shortfall=False, required_delivery_share=0.75)
    assert s.allowed_shortfall_share == 0.0


def test_allowed_shortfall_share_enabled():
    s = Scenario(enable_shortfall=True, required_delivery_share=0.75)
    assert s.allowed_shortfall_share == pytest.approx(0.25)


def test_maxbuy_mw_respects_toggle():
    on = Scenario(enable_market_buy=True, ppaload_mw=100.0)
    off = Scenario(enable_market_buy=False, ppaload_mw=100.0)
    assert on.maxbuy_mw == 100.0
    assert off.maxbuy_mw == 0.0


def test_maxsell_mw_sums_installed_capacity():
    s = Scenario(enable_market_sell=True, onsw_mw=100.0, pv_mw=50.0, bess_mw=10.0, include_bess=True)
    assert s.maxsell_mw == pytest.approx(160.0)


def test_crf_matches_annuity_formula():
    s = Scenario(discount_rate=0.08, project_life_yrs=25)
    r, n = 0.08, 25
    expected = r / (1 - (1 + r) ** -n)
    assert s.crf == pytest.approx(expected)


def test_crf_zero_discount_rate_falls_back_to_straight_line():
    s = Scenario(discount_rate=0.0, project_life_yrs=25)
    assert s.crf == pytest.approx(1.0 / 25)


def test_penalty_price_applies_multiple_when_enabled():
    s = Scenario(enable_penalty=True, ppa_price=100.0, pen_mult=1.5)
    assert s.penalty_price == pytest.approx(150.0)


def test_penalty_price_equals_ppa_price_when_disabled():
    s = Scenario(enable_penalty=False, ppa_price=100.0, pen_mult=1.5)
    assert s.penalty_price == pytest.approx(100.0)


def test_pv_and_wind_location_default_to_offtaker():
    s = Scenario(lat=51.5, lon=10.0)
    assert s.pv_location == (51.5, 10.0)
    assert s.wind_location == (51.5, 10.0)


def test_pv_location_override():
    s = Scenario(lat=51.5, lon=10.0, pv_lat=40.0, pv_lon=5.0)
    assert s.pv_location == (40.0, 5.0)


def test_bidding_zone_override_takes_precedence():
    s = Scenario(bidding_zone_override="FR")
    assert s.bidding_zone == "FR"


def test_bidding_zone_derived_from_location_when_no_override():
    s = Scenario(bidding_zone_override="", lat=48.85, lon=2.35)  # Paris
    assert s.bidding_zone == "FR"


def test_to_dict_round_trips_into_scenario():
    s = Scenario(onsw_mw=42.0)
    d = s.to_dict()
    assert d["onsw_mw"] == 42.0
    assert Scenario(**d) == s


# ── validate_scenario ──────────────────────────────────────────────────────


def test_validate_scenario_accepts_defaults():
    assert validate_scenario(BASE_SCENARIO) == []


def test_validate_scenario_flags_negative_wind():
    s = dataclasses.replace(BASE_SCENARIO, onsw_mw=-5.0)
    errors = validate_scenario(s)
    assert any("Onshore wind" in e for e in errors)


def test_validate_scenario_flags_bess_enabled_without_power():
    s = dataclasses.replace(BASE_SCENARIO, include_bess=True, bess_mw=0.0)
    errors = validate_scenario(s)
    assert any("BESS power" in e for e in errors)


def test_validate_scenario_flags_zero_load():
    s = dataclasses.replace(BASE_SCENARIO, ppaload_mw=0.0)
    errors = validate_scenario(s)
    assert any("PPA offtake load" in e for e in errors)


def test_validate_scenario_flags_bad_delivery_share():
    s = dataclasses.replace(BASE_SCENARIO, required_delivery_share=1.5)
    errors = validate_scenario(s)
    assert any("Required delivery share" in e for e in errors)


def test_validate_scenario_flags_unknown_load_profile():
    s = dataclasses.replace(BASE_SCENARIO, load_profile="not_a_real_profile")
    errors = validate_scenario(s)
    assert any("Unknown load profile" in e for e in errors)


def test_validate_scenario_flags_no_generation_when_not_sizing():
    s = dataclasses.replace(BASE_SCENARIO, optimize_capacity=False, onsw_mw=0.0, pv_mw=0.0)
    errors = validate_scenario(s)
    assert any("wind or solar" in e for e in errors)


def test_validate_scenario_sizing_mode_requires_positive_build_cap():
    s = dataclasses.replace(
        BASE_SCENARIO, optimize_capacity=True, max_build_wind_mw=0.0, max_build_pv_mw=0.0
    )
    errors = validate_scenario(s)
    assert any("max build" in e for e in errors)


def test_validate_scenario_sizing_mode_resolution_bounds():
    s = dataclasses.replace(BASE_SCENARIO, optimize_capacity=True, sizing_resolution_h=48)
    errors = validate_scenario(s)
    assert any("resolution" in e for e in errors)


def test_validate_scenario_unknown_bidding_zone_override():
    s = dataclasses.replace(BASE_SCENARIO, bidding_zone_override="NOT_A_ZONE")
    errors = validate_scenario(s)
    assert any("Unknown bidding zone" in e for e in errors)


def test_validate_scenario_chosen_day_must_be_available():
    errors = validate_scenario(BASE_SCENARIO, available_days=["2023-01-01"])
    assert any("chosen_day" in e for e in errors)


# ── Case studies ─────────────────────────────────────────────────────────────


def test_all_case_studies_are_individually_valid():
    for cs in CASE_STUDIES:
        scenario = load_case_study(cs)
        assert validate_scenario(scenario) == [], f"case study {cs.id!r} failed validation"


def test_case_studies_indexed_by_id():
    for cs in CASE_STUDIES:
        assert CASE_STUDIES_BY_ID[cs.id] is cs


def test_load_case_study_applies_overrides_on_top_of_base():
    cs = CASE_STUDIES_BY_ID["foundation_deal"]
    scenario = load_case_study(cs)
    assert scenario.onsw_mw == cs.overrides["onsw_mw"]
    # Unrelated field should still come from BASE_SCENARIO
    assert scenario.bidding_zone_override == BASE_SCENARIO.bidding_zone_override
