# pypsa-ppa

A [PyPSA](https://pypsa.readthedocs.io)-based toolkit for exploring how a renewable energy Power Purchase Agreement (PPA) actually performs once you put real weather and market prices behind it.

> **Proof of concept.** This is a research and demonstration tool, not a production planning system. Data, cost assumptions and results throughout are illustrative. Nothing here should be used to make real investment, procurement or legal decisions without independent verification. It's provided as-is, with no warranty; see [LICENSE](LICENSE).

## What this actually does

You describe a portfolio (wind, solar, optionally battery storage) and an offtaker under a PPA contract with a delivery obligation, a shortfall allowance, and a penalty for missing it. The toolkit builds an hourly linear program, dispatches the portfolio against real European day-ahead prices and renewable capacity factors, and reports whether the contract gets met, what it costs to serve, and what the underlying project economics look like.

It can also flip that around and size the portfolio itself: instead of telling it how much wind and solar to build, you give it a budget ceiling per technology and it works out the least-cost mix to serve the contract.

On top of the energy-side simulation sits a full project-finance model (debt sizing, tax, depreciation, IRR) and a sensitivity analysis tool that can explore financial assumptions instantly without re-running the optimization.

A Streamlit app ties all of this together with four predefined case studies and a fully customizable scenario form.

## Setup

This project uses [pixi](https://pixi.sh) for environment management. A `requirements.txt` is also provided for plain pip installs (for example, deploying to Streamlit Community Cloud).

### 1. Install pixi

```bash
curl -fsSL https://pixi.sh/install.sh | bash
# Restart your shell or run: source ~/.bashrc
```

### 2. Install the environment

```bash
cd pypsa-ppa
pixi install
```

This resolves a fully pinned environment (`pixi.lock`) from conda-forge: PyPSA, HiGHS, Linopy, Streamlit, and the rest of the stack.

### 3. Run the app

```bash
pixi run app
```

Opens at `http://localhost:8501`.

### 4. Run the worked-example notebook

```bash
pixi run notebook
```

Opens `notebooks/pypsa_ppa_example_v1.ipynb`, the original single-scenario worked example this project grew out of. It predates the European data pipeline and multi-year simulation described below, so treat it as historical context rather than the current entry point. The Streamlit app is where active development happens.

### Data access

The app needs free API tokens to download market and weather data:

- [ENTSO-E Transparency Platform](https://transparency.entsoe.eu) for day-ahead prices
- [renewables.ninja](https://www.renewables.ninja) for wind and solar capacity factors

Tokens are entered in the **Get Data** tab and kept only for the session, never written to disk. A handful of locations are already cached under `data/cache/` so you can try the app before requesting your own tokens.

## Walking through the app

The tabs run roughly in the order you'd use them:

| Tab | What it's for |
|---|---|
| **Welcome** | Orientation: what the tool does and where the data comes from |
| **1. Case Setup** | Pick one of four predefined case studies, or open the form and build your own scenario from scratch |
| **2. Get Data** | Check what's cached for your chosen locations, download whatever's missing, or upload your own price/weather data instead |
| **3. Optimization** | Run the simulation: either a single reference month for a quick look, or the full multi-year run |
| **4. Results** | Hourly dispatch, generation stats, and a comparison against alternative procurement strategies (spot-only, forward-hedged, blended) |
| **5. Financial Model** | The full levered project-finance model, run on top of the energy results, with an Excel export |
| **6. Sensitivity Analysis** | Instant what-if and tornado-chart analysis over financial assumptions, no re-run needed |
| **7. HELP** | A primer on PPA structures and the terminology used throughout the app |

## Scenario model

Every run is driven by a `Scenario` (`ppa/scenario.py`), which covers, broadly:

- **Portfolio**: wind/solar/battery capacity, or, in sizing mode, per-technology build ceilings and let the optimizer choose
- **Contract terms**: offtake volume, load shape, PPA tariff, required delivery share, shortfall allowance, penalty multiple
- **Market interaction**: whether market buying/selling is allowed, and how much
- **Locations**: offtaker, PV and wind sites can each sit at a different lat/lon; the offtaker's location determines the price zone
- **Simulation**: number of years, first simulation year, price escalation, technology degradation
- **Financial assumptions**: capex, opex, discount rate, target IRR

### Predefined case studies

| Case study | Offtaker | Portfolio | Delivery / penalty | Notes |
|---|---|---|---|---|
| ⚓ The Foundation Deal | Cement plant | 300 MW wind + 80 MW solar, no battery | 70% / 1.5× | Wind-dominant baseline, market buying disabled entirely |
| ☀️ Solar + Storage Play | Green hydrogen electrolyser | 80 MW wind + 450 MW solar + 50 MW / 200 MWh battery | 75% / 1.5× | PV-heavy with a 4-hour battery for time-shifting |
| 📈 Merchant Hybrid | Steel EAF | 250 MW wind + 200 MW solar + 60 MW / 240 MWh battery | 90% / 2.0× | Tighter obligation, market buying allowed, wider spread |
| 🏢 Corporate PPA | Data centre | 280 MW wind + 200 MW solar + 90 MW / 360 MWh battery | 90% / 1.2× | Premium tariff, near-zero market buying, 15-year term |

Each case study also carries its own offtaker load shape (see below) and storyline in the Case Setup tab. Everything not listed above falls back to the scenario defaults.

### Capacity co-optimization

Toggle "Co-optimize capacities & dispatch" in the form and the sliders for wind/solar/battery MW turn into build ceilings instead. The optimizer sizes all three together to minimize the cost of serving the contract. Merchant sales earn nothing during sizing, specifically so it doesn't overbuild just to sell into the market. The battery's power rating is optimized; its duration (hours of storage) stays fixed at whatever ratio you set.

Because a full hourly 25-year investment LP isn't practical, this runs at a coarser time resolution (3-hour blocks by default) over a capped horizon, then hands the resulting capacities to the normal hourly multi-year dispatch for the numbers you actually see. See [docs/MODEL.md](docs/MODEL.md) for exactly how that approximation works and how well it holds up against a full hourly solve.

## The optimization model, briefly

The energy-side model is a linear program: wind and solar dispatch against their capacity factors, a battery that can charge from either wind or solar but not from the market, representing a co-located renewables-plus-storage plant, a market-buy and market-sell option, and a penalty generator that makes the model always solvable even when the portfolio can't fully cover the contract, just expensive to rely on. The contract's shortfall allowance and any market-buy limit are enforced as caps relative to total load or delivery, computed per calendar year in multi-year sizing runs so the optimizer can't concentrate all its slack into one bad weather year.

The full variable list, objective function and every constraint, with file and line references, are written up in [docs/MODEL.md](docs/MODEL.md).

## Financial model

Two separate models live in this toolkit:

- A quick unlevered LCOE/IRR/NPV check, shown right in the Optimization and Results tabs.
- A full levered project-finance model (the Financial Model tab): debt sized to a DSCR target across contracted and uncontracted revenue, tax with loss carry-forward, book and tax depreciation, Project IRR and Equity IRR, and a live-formula Excel export with a full hourly sheet per simulated year.

The levered model was ported from an Excel-based project-finance workbook and validated against it: on a reference scenario it reproduces gearing, Project IRR and Equity IRR within about 0.3 percentage points.

The Sensitivity Analysis tab runs on top of this model's inputs; it varies 24 financial parameters across capex, opex, revenue, indexation, debt and tax, and updates results instantly without touching PyPSA. Anything that would actually change dispatch, like capacity or delivery share, still needs a re-run in the Optimization tab.

Full methodology in [docs/FINANCIAL_MODEL.md](docs/FINANCIAL_MODEL.md).

## Locations and market data

Offtaker, PV and wind sites are independent lat/lon points. The offtaker's location determines the price zone via a nearest-anchor lookup across roughly 40 European ENTSO-E bidding zones (handling multi-zone countries like Italy, Norway and Sweden), with a manual override available if the automatic pick is wrong for a border location. Great Britain is intentionally excluded: ENTSO-E stopped publishing GB day-ahead prices after Brexit.

An optional transmission/grid-use charge (€/MWh) applies to every MWh actually delivered to the offtaker, regardless of source, so it factors into both the dispatch decision and the reported margin.

Renewable capacity factors and day-ahead prices are cached under `data/cache/` per location and price zone, so a scenario in Italy doesn't accidentally reuse German data. That used to be a real bug, before locations were made explicit per asset.

### Bringing your own data

If you don't want to rely on ENTSO-E and renewables.ninja, the Get Data tab can also produce a CSV template pre-filled with whatever's already cached for your scenario's locations, covering every weather year the app cycles through. Fill in day-ahead prices and PV/wind capacity factors for any subset of years and re-upload it: those years use your data instead, and every other year keeps using downloaded or cached data as normal.

### Offtaker load profiles

| Profile | Source | Typical load factor |
|---|---|---|
| Flat | Synthetic constant | 100% |
| Cement plant | Real hourly data from [FfE](https://www.ffe.de) open data | ~68% |
| Steel EAF | Real hourly data from FfE open data | ~97% |
| Green hydrogen electrolyser | Synthetic, flexes toward cheap renewable hours | ~78% |
| Data centre | Synthetic, near-flat | ~88% |
| Aluminium smelter | Synthetic | ~97% |

The two FfE-derived profiles come from real measured hourly load data (2017 reference year, following the approach of [PyPSA-EUR PR #1875](https://github.com/PyPSA/pypsa-eur/pull/1875)), mapped onto any simulation year by averaging over matching month/weekday/hour triplets so the seasonal and weekly pattern survives even though the underlying data is a single fixed year.

## Project structure

```
pypsa-ppa/
├── streamlit_app.py             # App entry point (pixi run app)
├── pixi.toml / pixi.lock        # Environment definition and lockfile
├── requirements.txt             # Pinned pip install for non-pixi deployments
├── docs/
│   ├── MODEL.md                 # Full optimization model formulation
│   └── FINANCIAL_MODEL.md       # Full financial model methodology
├── data/
│   └── cache/                   # Cached ENTSO-E prices and renewables.ninja CFs
├── ppa/                          # Core library, no Streamlit dependency
│   ├── scenario.py               # Scenario dataclass + predefined case studies
│   ├── network.py                # PyPSA network builder
│   ├── solver.py                 # PPA-specific constraints + HiGHS solve
│   ├── sizing.py                 # Capacity co-optimization
│   ├── multi_year.py             # Multi-year simulation runner (parallel, memory-aware)
│   ├── results.py                # Result extraction into typed dataclasses
│   ├── financials.py             # Quick unlevered CAPEX/LCOE/IRR/NPV
│   ├── financial_model.py        # Levered project-finance model
│   ├── financial_model_excel.py  # Live-formula Excel export of the financial model
│   ├── sensitivity.py            # Sensitivity analysis engine
│   ├── counterfactuals.py        # PPA vs spot/forward/blended procurement comparison
│   ├── industrial_profiles.py    # Offtaker load profile library
│   ├── data_loader.py            # Legacy single-CSV timeseries loader
│   └── data/                     # External data sourcing
│       ├── bidding_zones.py      # Lat/lon to ENTSO-E zone mapping
│       ├── entsoe_client.py      # ENTSO-E day-ahead price fetch/cache
│       ├── european_data.py      # Assembles per-scenario hourly timeseries
│       ├── renewables_ninja.py   # Wind/PV capacity factor fetch/cache
│       └── ffe_profiles.json     # Cached FfE 2017 reference load data
├── ui/                           # Streamlit UI layer
│   ├── scenario_form.py          # The full interactive parameter form
│   ├── state.py                  # Session state accessors
│   └── tabs/                     # One module per tab
└── notebooks/
    └── pypsa_ppa_example_v1.ipynb  # Original single-scenario worked example
```

## Dependencies

Managed by pixi from conda-forge, with a matching `requirements.txt` for pip-based deployments:

| Package | Purpose |
|---|---|
| pypsa | Energy system modelling and network optimization |
| highspy | HiGHS LP solver |
| linopy | Linear programming backend for PyPSA |
| streamlit | Web application framework |
| plotly | Interactive charts |
| scipy | Financial analysis (IRR via Brent's method) |
| entsoe-py | ENTSO-E Transparency Platform client |
| folium / streamlit-folium | Interactive location map in the scenario form |
| pypsatopo | Network topology diagrams (notebook only, installed from PyPI) |

## Known limitations

Worth knowing before you rely on this for anything beyond exploration:

- There's no automated test suite yet. Changes are checked manually and against the financial model's source workbook.
- The capacity sizing LP is a time-coarsened approximation, not an exact hourly solve (see [docs/MODEL.md](docs/MODEL.md)).
- Cached weather and price data currently spans 2018-2024; multi-year simulations beyond that cycle through the cached years.
- Great Britain isn't supported as a bidding zone, since ENTSO-E doesn't publish GB day-ahead prices post-Brexit.

## License

MIT, see [LICENSE](LICENSE). This is a proof-of-concept research tool; use the results accordingly.
