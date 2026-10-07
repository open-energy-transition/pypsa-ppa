"""End-to-end: drive the real Streamlit app through a full run per matching period.

Uses Streamlit's AppTest to execute `streamlit_app.py` in-process the way a
user would: select the matching period in Case Setup, apply, run a one-year
optimization from the Optimization tab, then open the Results and Financial
Model tabs. The run uses the DE_LU price and CF data committed under
`data/cache/` for the base scenario location, so no network access is needed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from ppa.scenario import MATCHING_PERIODS

REPO_ROOT = Path(__file__).parent.parent
TAB_CASE_SETUP = "| 1. 🔬 Case Setup"
TAB_OPTIMIZATION = "| 3. ⚙️ Optimization"
TAB_RESULTS = "| 4. 🔍 Results"
TAB_FINANCIAL = "| 5. 🏦 Financial Model"
RUN_TIMEOUT_S = 600


def _run_on_tab(at: AppTest, label: str, timeout: float | None = None) -> None:
    """Rerun the app with `label` as the active tab.

    The app's st.tabs is keyed "main_tabs" with on_change="rerun", so only the
    selected tab's body executes. AppTest doesn't re-send the tab selection on
    later reruns (it isn't a widget in its element tree), so it is pinned via
    session state on every run.
    """
    at.session_state["main_tabs"] = label
    at.run(timeout=timeout)
    _assert_clean(at)


def _assert_clean(at: AppTest) -> None:
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error, [e.value for e in at.error]


def _run_app(matching_period: str) -> AppTest:
    at = AppTest.from_file(str(REPO_ROOT / "streamlit_app.py"), default_timeout=60)
    at.run()
    _assert_clean(at)

    _run_on_tab(at, TAB_CASE_SETUP)
    at.selectbox(key="sf_matching_period").set_value(matching_period)
    at.number_input(key="sf_sim_years").set_value(1)
    next(b for b in at.button if b.label == "Apply changes").click()
    _run_on_tab(at, TAB_CASE_SETUP)
    assert at.session_state["scenario"].matching_period == matching_period

    _run_on_tab(at, TAB_OPTIMIZATION)
    at.selectbox(key="opt_max_workers").set_value(1)
    at.button(key="opt_run_eu").click()
    _run_on_tab(at, TAB_OPTIMIZATION, timeout=RUN_TIMEOUT_S)
    assert "multi_year_results" in at.session_state
    return at


@pytest.fixture(scope="module")
def app_runs() -> dict[str, AppTest]:
    return {period: _run_app(period) for period in MATCHING_PERIODS}


@pytest.mark.parametrize("period", MATCHING_PERIODS)
def test_app_run_uses_selected_matching_period(app_runs, period):
    at = app_runs[period]
    results = at.session_state["multi_year_results"]
    assert len(results) == 1
    res = results[0]
    assert res.scenario.matching_period == period
    assert (res.solver_status, res.solver_condition) == ("ok", "optimal")
    # Optimization tab's scenario summary reflects the selection
    assert any(f"Matching: **{period}**" in md.value for md in at.markdown)


@pytest.mark.parametrize("period", MATCHING_PERIODS)
def test_app_run_volumes_balance_per_matching_period(app_runs, period):
    res = app_runs[period].session_state["multi_year_results"][0]
    d = res.dispatch
    load = d.ppa_delivery + d.allowed_shortfall + d.penalty_gen
    idx = load.index
    keys = {"hourly": idx, "monthly": idx.month, "annual": idx.year}[period]
    served = load.groupby(keys).sum()
    # The served total is the load whatever the matching period; what changes
    # is only the window over which it must add up.
    expected = res.summary.total_load_mwh
    assert served.sum() == pytest.approx(expected, rel=1e-6)
    if period == "hourly":
        assert d.ppa_delivery.max() <= res.scenario.ppaload_mw + 1e-6
        assert res.summary.netted_delivery_mwh == 0.0


def test_app_hourly_matching_never_over_delivers(app_runs):
    res = app_runs["hourly"].session_state["multi_year_results"][0]
    assert res.summary.netted_delivery_mwh == 0.0
    assert res.dispatch.ppa_delivery.max() <= res.scenario.ppaload_mw + 1e-6


@pytest.mark.parametrize("period", ["monthly", "annual"])
def test_app_netted_matching_banks_surplus_across_hours(app_runs, period):
    """With 400 MW of wind + PV against a 100 MW flat load, a real weather year
    has surplus hours to bank and calm nights to cover, so netting is used."""
    res = app_runs[period].session_state["multi_year_results"][0]
    assert res.summary.netted_delivery_mwh > 0.0
    assert res.dispatch.ppa_delivery.max() > res.scenario.ppaload_mw + 1e-6
    # Netting never lets delivery exceed the contracted volume
    assert res.summary.ppa_delivered_mwh <= res.summary.total_load_mwh + 1e-6


def test_app_monthly_matching_settles_each_month(app_runs):
    res = app_runs["monthly"].session_state["multi_year_results"][0]
    d = res.dispatch
    month = d.ppa_delivery.index.month
    delivered = d.ppa_delivery.groupby(month).sum()
    load = (d.ppa_delivery + d.allowed_shortfall + d.penalty_gen).groupby(month).sum()
    flat_month_load = res.scenario.ppaload_mw * d.ppa_delivery.groupby(month).size()
    # Flat base-scenario load: each month's served total is that month's load,
    # and no month delivers more than its own load.
    assert load.to_numpy() == pytest.approx(flat_month_load.to_numpy(), rel=1e-6)
    assert (delivered <= flat_month_load + 1e-6).all()


@pytest.mark.parametrize("period", ["hourly", "annual"])
@pytest.mark.parametrize("tab", [TAB_RESULTS, TAB_FINANCIAL])
def test_app_downstream_tabs_render_after_run(app_runs, period, tab):
    _run_on_tab(app_runs[period], tab)
