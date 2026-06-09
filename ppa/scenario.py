from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from ppa.industrial_profiles import PROFILE_KEYS


@dataclass
class Scenario:
    name: str = "Custom Scenario"

    # Feature toggles
    include_bess: bool = True
    enable_market_buy: bool = True
    enable_market_sell: bool = True
    enable_shortfall: bool = True
    enable_penalty: bool = True
    run_financial_analysis: bool = True
    enable_counterfactual: bool = True

    # Counterfactual sourcing
    cal_forward_price: float = 85.0
    cal_hedge_fraction: float = 0.80

    # Portfolio sizing
    onsw_mw: float = 250.0
    pv_mw: float = 150.0
    bess_mw: float = 60.0
    bess_mwh: float = 240.0
    bess_efficiency_store: float = 0.90
    bess_efficiency_dispatch: float = 0.90

    # PPA contract terms
    ppaload_mw: float = 100.0
    load_profile: str = "flat"  # key into ppa.industrial_profiles.PROFILE_INFO
    ppa_price: float = 100.0
    pen_mult: float = 1.5
    required_delivery_share: float = 0.75
    market_buy_share: float = 0.05
    market_spread: float = 0.10

    # Operational (single-day mode)
    chosen_day: str = "2025-03-15"

    # Multi-year simulation
    simulation_years: int = 25
    first_sim_year: int = 2025
    price_escalation_rate: float = 0.02  # annual escalation applied to base market prices

    # Technology degradation (compound per year, applied from year 1 onward)
    pv_degradation_rate: float = 0.005    # 0.5%/yr — industry standard for crystalline Si
    wind_degradation_rate: float = 0.005  # 0.5%/yr
    bess_degradation_rate: float = 0.020  # 2.0%/yr usable capacity fade

    # European location (lat/lon for renewables.ninja CF downloads)
    lat: float = 51.5
    lon: float = 10.0

    # Financial — European 2024 benchmarks
    wind_capex_per_kw: float = 1200.0   # €/kW, EU onshore wind
    pv_capex_per_kw: float = 750.0      # €/kW, EU utility-scale PV
    bess_capex_per_kwh: float = 380.0   # €/kWh, EU BESS
    opex_rate: float = 0.02
    project_life_yrs: int = 25
    discount_rate: float = 0.08
    target_irr: float = 0.10

    # ── Derived properties ─────────────────────────────────────────────────────

    @property
    def bess_max_hours(self) -> float:
        if self.include_bess and self.bess_mw > 0:
            return self.bess_mwh / self.bess_mw
        return 4.0

    @property
    def allowed_shortfall_share(self) -> float:
        return (1.0 - self.required_delivery_share) if self.enable_shortfall else 0.0

    @property
    def effective_bess_mw(self) -> float:
        return self.bess_mw if self.include_bess else 0.0

    @property
    def effective_bess_mwh(self) -> float:
        return self.bess_mwh if self.include_bess else 0.0

    @property
    def maxbuy_mw(self) -> float:
        return self.ppaload_mw if self.enable_market_buy else 0.0

    @property
    def maxsell_mw(self) -> float:
        return (self.onsw_mw + self.pv_mw + self.effective_bess_mw) if self.enable_market_sell else 0.0

    @property
    def penalty_price(self) -> float:
        return self.ppa_price * self.pen_mult if self.enable_penalty else self.ppa_price

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


BASE_SCENARIO = Scenario()


@dataclass
class CaseStudy:
    id: str
    name: str
    subtitle: str
    storyline: str
    icon: str
    overrides: dict = field(default_factory=dict)


CASE_STUDIES: list[CaseStudy] = [
    CaseStudy(
        id="foundation_deal",
        name="The Foundation Deal",
        subtitle="Cement plant offtaker, wind-dominant, no storage",
        icon="⚓",
        storyline=(
            "A first-mover IPP signs a 10-year PPA with a cement plant at €90/MWh. "
            "The portfolio is wind-dominant with no storage and no market flexibility — a pure baseline "
            "to understand penalty exposure. The cement load runs near-continuous but drops sharply "
            "during its Sunday maintenance window. Can onshore wind alone hit a 70% delivery obligation "
            "against this near-baseload industrial demand in central Europe?"
        ),
        overrides={
            "name": "The Foundation Deal",
            "onsw_mw": 300.0,
            "pv_mw": 80.0,
            "bess_mw": 0.0,
            "bess_mwh": 0.0,
            "include_bess": False,
            "enable_market_buy": False,
            "enable_market_sell": True,
            "ppa_price": 90.0,
            "required_delivery_share": 0.70,
            "market_buy_share": 0.0,
            "pen_mult": 1.5,
            "load_profile": "cement_plant",
        },
    ),
    CaseStudy(
        id="solar_bess",
        name="Solar + Storage Play",
        subtitle="Green H₂ electrolyser offtaker, PV-heavy with 4h BESS",
        icon="☀️",
        storyline=(
            "A developer pairs a large PV array with a 4-hour BESS serving a green hydrogen electrolyser. "
            "The electrolyser's flexible demand naturally aligns with solar generation — ramping up at midday "
            "and backing off during evening grid peaks — making it an ideal PPA offtaker for a solar-heavy portfolio. "
            "Market purchases are disabled to maintain renewable additionality. "
            "Does the demand flexibility of the electrolyser help or hinder delivery obligations compared to flat load?"
        ),
        overrides={
            "name": "Solar + Storage Play",
            "onsw_mw": 80.0,
            "pv_mw": 450.0,
            "bess_mw": 120.0,
            "bess_mwh": 480.0,
            "include_bess": True,
            "enable_market_buy": False,
            "enable_market_sell": True,
            "ppa_price": 90.0,
            "required_delivery_share": 0.75,
            "market_buy_share": 0.0,
            "load_profile": "green_hydrogen",
        },
    ),
    CaseStudy(
        id="merchant_hybrid",
        name="Merchant Hybrid",
        subtitle="Steel EAF offtaker, high obligation, 2× penalty",
        icon="📈",
        storyline=(
            "An aggressive IPP structure serves a steel Electric Arc Furnace (EAF) with a 90% delivery obligation "
            "and a generous 15% market buy allowance. The EAF's batch melting cycles create highly variable demand — "
            "spiking at ~95% during each heat then dropping to ~15% between charges. "
            "The penalty regime is strict at 2× the tariff. "
            "Does the optimizer exploit the EAF's idle periods for market sales, and can BESS bridge the delivery gaps?"
        ),
        overrides={
            "name": "Merchant Hybrid",
            "onsw_mw": 250.0,
            "pv_mw": 200.0,
            "bess_mw": 60.0,
            "bess_mwh": 240.0,
            "include_bess": True,
            "enable_market_buy": True,
            "enable_market_sell": True,
            "ppa_price": 95.0,
            "required_delivery_share": 0.90,
            "market_buy_share": 0.15,
            "pen_mult": 2.0,
            "market_spread": 0.50,
            "load_profile": "steel_eaf",
        },
    ),
    CaseStudy(
        id="corporate_ppa",
        name="Corporate PPA",
        subtitle="Data-centre offtaker, premium price, near-zero market buy",
        icon="🏢",
        storyline=(
            "A European corporation signs a 15-year virtual PPA for its data-centre fleet at €105/MWh. "
            "The data-centre load is near-flat with a modest business-hours peak — a demanding obligation "
            "for an RE portfolio. Market supplementation is capped at 1% to preserve additionality claims. "
            "Can a balanced wind + solar + BESS portfolio hit a 90% SLA against a near-constant high load "
            "with almost no market flexibility?"
        ),
        overrides={
            "name": "Corporate PPA",
            "onsw_mw": 280.0,
            "pv_mw": 200.0,
            "bess_mw": 90.0,
            "bess_mwh": 360.0,
            "include_bess": True,
            "enable_market_buy": True,
            "enable_market_sell": True,
            "ppa_price": 105.0,
            "required_delivery_share": 0.90,
            "market_buy_share": 0.01,
            "pen_mult": 1.2,
            "load_profile": "data_center",
        },
    ),
]

CASE_STUDIES_BY_ID: dict[str, CaseStudy] = {cs.id: cs for cs in CASE_STUDIES}


def load_case_study(cs: CaseStudy) -> Scenario:
    return dataclasses.replace(BASE_SCENARIO, **cs.overrides)


def validate_scenario(s: Scenario, available_days: list[str] | None = None) -> list[str]:
    errors: list[str] = []
    if s.onsw_mw < 0:
        errors.append("Onshore wind capacity must be ≥ 0 MW.")
    if s.pv_mw < 0:
        errors.append("Solar PV capacity must be ≥ 0 MW.")
    if s.include_bess and s.bess_mw <= 0:
        errors.append("BESS power capacity must be > 0 when BESS is enabled.")
    if s.include_bess and s.bess_mwh <= 0:
        errors.append("BESS energy capacity must be > 0 when BESS is enabled.")
    if s.ppaload_mw <= 0:
        errors.append("PPA offtake load must be > 0 MW.")
    if s.ppa_price <= 0:
        errors.append("PPA price must be > 0 $/MWh.")
    if not (0.0 < s.required_delivery_share <= 1.0):
        errors.append("Required delivery share must be between 0 and 1.")
    if s.onsw_mw == 0 and s.pv_mw == 0:
        errors.append("At least one generation asset (wind or solar) must have capacity > 0.")
    if s.load_profile not in PROFILE_KEYS:
        errors.append(f"Unknown load profile '{s.load_profile}'. Valid options: {PROFILE_KEYS}")
    if available_days and s.chosen_day not in available_days:
        errors.append(f"chosen_day '{s.chosen_day}' is not present in the timeseries data.")
    return errors


def scenario_from_excel(path: str | Path) -> Scenario:
    raw = pd.read_excel(path, sheet_name="Scenario", header=None)
    params: dict[str, Any] = {}
    for _, row in raw.iterrows():
        param = row.iloc[4]
        value = row.iloc[1]
        if pd.notna(param):
            key = str(param).strip()
            if key and key.isidentifier():
                params[key] = value

    def _yn(key: str) -> bool:
        return str(params.get(key, "no")).strip().lower() == "yes"

    def _float(key: str, default: float = 0.0) -> float:
        return float(params.get(key, default))

    def _int(key: str, default: int = 0) -> int:
        return int(float(params.get(key, default)))

    return Scenario(
        include_bess=_yn("include_bess"),
        enable_market_buy=_yn("enable_market_buy"),
        enable_market_sell=_yn("enable_market_sell"),
        enable_shortfall=_yn("enable_shortfall"),
        enable_penalty=_yn("enable_penalty"),
        run_financial_analysis=_yn("run_financial_analysis"),
        onsw_mw=_float("onsw_mw", 150.0),
        pv_mw=_float("pv_mw", 200.0),
        bess_mw=_float("bess_mw", 60.0),
        bess_mwh=_float("bess_mwh", 240.0),
        bess_efficiency_store=_float("bess_efficiency_store", 0.9),
        bess_efficiency_dispatch=_float("bess_efficiency_dispatch", 0.9),
        ppaload_mw=_float("ppaload_mw", 100.0),
        ppa_price=_float("ppa_price", 100.0),
        pen_mult=_float("pen_mult", 1.5),
        required_delivery_share=_float("required_delivery_share", 0.75),
        market_buy_share=_float("market_buy_share", 0.05),
        market_spread=_float("market_spread", 0.10),
        chosen_day=str(params.get("chosen_day", "2025-03-15")).strip(),
        wind_capex_per_kw=_float("wind_capex_per_kw", 1800.0),
        pv_capex_per_kw=_float("pv_capex_per_kw", 1000.0),
        bess_capex_per_kwh=_float("bess_capex_per_kwh", 500.0),
        opex_rate=_float("opex_rate", 0.02),
        project_life_yrs=_int("project_life_yrs", 25),
        discount_rate=_float("discount_rate", 0.08),
        target_irr=_float("target_irr", 0.10),
    )
