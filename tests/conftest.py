"""Shared fixtures for the pypsa-ppa test suite.

Fixtures build small, deterministic timeseries (48 hours) so that PyPSA/HiGHS
solves stay fast (well under a second each) while still exercising the real
network-building and solving code paths.
"""
from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from ppa.network import build_network
from ppa.results import extract_results
from ppa.scenario import Scenario
from ppa.solver import solve

N_HOURS = 48


@pytest.fixture(scope="session")
def tiny_index() -> pd.DatetimeIndex:
    return pd.date_range("2023-01-01", periods=N_HOURS, freq="h", name="snapshot")


@pytest.fixture(scope="session")
def tiny_ts(tiny_index: pd.DatetimeIndex) -> pd.DataFrame:
    hours = np.arange(N_HOURS)
    hour_of_day = hours % 24

    # Solar bell curve centred at midday, zero at night.
    pv = np.clip(np.sin((hour_of_day - 6) / 12 * np.pi), 0.0, 1.0)
    # Wind: smooth oscillation, always producing something.
    wind = 0.5 + 0.3 * np.sin(hours / 7.0)
    # Market price: day/night swing.
    price = 50.0 + 25.0 * np.sin((hour_of_day - 8) / 12 * np.pi)

    return pd.DataFrame(
        {
            "ts_PVGen": pv,
            "ts_WindGen": wind,
            "ts_MktPrice": price,
            "ppaload_mw": np.full(N_HOURS, 100.0),
        },
        index=tiny_index,
    )


@pytest.fixture
def base_scenario() -> Scenario:
    return Scenario(
        name="Test Scenario",
        onsw_mw=120.0,
        pv_mw=100.0,
        bess_mw=20.0,
        bess_mwh=80.0,
        ppaload_mw=100.0,
        simulation_years=1,
    )


@pytest.fixture(scope="session")
def solved_result(tiny_ts):
    """A real, solved OptimizationResult built from the tiny fixture timeseries."""
    scenario = Scenario(
        name="Test Scenario",
        onsw_mw=120.0,
        pv_mw=100.0,
        bess_mw=20.0,
        bess_mwh=80.0,
        ppaload_mw=100.0,
        simulation_years=1,
    )
    n = build_network(tiny_ts, scenario)
    status, condition = solve(n, scenario, tiny_ts)
    return extract_results(n, scenario, tiny_ts, status, condition)


@pytest.fixture
def energy_inputs(solved_result):
    from ppa.financial_model import energy_inputs_from_result

    return energy_inputs_from_result(solved_result)


@pytest.fixture
def pf_inputs():
    from ppa.financial_model import ProjectFinanceInputs

    # Shorter model horizon than the 40y default so the (already fast) numpy
    # pipeline stays trivially small in test output/debugging.
    return ProjectFinanceInputs(model_duration=20, operating_life=15, debt_tenor=10, ppa_tenor=10)


def make_scenario(**overrides) -> Scenario:
    return dataclasses.replace(Scenario(), **overrides)
