import pytest

from ppa.data.bidding_zones import SUPPORTED_ZONES, ZONE_LABELS, bidding_zone_for, zone_label


@pytest.mark.parametrize(
    "lat,lon,expected_zone",
    [
        (52.52, 13.40, "DE_LU"),   # Berlin
        (48.85, 2.35, "FR"),       # Paris
        (52.37, 4.90, "NL"),       # Amsterdam
        (41.90, 12.50, "IT_CSUD"),  # Rome
        (59.33, 18.07, "SE_3"),    # Stockholm
    ],
)
def test_bidding_zone_for_known_cities(lat, lon, expected_zone):
    assert bidding_zone_for(lat, lon) == expected_zone


def test_bidding_zone_for_always_returns_a_supported_zone():
    # A coordinate far from Europe still returns nearest-anchor best guess.
    zone = bidding_zone_for(0.0, 0.0)
    assert zone in SUPPORTED_ZONES


def test_bidding_zone_for_is_deterministic():
    assert bidding_zone_for(51.5, 10.0) == bidding_zone_for(51.5, 10.0)


def test_zone_label_known_zone():
    assert zone_label("DE_LU") == ZONE_LABELS["DE_LU"]


def test_zone_label_unknown_zone_falls_back_to_code():
    assert zone_label("NOT_A_ZONE") == "NOT_A_ZONE"


def test_all_supported_zones_have_labels():
    for zone in SUPPORTED_ZONES:
        assert zone_label(zone) != "" and zone_label(zone) is not None
