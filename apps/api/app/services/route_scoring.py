from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ROUTE_PREFERENCES = ("balanced", "fastest", "fuel_saver", "weather_cautious")

WEIGHTS: dict[str, dict[str, float]] = {
    "balanced": {"time": 0.25, "fuel": 0.2, "weather": 0.2, "delay": 0.2, "diversion": 0.15},
    "fastest": {"time": 0.45, "fuel": 0.1, "weather": 0.1, "delay": 0.25, "diversion": 0.1},
    "fuel_saver": {"time": 0.15, "fuel": 0.45, "weather": 0.1, "delay": 0.15, "diversion": 0.15},
    "weather_cautious": {"time": 0.1, "fuel": 0.1, "weather": 0.45, "delay": 0.2, "diversion": 0.15},
}


@dataclass
class ScoringInput:
    ete_minutes: float
    fuel_burn_gal: float
    baseline_ete_minutes: float
    baseline_fuel_gal: float
    departure_delay_min: int = 0
    destination_delay_min: int = 0
    departure_closed: bool = False
    destination_closed: bool = False
    departure_ground_stop: bool = False
    destination_ground_stop: bool = False
    departure_flight_category: str | None = None
    destination_flight_category: str | None = None
    checkpoint_weather_penalty: float = 0.0
    diversion_count: int = 0
    min_diversion_runway_ft: int = 3000


def _clamp_score(value: float) -> float:
    return max(0.0, min(100.0, value))


def _weather_penalty(category: str | None) -> float:
    penalties = {"LIFR": 60, "IFR": 40, "MVFR": 20, "VFR": 0}
    return penalties.get((category or "VFR").upper(), 10)


def _component_scores(inp: ScoringInput) -> dict[str, float]:
    ete_ratio = inp.ete_minutes / max(inp.baseline_ete_minutes, 1.0)
    time_score = _clamp_score(100 - (ete_ratio - 1.0) * 80)

    fuel_ratio = inp.fuel_burn_gal / max(inp.baseline_fuel_gal, 1.0)
    fuel_score = _clamp_score(100 - (fuel_ratio - 1.0) * 80)

    weather_pen = (
        _weather_penalty(inp.departure_flight_category)
        + _weather_penalty(inp.destination_flight_category)
        + inp.checkpoint_weather_penalty
    )
    weather_score = _clamp_score(100 - weather_pen)

    delay_pen = inp.departure_delay_min + inp.destination_delay_min
    if inp.departure_closed or inp.destination_closed:
        delay_pen += 120
    if inp.departure_ground_stop or inp.destination_ground_stop:
        delay_pen += 60
    delay_score = _clamp_score(100 - delay_pen * 0.5)

    if inp.diversion_count == 0:
        div_pen = 50
    elif inp.min_diversion_runway_ft < 3000:
        div_pen = 20
    else:
        div_pen = 0
    diversion_score = _clamp_score(100 - div_pen)

    return {
        "time": round(time_score, 1),
        "fuel": round(fuel_score, 1),
        "weather": round(weather_score, 1),
        "delay": round(delay_score, 1),
        "diversion": round(diversion_score, 1),
    }


def calculate_normalized_score(
    inp: ScoringInput, preference: str = "balanced"
) -> dict[str, Any]:
    pref = preference if preference in ROUTE_PREFERENCES else "balanced"
    weights = WEIGHTS[pref]
    components = _component_scores(inp)
    composite = sum(components[k] * weights[k] for k in weights)
    composite = round(_clamp_score(composite), 1)

    # Legacy penalty-style breakdown for debugging
    fuel_penalty = max(0.0, inp.fuel_burn_gal - inp.baseline_fuel_gal) * 2
    delay_penalty = (
        inp.departure_delay_min
        + inp.destination_delay_min
        + (120 if inp.departure_closed or inp.destination_closed else 0)
        + (60 if inp.departure_ground_stop or inp.destination_ground_stop else 0)
    )
    weather_penalty = (
        _weather_penalty(inp.departure_flight_category)
        + _weather_penalty(inp.destination_flight_category)
        + inp.checkpoint_weather_penalty
    )
    diversion_penalty = 50.0 if inp.diversion_count == 0 else (20.0 if inp.min_diversion_runway_ft < 3000 else 0.0)
    legacy_total = (
        inp.ete_minutes + fuel_penalty + delay_penalty + weather_penalty + diversion_penalty
    )

    return {
        "preference": pref,
        "composite_score": composite,
        "component_scores": components,
        "weights": weights,
        "legacy": {
            "ete_minutes": round(inp.ete_minutes, 2),
            "fuel_penalty": round(fuel_penalty, 2),
            "delay_penalty": round(delay_penalty, 2),
            "weather_penalty": round(weather_penalty, 2),
            "diversion_penalty": round(diversion_penalty, 2),
            "total": round(legacy_total, 2),
        },
        "total": composite,
    }
