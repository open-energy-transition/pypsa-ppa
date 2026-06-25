"""Reference industrial load profiles for PPA offtakers.

Each profile function accepts a pd.DatetimeIndex and returns a pd.Series of
normalized load values in [0, 1]. Multiply by scenario.ppaload_mw to get MW.

Profiles for cement and steel are derived from real measured data published by
the Forschungsstelle für Energiewirtschaft (FfE) via their open data API
(id_opendata=59, bundled at ppa/data/ffe_profiles.json). The profiles cover
8760 hours of a 2017 reference year; they are mapped to the target simulation
year by averaging over (month, day-of-week, hour) triplets so that seasonal
and weekday patterns are preserved under year-to-year calendar shifts.

All other profiles remain synthetically generated.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

# ── FfE data ───────────────────────────────────────────────────────────────────

_FFE_JSON = Path(__file__).parent / "data" / "ffe_profiles.json"

# FfE internal_id → profile name mapping (from pypsa-eur PR #1875)
_FFE_ID_TO_NAME = {
    1: "Iron & steel industry",
    4: "Non-metallic Minerals",
    5: "Transport Equipment",
    6: "Machinery",
    7: "Mining and Quarrying",
    8: "Food and Tobacco",
    9: "Paper, Pulp and Print",
    10: "Wood and Wood Products",
    11: "Construction",
    12: "Textile and Leather",
    13: "Non-specified (Industry)",
}

# Maps our profile keys to FfE sector ids
_PROFILE_TO_FFE_ID = {
    "cement_plant": 4,   # Non-metallic Minerals (cement, glass, ceramics)
    "steel_eaf": 1,      # Iron & steel industry
}


@lru_cache(maxsize=1)
def _load_ffe_df() -> pd.DataFrame:
    """Load FfE profiles into a DataFrame indexed by a 2017 DatetimeIndex."""
    with open(_FFE_JSON) as f:
        raw = json.load(f)

    ref_index = pd.date_range("2017-01-01", periods=8760, freq="h")
    rows = {}
    for item in raw["data"]:
        sector_id = item["internal_id"][0]
        name = _FFE_ID_TO_NAME.get(sector_id)
        if name is not None:
            rows[name] = item["values"]

    return pd.DataFrame(rows, index=ref_index)


def _ffe_profile(sector_id: int, index: pd.DatetimeIndex) -> pd.Series:
    """Return a normalized (0–1) FfE sector profile mapped to *index*.

    The 2017 reference data is averaged by (month, dayofweek, hour) and then
    looked up for every hour in *index*, preserving seasonal and weekday
    patterns regardless of the target year. Values are normalized so max = 1.
    """
    df = _load_ffe_df()
    name = _FFE_ID_TO_NAME[sector_id]
    s = df[name]

    # Build lookup: average by (month, day-of-week, hour)
    keys = pd.DataFrame({
        "month": s.index.month,
        "dow": s.index.dayofweek,
        "hour": s.index.hour,
    }, index=s.index)
    avg = s.groupby([keys["month"], keys["dow"], keys["hour"]]).mean()
    avg.index.names = ["month", "dow", "hour"]

    # Look up each hour in the target index
    values = np.array([
        avg.loc[(t.month, t.dayofweek, t.hour)]
        for t in index
    ])

    # Normalize to [0, 1] so max hour = 1.0
    values /= values.max()
    return pd.Series(values, index=index, dtype=float)


# ── Registry & metadata ───────────────────────────────────────────────────────

PROFILE_INFO: dict[str, dict] = {
    "flat": {
        "label": "Flat (constant)",
        "icon": "➖",
        "typical_lf": "100%",
        "description": (
            "Constant demand equal to the rated PPA MW at every hour. "
            "The baseline for all comparison scenarios."
        ),
    },
    "cement_plant": {
        "label": "Cement plant",
        "icon": "🏭",
        "typical_lf": "~68%",
        "description": (
            "Non-metallic minerals sector (cement, glass, ceramics). "
            "Real hourly pattern from FfE open data (2017 reference year), "
            "mapped to the simulation year by month / weekday / hour averages."
        ),
    },
    "steel_eaf": {
        "label": "Steel — Electric Arc Furnace",
        "icon": "⚙️",
        "typical_lf": "~97%",
        "description": (
            "Iron & steel industry sector. "
            "Real hourly pattern from FfE open data (2017 reference year), "
            "mapped to the simulation year by month / weekday / hour averages."
        ),
    },
    "green_hydrogen": {
        "label": "Green hydrogen electrolyser",
        "icon": "🟢",
        "typical_lf": "~78%",
        "description": (
            "Flexible electrolyser that maximises operation during cheap renewable "
            "hours (midday & night) and reduces load during morning/evening grid peaks. "
            "Slightly higher on weekends when grid is less congested. Synthetic profile."
        ),
    },
    "data_center": {
        "label": "Data centre",
        "icon": "🖥️",
        "typical_lf": "~88%",
        "description": (
            "Stable IT load with a slight business-hours compute peak and low overnight "
            "minimum. Very low volatility — the textbook 'always-on' corporate offtaker. "
            "Synthetic profile."
        ),
    },
    "aluminum_smelter": {
        "label": "Aluminium smelter",
        "icon": "🔩",
        "typical_lf": "~97%",
        "description": (
            "Near-constant electrochemical Hall-Héroult process. "
            "Highest load factor of any heavy industry; only interrupted by "
            "periodic anode replacement (brief dip every ~28 days). Synthetic profile."
        ),
    },
}

PROFILE_KEYS: list[str] = list(PROFILE_INFO.keys())


# ── Public API ─────────────────────────────────────────────────────────────────

def get_load_series(profile_name: str, index: pd.DatetimeIndex) -> pd.Series:
    """Return normalized load profile (0–1) for *profile_name* over *index*."""
    fn = _REGISTRY.get(profile_name, _flat)
    return fn(index)


# ── Profile implementations ────────────────────────────────────────────────────

def _flat(index: pd.DatetimeIndex) -> pd.Series:
    return pd.Series(np.ones(len(index)), index=index, dtype=float)


def _cement_plant(index: pd.DatetimeIndex) -> pd.Series:
    return _ffe_profile(_PROFILE_TO_FFE_ID["cement_plant"], index)


def _steel_eaf(index: pd.DatetimeIndex) -> pd.Series:
    return _ffe_profile(_PROFILE_TO_FFE_ID["steel_eaf"], index)


def _green_hydrogen(index: pd.DatetimeIndex) -> pd.Series:
    h = index.hour
    dow = index.dayofweek

    _weekday = np.array([
        0.90, 0.90, 0.92, 0.92, 0.90, 0.85,   # 00–05: cheap night
        0.75, 0.65, 0.65, 0.80, 0.98, 1.00,   # 06–11: morning ramp + solar
        1.00, 1.00, 1.00, 0.98, 0.90, 0.72,   # 12–17: peak solar → evening ramp
        0.65, 0.65, 0.68, 0.75, 0.85, 0.90,   # 18–23: evening peak avoidance
    ])

    load = _weekday[h]
    weekend = (dow >= 5).astype(float)
    load = np.minimum(load * (1.0 + 0.05 * weekend), 1.0)

    return pd.Series(load, index=index, dtype=float)


def _data_center(index: pd.DatetimeIndex) -> pd.Series:
    h = index.hour
    dow = index.dayofweek

    _weekday = np.array([
        0.80, 0.78, 0.77, 0.77, 0.78, 0.80,   # 00–05: night minimum
        0.84, 0.90, 0.96, 1.00, 1.00, 1.00,   # 06–11: morning ramp
        1.00, 1.00, 1.00, 1.00, 0.98, 0.95,   # 12–17: full compute day
        0.90, 0.88, 0.86, 0.84, 0.82, 0.80,   # 18–23: evening taper
    ])
    _weekend = _weekday * 0.88

    is_weekend = (dow >= 5)
    load = np.where(is_weekend, _weekend[h], _weekday[h])
    return pd.Series(load, index=index, dtype=float)


def _aluminum_smelter(index: pd.DatetimeIndex) -> pd.Series:
    day_of_year = index.dayofyear
    h = index.hour

    anode_window = (day_of_year % 28 == 0) & (h >= 2) & (h < 6)
    load = np.where(anode_window, 0.78, 0.97)
    return pd.Series(load, index=index, dtype=float)


_REGISTRY: dict[str, object] = {
    "flat": _flat,
    "cement_plant": _cement_plant,
    "steel_eaf": _steel_eaf,
    "green_hydrogen": _green_hydrogen,
    "data_center": _data_center,
    "aluminum_smelter": _aluminum_smelter,
}
