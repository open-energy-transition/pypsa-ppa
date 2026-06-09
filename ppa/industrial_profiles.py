"""Reference industrial load profiles for PPA offtakers.

Each profile function accepts a pd.DatetimeIndex and returns a pd.Series of
normalized load values in [0, 1]. Multiply by scenario.ppaload_mw to get MW.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

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
        "typical_lf": "~88%",
        "description": (
            "Continuous rotary kiln (~70% of load) plus grinding mills (~30%). "
            "Slight overnight dip for mill flexibility, weekend reduction, "
            "and a weekly Sunday maintenance window."
        ),
    },
    "steel_eaf": {
        "label": "Steel — Electric Arc Furnace",
        "icon": "⚙️",
        "typical_lf": "~45%",
        "description": (
            "Batch melting with 90-minute tap-to-tap cycles: high load during "
            "the heat (~60 min), very low between heats (~30 min). "
            "Two operating shifts (06:00–22:00); idle overnight and on Sundays."
        ),
    },
    "green_hydrogen": {
        "label": "Green hydrogen electrolyser",
        "icon": "🟢",
        "typical_lf": "~78%",
        "description": (
            "Flexible electrolyser that maximises operation during cheap renewable "
            "hours (midday & night) and reduces load during morning/evening grid peaks. "
            "Slightly higher on weekends when grid is less congested."
        ),
    },
    "data_center": {
        "label": "Data centre",
        "icon": "🖥️",
        "typical_lf": "~88%",
        "description": (
            "Stable IT load with a slight business-hours compute peak and low overnight "
            "minimum. Very low volatility — the textbook 'always-on' corporate offtaker."
        ),
    },
    "aluminum_smelter": {
        "label": "Aluminium smelter",
        "icon": "🔩",
        "typical_lf": "~97%",
        "description": (
            "Near-constant electrochemical Hall-Héroult process. "
            "Highest load factor of any heavy industry; only interrupted by "
            "periodic anode replacement (brief dip every ~28 days)."
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
    """Kiln + grinding mills: near-baseload with weekly maintenance shutdown."""
    h = index.hour
    dow = index.dayofweek  # 0=Mon … 6=Sun

    # Sunday 03:00–11:00: planned weekly maintenance / kiln inspection
    maintenance = (dow == 6) & (h >= 3) & (h < 11)

    load = np.where(
        maintenance,
        0.28,  # kiln at reduced purge mode, mills stopped
        np.where(
            dow < 5,  # weekdays
            np.where((h >= 22) | (h < 5), 0.90, 1.00),  # slight night dip for mills
            np.where(dow == 5, 0.83, 0.72),              # Sat / rest of Sun
        ),
    )
    return pd.Series(load, index=index, dtype=float)


def _steel_eaf(index: pd.DatetimeIndex) -> pd.Series:
    """Electric Arc Furnace: 90-minute tap-to-tap batch cycles, two shifts."""
    h = index.hour
    dow = index.dayofweek

    # 90-min cycle position (hours are on-the-hour, minute=0)
    cycle_pos = (h * 60) % 90  # 0, 60, 30, 0, 60, 30 … repeating each 3 h
    in_heat = cycle_pos < 60   # 60 min heat, 30 min between (scrap charge / tap)

    # Operating shifts 06:00–22:00; idle overnight
    in_shift = (h >= 6) & (h < 22)

    load = np.where(
        dow == 6,                            # Sunday: full shutdown
        0.05,
        np.where(
            in_shift,
            np.where(in_heat, 0.95, 0.15),  # during shift: heat vs. between
            0.05,                            # overnight: idle
        ),
    )
    return pd.Series(load, index=index, dtype=float)


def _green_hydrogen(index: pd.DatetimeIndex) -> pd.Series:
    """Flexible electrolyser: maximises cheap-hour operation, avoids grid peaks."""
    h = index.hour
    dow = index.dayofweek

    # Hourly weights indexed 0-23
    _weekday = np.array([
        0.90, 0.90, 0.92, 0.92, 0.90, 0.85,   # 00–05: cheap night
        0.75, 0.65, 0.65, 0.80, 0.98, 1.00,   # 06–11: morning ramp + solar
        1.00, 1.00, 1.00, 0.98, 0.90, 0.72,   # 12–17: peak solar → evening ramp
        0.65, 0.65, 0.68, 0.75, 0.85, 0.90,   # 18–23: evening peak avoidance
    ])

    load = _weekday[h]
    # Weekends: slightly higher (grid less congested, cheaper prices)
    weekend = (dow >= 5).astype(float)
    load = np.minimum(load * (1.0 + 0.05 * weekend), 1.0)

    return pd.Series(load, index=index, dtype=float)


def _data_center(index: pd.DatetimeIndex) -> pd.Series:
    """Stable IT load: slight business-hours peak, low overnight minimum."""
    h = index.hour
    dow = index.dayofweek

    _weekday = np.array([
        0.80, 0.78, 0.77, 0.77, 0.78, 0.80,   # 00–05: night minimum
        0.84, 0.90, 0.96, 1.00, 1.00, 1.00,   # 06–11: morning ramp
        1.00, 1.00, 1.00, 1.00, 0.98, 0.95,   # 12–17: full compute day
        0.90, 0.88, 0.86, 0.84, 0.82, 0.80,   # 18–23: evening taper
    ])
    _weekend = _weekday * 0.88  # weekends ~12% lower

    is_weekend = (dow >= 5)
    load = np.where(is_weekend, _weekend[h], _weekday[h])
    return pd.Series(load, index=index, dtype=float)


def _aluminum_smelter(index: pd.DatetimeIndex) -> pd.Series:
    """Near-constant Hall-Héroult smelting with periodic anode replacement dips."""
    day_of_year = index.dayofyear
    h = index.hour

    # Anode replacement every 28 days: 4-hour dip to ~78%
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
