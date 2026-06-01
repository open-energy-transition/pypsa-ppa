from __future__ import annotations

import pandas as pd
import pypsa

from ppa.scenario import Scenario


def solve(
    n: pypsa.Network,
    scenario: Scenario,
    ts: pd.DataFrame,
    solver_name: str = "highs",
) -> tuple[str, str]:
    """Add custom Linopy constraints and solve the network. Returns (status, condition)."""
    s = scenario

    # Two-step workflow: create_model() → inject constraints → solve_model()
    m = n.optimize.create_model(
        include_objective_constant=True,
    )

    gen_p = m.variables["Generator-p"]
    link_p = m.variables["Link-p"]

    total_load_mwh = float(n.loads_t.p_set["Load_PPAOfftake"].sum())

    # Constraint 1 — allowed shortfall cap (aggregate over period)
    allowed_shortfall_expr = gen_p.loc[:, "Gen_AllowedShortfall"].sum()
    m.add_constraints(
        allowed_shortfall_expr <= s.allowed_shortfall_share * total_load_mwh,
        name="AllowedShortfall_Limit",
    )

    # Constraint 2 — market buy cap relative to PPA delivery (only when enabled)
    if s.enable_market_buy and s.market_buy_share > 0:
        buy_expr = gen_p.loc[:, "Gen_BuyFromMarket"].sum()
        delivery_expr = link_p.loc[:, "IPPGen_to_PPAOfftake"].sum()
        m.add_constraints(
            buy_expr <= s.market_buy_share * delivery_expr,
            name="BuyFromMarket_Limit",
        )

    status, condition = n.optimize.solve_model(
        solver_name=solver_name,
        assign_all_duals=True,
    )
    return status, condition
