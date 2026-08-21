"""Map a European lat/lon to an ENTSO-E day-ahead bidding zone.

The lookup is nearest-anchor: each bidding zone is represented by a handful of
anchor points (major cities / load centres) and a coordinate is assigned to the
zone of its closest anchor. This handles jagged borders and multi-zone
countries (IT, NO, SE, DK) far better than bounding boxes, but it is still an
approximation near borders: the UI therefore lets the user override the
derived zone explicitly.

Zone codes match the ``entsoe-py`` area codes accepted by
``EntsoePandasClient.query_day_ahead_prices``. Great Britain is intentionally
absent: ENTSO-E stopped publishing GB day-ahead prices after Brexit.
"""

from __future__ import annotations

import math

# zone code → human-readable label (ordering = dropdown ordering in the UI)
ZONE_LABELS: dict[str, str] = {
    "DE_LU": "Germany–Luxembourg",
    "AT": "Austria",
    "BE": "Belgium",
    "NL": "Netherlands",
    "FR": "France",
    "CH": "Switzerland",
    "ES": "Spain",
    "PT": "Portugal",
    "IT_NORD": "Italy North",
    "IT_CNOR": "Italy Centre-North",
    "IT_CSUD": "Italy Centre-South",
    "IT_SUD": "Italy South",
    "IT_CALA": "Italy Calabria",
    "IT_SICI": "Italy Sicily",
    "IT_SARD": "Italy Sardinia",
    "PL": "Poland",
    "CZ": "Czechia",
    "SK": "Slovakia",
    "HU": "Hungary",
    "SI": "Slovenia",
    "HR": "Croatia",
    "RO": "Romania",
    "BG": "Bulgaria",
    "GR": "Greece",
    "DK_1": "Denmark West (DK1)",
    "DK_2": "Denmark East (DK2)",
    "SE_1": "Sweden North (SE1)",
    "SE_2": "Sweden North-Central (SE2)",
    "SE_3": "Sweden South-Central (SE3)",
    "SE_4": "Sweden South (SE4)",
    "NO_1": "Norway East (NO1)",
    "NO_2": "Norway South (NO2)",
    "NO_3": "Norway Central (NO3)",
    "NO_4": "Norway North (NO4)",
    "NO_5": "Norway West (NO5)",
    "FI": "Finland",
    "EE": "Estonia",
    "LV": "Latvia",
    "LT": "Lithuania",
    "IE_SEM": "Ireland (SEM)",
}

SUPPORTED_ZONES: list[str] = list(ZONE_LABELS)

# zone → [(lat, lon), ...] anchor points (major cities / load centres)
_ANCHORS: dict[str, list[tuple[float, float]]] = {
    "DE_LU": [
        (53.55, 10.00),
        (52.52, 13.40),
        (50.94, 6.96),
        (50.11, 8.68),
        (48.14, 11.58),
        (51.34, 12.37),
        (48.78, 9.18),
        (52.37, 9.73),
        (49.61, 6.13),
    ],
    "AT": [(48.21, 16.37), (47.07, 15.44), (47.27, 11.40), (47.80, 13.04)],
    "BE": [(50.85, 4.35), (51.22, 4.40), (50.63, 5.57)],
    "NL": [(52.37, 4.90), (51.92, 4.48), (53.22, 6.57), (51.44, 5.47)],
    "FR": [
        (48.85, 2.35),
        (45.76, 4.84),
        (43.30, 5.37),
        (43.60, 1.44),
        (44.84, -0.58),
        (47.22, -1.55),
        (50.63, 3.06),
        (48.57, 7.75),
        (48.39, -4.49),
        (45.19, 5.72),
    ],
    "CH": [(47.37, 8.54), (46.20, 6.14), (46.95, 7.45)],
    "ES": [
        (40.42, -3.70),
        (41.39, 2.17),
        (37.39, -5.99),
        (39.47, -0.38),
        (43.26, -2.93),
        (41.65, -0.88),
        (36.72, -4.42),
        (42.88, -8.54),
    ],
    "PT": [(38.72, -9.14), (41.15, -8.61), (37.02, -7.93)],
    "IT_NORD": [
        (45.46, 9.19),
        (45.07, 7.69),
        (45.44, 12.32),
        (44.49, 11.34),
        (44.41, 8.93),
    ],
    "IT_CNOR": [(43.77, 11.25), (43.62, 13.51), (43.11, 12.39)],
    "IT_CSUD": [(41.90, 12.50), (40.85, 14.27), (42.46, 14.21)],
    "IT_SUD": [(41.13, 16.87), (40.46, 17.24), (40.64, 15.80), (41.56, 14.66)],
    "IT_CALA": [(38.91, 16.59), (39.31, 16.25), (38.11, 15.65)],
    "IT_SICI": [(38.12, 13.36), (37.50, 15.09)],
    "IT_SARD": [(39.22, 9.12), (40.73, 8.56)],
    "PL": [
        (52.23, 21.01),
        (50.06, 19.94),
        (51.11, 17.03),
        (52.41, 16.93),
        (54.35, 18.65),
        (53.43, 14.55),
        (51.25, 22.57),
    ],
    "CZ": [(50.08, 14.44), (49.19, 16.61), (49.84, 18.29), (49.74, 13.37)],
    "SK": [(48.15, 17.11), (48.72, 21.26), (49.06, 18.92)],
    "HU": [(47.50, 19.04), (47.53, 21.62), (46.07, 18.23), (46.25, 20.15)],
    "SI": [(46.06, 14.51), (46.55, 15.65)],
    "HR": [(45.81, 15.98), (43.51, 16.44), (45.55, 18.69), (45.33, 14.44)],
    "RO": [
        (44.43, 26.10),
        (46.77, 23.60),
        (45.76, 21.23),
        (47.16, 27.59),
        (44.18, 28.65),
    ],
    "BG": [(42.70, 23.32), (42.14, 24.75), (43.21, 27.92)],
    "GR": [(37.98, 23.73), (40.64, 22.94), (38.25, 21.73), (35.34, 25.13)],
    "DK_1": [(56.16, 10.20), (57.05, 9.92), (55.47, 8.45), (55.40, 10.40)],
    "DK_2": [(55.68, 12.57), (55.64, 12.08)],
    "SE_1": [(65.58, 22.15), (67.86, 20.23)],
    "SE_2": [(62.39, 17.31), (63.18, 14.64), (63.83, 20.26)],
    "SE_3": [(59.33, 18.07), (57.71, 11.97), (59.27, 15.21), (59.86, 17.64)],
    "SE_4": [(55.60, 13.00), (56.66, 16.36), (56.05, 14.16)],
    "NO_1": [(59.91, 10.75), (60.79, 11.07)],
    "NO_2": [(58.15, 8.00), (58.97, 5.73)],
    "NO_3": [(63.43, 10.40), (62.74, 7.16)],
    "NO_4": [(69.65, 18.96), (67.28, 14.40)],
    "NO_5": [(60.39, 5.32)],
    "FI": [(60.17, 24.94), (61.50, 23.76), (65.01, 25.47), (62.89, 27.68)],
    "EE": [(59.44, 24.75), (58.38, 26.72)],
    "LV": [(56.95, 24.11), (55.87, 26.54), (56.51, 21.01)],
    "LT": [(54.69, 25.28), (54.90, 23.90), (55.70, 21.14)],
    "IE_SEM": [(53.35, -6.26), (51.90, -8.47), (54.60, -5.93), (53.27, -9.05)],
}


def _distance_sq(lat: float, lon: float, alat: float, alon: float) -> float:
    """Squared equirectangular distance: fine for ranking nearby anchors."""
    dlat = lat - alat
    dlon = (lon - alon) * math.cos(math.radians((lat + alat) / 2.0))
    return dlat * dlat + dlon * dlon


def bidding_zone_for(lat: float, lon: float) -> str:
    """Return the ENTSO-E bidding-zone code whose anchor is closest to (lat, lon).

    Always returns a zone (nearest-anchor never fails), so callers should let
    users override the result when the coordinate is near a border or outside
    the covered area.
    """
    best_zone, best_d = "DE_LU", float("inf")
    for zone, anchors in _ANCHORS.items():
        for alat, alon in anchors:
            d = _distance_sq(lat, lon, alat, alon)
            if d < best_d:
                best_zone, best_d = zone, d
    return best_zone


def zone_label(zone: str) -> str:
    return ZONE_LABELS.get(zone, zone)
