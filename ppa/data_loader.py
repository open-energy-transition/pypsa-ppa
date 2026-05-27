from __future__ import annotations

from pathlib import Path

import pandas as pd

from ppa.scenario import Scenario

REQUIRED_COLUMNS = ["timestamp", "ts_PVGen", "ts_WindGen", "ts_NSWPrice"]

_DEFAULT_CSV_CANDIDATES = [
    Path(__file__).parent.parent / "data" / "march_2025_pypsa_timeseries.csv",
]


def find_default_csv() -> Path | None:
    for p in _DEFAULT_CSV_CANDIDATES:
        if p.exists():
            return p
    return None


def load_timeseries(csv_path: str | Path) -> pd.DataFrame:
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Timeseries CSV not found: {csv_path}")

    ts = pd.read_csv(csv_path)

    missing = [c for c in REQUIRED_COLUMNS if c not in ts.columns]
    if missing:
        raise ValueError(f"Missing required columns in CSV: {missing}")

    ts["timestamp"] = pd.to_datetime(ts["timestamp"])
    ts = ts.sort_values("timestamp").set_index("timestamp")
    ts.index.name = "snapshot"
    return ts


def prepare_timeseries(ts: pd.DataFrame, scenario: Scenario) -> pd.DataFrame:
    ts = ts.copy()
    ts["ts_MktPrice"] = ts["ts_NSWPrice"]
    ts["ppaload_mw"] = scenario.ppaload_mw
    return ts


def get_available_days(ts: pd.DataFrame) -> list[str]:
    return sorted({str(d.date()) for d in ts.index})
