"""Render the optimisation tab's near-optimal alternatives (MGA) panel with
Streamlit's AppTest, from a hand-built MGA result (no LP solve needed)."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest


def _mga_panel_app():
    from ppa.scenario import Scenario
    from ppa.sizing import MGAAlternative, MGAResult, SizedCapacities
    from ui import state
    from ui.tabs import optimization

    def alt(key, label, wind, pv, bess, dc):
        return MGAAlternative(
            key=key,
            label=label,
            stakeholder="Test",
            sized=SizedCapacities(wind, pv, bess, bess * 4, "ok", "optimal", 1, False, 3),
            cost_increase=dc,
            total_cost_eur_per_yr=30e6 * (1 + dc),
            capex_eur=250e6,
            re_matching_share=0.85,
            market_buy_share=0.04,
            surplus_share=0.2,
        )

    s = Scenario(optimize_capacity=True)
    if not state.has_mga_result():
        result = MGAResult(
            slack=0.05,
            optimum=alt("optimum", "Least-cost optimum", 170, 60, 0, 0.0),
            alternatives=[
                alt("max_wind", "Max wind", 230, 40, 0, 0.05),
                alt("min_capex", "Lowest upfront capex", 146, 35, 0, 0.05),
            ],
            notes=["Min BESS: skipped, already zero at the optimum."],
        )
        state.set_mga_result(result, s)
    optimization._render_mga(s, 1, True)


def test_mga_panel_renders_table_charts_and_simulate_controls():
    at = AppTest.from_function(_mga_panel_app, default_timeout=60).run()
    assert not at.exception
    assert at.expander[0].label == "Near-optimal alternatives (MGA)"
    df = at.dataframe[0].value
    assert list(df.index) == ["▶ Least-cost optimum", "Max wind", "Lowest upfront capex"]
    assert df.loc["Max wind", "Wind (MW)"] == 230
    # The active (optimum) portfolio can't be re-adopted; picking another can
    assert at.button(key="opt_mga_simulate").disabled
    at.selectbox(key="opt_mga_choice").set_value("max_wind").run()
    assert not at.button(key="opt_mga_simulate").disabled
    assert not at.warning  # scenario unchanged → not stale
