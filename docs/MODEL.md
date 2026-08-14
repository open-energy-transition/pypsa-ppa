# Optimization model

This page describes the linear program that sits underneath every run in the app: the network topology, the decision variables, the objective, and every constraint. It's meant for anyone who wants to check the model does what they think it does, or who wants to extend it.

The model is built with [PyPSA](https://pypsa.readthedocs.io) and [linopy](https://linopy.readthedocs.io) and solved with [HiGHS](https://highs.dev). Two places in the code build on top of PyPSA's own machinery:

- `ppa/network.py` builds the network: buses, generators, storage, links and their costs.
- `ppa/solver.py` adds the PPA-specific constraints (shortfall cap, market-buy cap) and calls the solver.
- `ppa/sizing.py` reuses the same network and solver code with capacities left free, to co-optimize the portfolio instead of dispatching a fixed one.

## Network topology

Six buses, all on a single "AC" carrier:

| Bus | What sits on it |
|---|---|
| `Bus_OnshoreWind` | `Gen_OnshoreWind` |
| `Bus_PVBESS` | `Gen_PV` and the battery, `SU_BESS` |
| `Bus_IPPGeneration` | nothing directly; it's a hub where all generation converges before being sold or delivered |
| `Bus_BuyFromMarket` | `Gen_BuyFromMarket`, the market-purchase source |
| `Bus_SellToMarket` | `Gen_SellToMarket`, a sink for merchant sales |
| `Bus_PPAOfftake` | `Load_PPAOfftake` (the contracted demand), plus `Gen_Penalty` and `Gen_AllowedShortfall` |

Five one-directional links move power between them:

| Link | From → to | Marginal cost |
|---|---|---|
| `OnshoreWind_to_IPPGeneration` | Wind → hub | 0 |
| `PVBESS_to_IPPGeneration` | PV/BESS bus → hub | 0 |
| `BuyFromMarket_to_IPPGeneration` | Market buy → hub | 0 |
| `IPPGen_to_SellToMarket` | Hub → market sale | 0 |
| `IPPGen_to_PPAOfftake` | Hub → offtaker | `transmission_cost_eur_mwh − ppa_price` |

Because these are PyPSA links, flow only goes one way (bus0 to bus1), and PV and the battery share a bus that only has one outgoing link to the hub. Put together, **the battery can only ever charge from PV generation on the same bus** (net of whatever isn't exported that hour), with no path to charge from wind or from the market. This is a real modelling choice, not an oversight, and it matters when you're trying to understand why a case study's battery does or doesn't get used.

The last link is where the PPA revenue actually shows up: its marginal cost is `transmission_cost − ppa_price`, so every MWh that flows across it earns the model `ppa_price` and costs `transmission_cost`, both applied to delivered energy regardless of whether it came from wind, PV, the battery, or a market purchase.

## Decision variables

| Variable | Bounds | Units |
|---|---|---|
| Wind / PV dispatch | `0 ≤ p(t) ≤ p_max_pu(t) · capacity` | MW |
| Wind / PV capacity (sizing mode only) | `0 ≤ capacity ≤ max_build_*_mw` | MW |
| Market buy | `0 ≤ p(t) ≤ maxbuy_mw` | MW |
| Market sell | `0 ≤ p(t) ≤ capacity` | MW |
| Penalty generator | `0 ≤ p(t) ≤ ppaload_mw` | MW |
| Allowed-shortfall generator | `0 ≤ p(t) ≤ ppaload_mw` | MW |
| Battery charge / discharge | `0 ≤ p(t) ≤ capacity` | MW |
| Battery state of charge | `0 ≤ soc(t) ≤ capacity × duration_hours` | MWh |
| Battery power capacity (sizing mode only) | `0 ≤ capacity ≤ max_build_bess_mw` | MW |
| Link flows | `0 ≤ p(t) ≤ capacity` | MW |

Links are never extendable, in either mode. In sizing mode they're just given a cap generous enough (the sum of all three max-build limits) that it never binds. They're plumbing, not investment decisions.

## Objective

PyPSA minimizes total cost:

```
minimize  Σ_t  weight(t) · Σ_component  marginal_cost(t) · dispatch(t)   +   Σ_component  annualized_capex · capacity
```

The capex term only exists in sizing mode, for the three extendable components. Marginal costs, in €/MWh:

- Wind: 0.1 (near-zero, just a tie-breaker in the solver)
- PV: 0.01
- Market buy: `spot_price(t) + market_spread`
- Market sell: `−(spot_price(t) − market_spread)` in normal dispatch mode. This is where merchant revenue comes from. **In sizing mode this is forced to 0.** That's deliberate: without it, the sizing LP would happily overbuild capacity just to sell it as merchant power, which isn't what "least-cost to serve the PPA" is supposed to mean. Sizing decisions never get credit for merchant sales.
- Penalty generator: `ppa_price × penalty_multiple` if penalties are enabled, otherwise just `ppa_price`
- Allowed-shortfall generator: 0.001 (effectively free, but a hair more expensive than genuine delivery so the solver doesn't use it needlessly)
- Battery: 0
- `IPPGen_to_PPAOfftake` link: `transmission_cost − ppa_price`, as above

Annualized capex, sizing mode only:

```
annualized_capex = capex_per_kw × 1000 × (CRF + opex_rate) × horizon_years
```

where `CRF` is the standard capital recovery factor over the project life at the discount rate, and `horizon_years` scales the annual cost down to however much of a year the sizing run actually covers (see below). The battery's capex is expressed per kWh and multiplied by its fixed duration to get an equivalent per-MW figure.

Put together: in sizing mode the model minimizes opex plus capex minus PPA delivery revenue plus transmission cost, with merchant sales earning nothing. That's a genuine least-cost-to-serve-the-contract objective, not a profit-maximizing one.

## Constraints

**Nodal balance.** At every bus, in every snapshot, generation plus storage discharge minus storage charge plus net link inflow equals load. This is standard PyPSA machinery, not custom code, but it's worth stating explicitly for the offtaker bus: `PPA delivery + penalty + allowed shortfall = contracted load`. The penalty and shortfall generators exist purely so this equation can always be satisfied. The model is never infeasible just because renewables underperform: it just gets expensive.

**Battery state of charge.** Standard storage dynamics: `soc(t) = soc(t−1) + η_charge · charge(t) − discharge(t) / η_discharge`, cyclic over the whole horizon (the end-of-horizon SoC has to equal the start, so the model can't just start full for free). Charge and discharge efficiencies default to 90% each and are scenario parameters.

**Battery duration is fixed.** In sizing mode, only the battery's power rating is a free variable; its energy capacity is tied to it by a fixed hours-of-duration ratio taken from the scenario (power × duration = energy). The model never independently chooses how many hours of storage to build; you set that ratio, and it sizes the MW.

**Allowed shortfall is capped.** If shortfall allowance is enabled:

```
Σ_t allowed_shortfall(t)  ≤  (1 − required_delivery_share) × Σ_t contracted_load(t)
```

In multi-year sizing runs this is enforced per calendar year rather than once over the whole horizon, specifically so the optimizer can't dump the entire multi-year shortfall allowance into the single worst weather year.

**Market purchases are capped relative to delivery.** If market buy is enabled with a nonzero share:

```
Σ_t market_buy(t)  ≤  market_buy_share × Σ_t delivered_to_offtaker(t)
```

Same per-year grouping in multi-year sizing runs, same reasoning.

**Build limits (sizing mode).** Each extendable technology has a hard cap on installed capacity, set directly on the component rather than as a separate constraint: wind ≤ `max_build_wind_mw`, PV ≤ `max_build_pv_mw`, battery ≤ `max_build_bess_mw`.

## Sizing mode: how it stays fast

Running a full hourly investment LP over 25 years just isn't practical, so `ppa/sizing.py` trims the problem down in three ways before handing it to the solver, and none of them touch the dispatch-mode LP used for the actual multi-year results:

1. **Weather-year capping.** The cached weather and price data only spans a handful of years, and the multi-year simulation cycles through them. A 25-year sizing horizon made up of six repeating years is mostly duplicate information, so the sizing LP is capped at one full cycle of the cached years rather than the full requested horizon.
2. **Time-block coarsening.** The hourly timeseries is block-averaged into coarser snapshots (3 hours by default, configurable from 1 to 6 in the UI), with the snapshot weightings set to match, so energy and cost totals still integrate correctly over real hours even though there are fewer of them. This is an approximation: a battery's ability to arbitrage within a 3-hour window is invisible to the sizing LP, since it only sees the block average. The sized capacities have been checked against a full hourly solve and come out within a few percent, at roughly an order of magnitude less compute.
3. **Battery capex correction for degradation.** Because a single LP can't vary a storage duration ratio over time, sizing runs approximate multi-year battery degradation by averaging the degradation factor over the sizing horizon and adjusting the effective capex accordingly, rather than modelling year-by-year fade explicitly.

Once sizing picks capacities, they're written into a fixed-capacity scenario and handed to the same hourly multi-year dispatch used everywhere else. Nothing downstream needs to know a sizing step ever happened.

## Multi-year dispatch and parallelism

Outside of sizing mode, each simulated year is solved independently at full hourly resolution, with technology degradation applied by scaling down capacity year over year rather than by re-solving anything dynamic. Years run in parallel using separate processes, not threads: the solver stack isn't thread-safe, and threads only ever gave the appearance of parallelism anyway. The number of workers is automatically capped based on available memory, reading the container's actual memory limit where available, so the app degrades to running years serially rather than crashing on memory-constrained hosts like a small cloud instance. This is transparent to the user; the "parallel workers" control in the Optimization tab is a ceiling, not a guarantee.
