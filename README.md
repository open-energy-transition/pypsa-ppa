# pypsa-ppa

PyPSA-based toolkit for simulating and optimising Power Purchase Agreements (PPAs) under different scenarios.

## Overview

This project models renewable portfolios (wind, solar, battery storage) operating under long-term PPAs. It uses [PyPSA](https://pypsa.readthedocs.io) to find the least-cost hourly dispatch across a full month of real Australian NEM market data, honouring contractual delivery obligations, shortfall allowances, penalty regimes, and market interaction caps.

A Streamlit web app provides an interactive interface with four predefined case studies, a customisable scenario form, and detailed results (KPIs, financial analysis, supply mix charts).

## Setup

This project uses [pixi](https://pixi.sh) for reproducible environment management.

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

This creates a fully pinned environment (see `pixi.lock`) with all dependencies resolved from conda-forge, including PyPSA, HiGHS, Linopy, Streamlit, and SciPy.

### 3. Run the Streamlit app

```bash
pixi run app
```

The app opens at `http://localhost:8501`. Navigate through the tabs:

. **Welcome** — capabilities overview and navigation guide
1. **Case Setup** — select a predefined case study and customise parameters
2. **Get Data** — download necessary time series data
3. **Optimization** — review the scenario and click *Run Optimization*
4. **Results** — financial analysis (LCOE, IRR, NPV), daily dispatch detail
5. **Financial model** — project-finance appraisal layered on the energy-model results
6. **Sensitivity analysis** — financial-parameter sensitivity
7. **HELP** — PPA key concepts and terminology

### 4. Run the Jupyter notebook (worked example)

```bash
pixi run notebook
```

Opens the original worked example notebook at `notebooks/pypsa_ppa_example_v1.ipynb`.

## Project structure

```
pypsa-ppa/
├── streamlit_app.py             # App entry point (pixi run app)
├── pixi.toml                    # Environment definition
├── pixi.lock                    # Pinned dependency lockfile
├── data/                        # Data
│   ├── Scenario_definition.xls  # Template to define a scenario via Excel
│   └── cache                    # Cached data
│       ├── entsoe               # Cached day-ahead data
│       └── renewables_ninja     # Cached renewable profiles
├── ppa/                         # Core library — no Streamlit dependency
│   ├── counterfactuals.py       # Counterfactual comparison of PPA
│   ├── data_loader.py           # CSV loading and timeseries preparation
│   ├── financial_model_excel.py # Excel export of the Financial model
│   ├── financial_model.py       # Financial model within the UI
│   ├── financials.py            # CAPEX / LCOE / IRR / NPV / breakeven price
│   ├── industrial_profiles.py   # Reference industrial load profiles
│   ├── multi_year.py            # Simulation runner
│   ├── network.py               # PyPSA network builder
│   ├── results.py               # Result extraction into typed dataclasses
│   ├── scenario.py              # Scenario dataclass + 4 predefined case studies
│   ├── sensitivity.py           # Sensitivity analysis helpers
│   ├── solver.py                # Linopy constraints + HiGHS solve
│   └── data                     # Data handling libraries
│       ├── entsoe_client.py     # ENTSO-E support functions
│       ├── european_data.py     # Collect necessary data
│       ├── ffe_profiles.py      # Industrial default profiles
│       └── renewables_ninja.py  # Global renewable profiles
├── ui/                          # Streamlit UI layer
│   ├── charts.py                # Plotly figure builders
│   ├── scenario_form.py         # Interactive parameter form
│   ├── state.py                 # Session state accessors
│   └── tabs/                    # One module per tab
└── notebooks/
    └── pypsa_ppa_example_v1.ipynb        # Original worked example
```

## Predefined case studies

| Case study | Portfolio | Key feature |
|---|---|---|
| ⚓ The Foundation Deal | 200 MW wind + 80 MW solar, no BESS | Baseline penalty exposure without storage |
| ☀️ Solar + Storage Play | 50 MW wind + 300 MW solar + 120/480 BESS | Time-shifting via large battery |
| 📈 Merchant Hybrid | Standard mix, 90% delivery, 2× penalty | Market buy at volatile NEM prices |
| 🏢 Corporate PPA | Balanced 180/180/90 MW, 90% delivery, 1% market buy | Near-zero flexibility, premium tariff |

## Data

### Renewable & price timeseries

Market prices and renewable capacity factors are sourced from ENTSO-E (day-ahead prices) and [renewables.ninja](https://renewables.ninja) (wind/solar profiles for a user-specified location).

git c### Industrial load profiles

Offtaker demand shapes for **cement** and **steel** are derived from real measured hourly profiles published by the [Forschungsstelle für Energiewirtschaft (FfE)](https://www.ffe.de) via their open data API (`id_opendata=59`), following the approach of [PyPSA-EUR PR #1875](https://github.com/PyPSA/pypsa-eur/pull/1875). The 2017 reference year data is bundled at `ppa/data/ffe_profiles.json` and mapped to any simulation year by averaging over (month, day-of-week, hour) triplets to preserve seasonal and weekday patterns.

| Profile key | Data source | FfE sector |
|---|---|---|
| `flat` | Synthetic | — |
| `cement_plant` | FfE open data | Non-metallic Minerals (id 4) |
| `steel_eaf` | FfE open data | Iron & steel industry (id 1) |
| `green_hydrogen` | Synthetic | — |
| `data_center` | Synthetic | — |
| `aluminum_smelter` | Synthetic | — |

## Dependencies

All managed by pixi from conda-forge:

| Package | Purpose |
|---|---|
| pypsa | Energy system modelling and network optimisation |
| highspy | HiGHS LP solver |
| linopy | Linear programming backend for PyPSA |
| streamlit | Web application framework |
| plotly | Interactive charts |
| scipy | Financial analysis (IRR via Brent's method) |
| pypsatopo* | Network topology diagrams (notebook) |

\* Installed from PyPI via pixi's `[pypi-dependencies]`.
