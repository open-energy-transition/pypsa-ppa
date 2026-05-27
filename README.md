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

1. **Welcome** — capabilities overview and navigation guide
2. **Introduction to PPAs** — key concepts and terminology
3. **Case Study Definition** — select a predefined case study and customise parameters
4. **Optimization** — review the scenario and click *Run Optimization*
5. **Results Overview** — KPIs, supply mix chart, revenue breakdown
6. **Results Deep Dive** — financial analysis (LCOE, IRR, NPV), daily dispatch detail

### 4. Run the Jupyter notebook (worked example)

```bash
pixi run notebook
```

Opens the original worked example notebook at `notebooks/pypsa_ppa_example_v1.ipynb`.

## Project structure

```
pypsa-ppa/
├── streamlit_app.py          # App entry point (pixi run app)
├── pixi.toml                 # Environment definition
├── pixi.lock                 # Pinned dependency lockfile
├── ppa/                      # Core library — no Streamlit dependency
│   ├── scenario.py           # Scenario dataclass + 4 predefined case studies
│   ├── data_loader.py        # CSV loading and timeseries preparation
│   ├── network.py            # PyPSA network builder
│   ├── solver.py             # Linopy constraints + HiGHS solve
│   ├── results.py            # Result extraction into typed dataclasses
│   └── financials.py         # CAPEX / LCOE / IRR / NPV / breakeven price
├── ui/                       # Streamlit UI layer
│   ├── state.py              # Session state accessors
│   ├── charts.py             # Plotly figure builders
│   ├── scenario_form.py      # Interactive parameter form
│   └── tabs/                 # One module per tab
├── data/
│   ├── march_2025_pypsa_timeseries.csv   # Real NEM hourly data (March 2025, NSW)
│   └── PPA_scenario_definition.xlsx      # Excel-based scenario config (notebook use)
└── notebooks/
    └── pypsa_ppa_example_v1.ipynb        # Original worked example
```

## Case studies

| Case study | Portfolio | Key feature |
|---|---|---|
| ⚓ The Foundation Deal | 200 MW wind + 80 MW solar, no BESS | Baseline penalty exposure without storage |
| ☀️ Solar + Storage Play | 50 MW wind + 300 MW solar + 120/480 BESS | Time-shifting via large battery |
| 📈 Merchant Hybrid | Standard mix, 90% delivery, 2× penalty | Market buy at volatile NEM prices |
| 🏢 Corporate PPA | Balanced 180/180/90 MW, 90% delivery, 1% market buy | Near-zero flexibility, premium tariff |

## Data

The timeseries data covers **March 2025** from the Australian National Electricity Market (NSW dispatch region), sourced via [NEMOSIS](https://github.com/UNSW-CEEM/NEMOSIS):

- Hourly wind and solar capacity factors
- NSW wholesale spot electricity prices

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
