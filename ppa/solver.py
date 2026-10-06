from __future__ import annotations

import pandas as pd
import pypsa
from ppa.scenario import Scenario

pypsa.options.general.allow_network_requests = False
pypsa.options.params.statistics.drop_zero = True
pypsa.options.params.statistics.round = 2
pypsa.options.params.optimize.log_to_console = False
pypsa.options.params.optimize.include_objective_constant = False
pypsa.options.api.new_components_api = True


def matching_period_groups(
    index: pd.DatetimeIndex, matching_period: str
) -> list[tuple[str, pd.DatetimeIndex]]:
    """Split snapshots into the calendar periods delivery is matched over.

    Returns (constraint-name suffix, snapshots) per calendar month or year.
    "hourly" yields no groups: each snapshot is its own period and the network
    has no matching-balance generators to constrain.
    """
    if matching_period == "hourly":
        return []
    if matching_period == "monthly":
        keys = index.year * 100 + index.month
    elif matching_period == "annual":
        keys = index.year
    else:
        raise ValueError(f"Unknown matching period '{matching_period}'")
    keys = pd.Index(keys)
    return [(f"_{k}", index[keys == k]) for k in keys.unique()]


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

    load = n.loads.dynamic.p_set["Load_PPAOfftake"]

    # In a multi-year sizing LP the caps must bind per calendar year: one
    # aggregate constraint over 25 years would let the optimizer concentrate all
    # shortfall/buys into the worst weather years. Single-year runs keep the
    # original single aggregate constraint (identical behavior).
    years = pd.Index(ts.index.year)
    if s.optimize_capacity and years.nunique() > 1:
        snapshot_groups = [(f"_{y}", ts.index[years == y]) for y in years.unique()]
    else:
        snapshot_groups = [("", ts.index)]

    for suffix, snaps in snapshot_groups:
        # Constraint 1: allowed shortfall cap (aggregate over period)
        period_load_mwh = float(load.loc[snaps].sum())
        allowed_shortfall_expr = gen_p.loc[snaps, "Gen_AllowedShortfall"].sum()
        m.add_constraints(
            allowed_shortfall_expr <= s.allowed_shortfall_share * period_load_mwh,
            name=f"AllowedShortfall_Limit{suffix}",
        )

        # Constraint 2: market buy cap relative to PPA delivery (only when enabled)
        if s.enable_market_buy and s.market_buy_share > 0:
            buy_expr = gen_p.loc[snaps, "Gen_BuyFromMarket"].sum()
            delivery_expr = link_p.loc[snaps, "IPPGen_to_PPAOfftake"].sum()
            m.add_constraints(
                buy_expr <= s.market_buy_share * delivery_expr,
                name=f"BuyFromMarket_Limit{suffix}",
            )

    # Constraint 3: monthly / annual matching. Energy drawn from the matching
    # account equals energy banked within each period, so delivered volume
    # nets against load per period and surplus can't be carried into the next
    # one. Snapshot weightings are uniform within a run, so unweighted sums
    # suffice (as for the caps above).
    for suffix, snaps in matching_period_groups(ts.index, s.matching_period):
        m.add_constraints(
            gen_p.loc[snaps, "Gen_MatchingDraw"].sum()
            == gen_p.loc[snaps, "Gen_MatchingBank"].sum(),
            name=f"MatchingBalance{suffix}",
        )

    # io_api="direct": hand the problem to HiGHS in memory instead of writing an
    # LP file and reading it back. Identical optimum, but ~265 MB less peak RSS
    # (~1000 → ~735 MB per solve) and faster: matters on the ~1 GB Streamlit
    # Cloud tier. assign_all_duals is left at its default (False): duals are never
    # consumed anywhere in the app, so materialising 300k+ of them is dead work.
    # Solver algorithm note: parallel interior point ("solver": "ipm") was
    # benchmarked on the 6-year 3h sizing LP and lost to the default dual
    # simplex (~180 s vs ~80 s incl. model build), so no sizing-specific
    # algorithm override is applied.
    status, condition = n.optimize.solve_model(
        solver_name=solver_name,
        io_api="direct",
    )
    return status, condition
