from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

ROUTE_PREFERENCES = ("balanced", "fastest", "fuel_saver", "weather_cautious")

WEIGHTS: dict[str, dict[str, float]] = {
    "balanced": {"time": 0.25, "fuel": 0.2, "weather": 0.2, "delay": 0.2, "diversion": 0.15},
    "fastest": {"time": 0.45, "fuel": 0.1, "weather": 0.1, "delay": 0.25, "diversion": 0.1},
    "fuel_saver": {"time": 0.15, "fuel": 0.45, "weather": 0.1, "delay": 0.15, "diversion": 0.15},
    "weather_cautious": {"time": 0.1, "fuel": 0.1, "weather": 0.45, "delay": 0.2, "diversion": 0.15},
}

# Penalty points per flight category at the departure and destination. Any other value (None, "UNKNOWN", "") is a
# missing observation and is not scored: treating it as VFR would present "no data" as perfect weather.
ENDPOINT_CATEGORY_PENALTIES = {"LIFR": 60, "IFR": 40, "MVFR": 20, "VFR": 0}


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
    # None / "UNKNOWN": no observation for that airport (it is not scored).
    departure_flight_category: str | None = None
    destination_flight_category: str | None = None
    # Mean penalty of the en-route checkpoints whose weather is known; None when none of them is.
    checkpoint_weather_penalty: float | None = None
    diversion_count: int = 0
    min_diversion_runway_ft: int = 3000
    # False when the FAA status (delay, closure, ground stop) of the airports is unknown: the delay component is
    # then left out of the score instead of being scored as "no delays".
    delay_known: bool = True


def _clamp_score(value: float) -> float:
    return max(0.0, min(100.0, value))


def _weather_penalty(category: str | None) -> float | None:
    """Penalty points of a flight category; None when the category is unknown."""
    return ENDPOINT_CATEGORY_PENALTIES.get(str(category or "").strip().upper())


def is_known_flight_category(category: str | None) -> bool:
    """True for VFR / MVFR / IFR / LIFR (any case); None, 'UNKNOWN' or anything else is a missing observation."""
    return _weather_penalty(category) is not None


def _weather_penalty_total(inp: ScoringInput) -> float | None:
    """Weather penalty from the observations that exist; None when there is no observation at all."""
    parts = (
        _weather_penalty(inp.departure_flight_category),
        _weather_penalty(inp.destination_flight_category),
        inp.checkpoint_weather_penalty,
    )
    known = [part for part in parts if part is not None]
    return float(sum(known)) if known else None


def _delay_penalty_total(inp: ScoringInput) -> float | None:
    """Delay penalty (minutes-equivalent); None when the airport status is unknown."""
    if not inp.delay_known:
        return None
    penalty = float(inp.departure_delay_min + inp.destination_delay_min)
    if inp.departure_closed or inp.destination_closed:
        penalty += 120
    if inp.departure_ground_stop or inp.destination_ground_stop:
        penalty += 60
    return penalty


def combine_components(
    components: Mapping[str, float | None], weights: Mapping[str, float]
) -> tuple[float, dict[str, float]]:
    """Weighted mean of the components that have a value, and the weights it used.

    A component without data (None) is left out and the remaining weights are renormalised, so a missing
    component is counted neither as perfect nor as poor.
    """
    available = {key: value for key, value in components.items() if value is not None and weights.get(key, 0) > 0}
    total_weight = sum(weights[key] for key in available)
    if total_weight <= 0:
        return 0.0, {}
    composite = sum(value * weights[key] for key, value in available.items()) / total_weight
    effective = {key: round(weights[key] / total_weight, 4) for key in available}
    return round(_clamp_score(composite), 1), effective


def _join(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def scoring_data_warnings(breakdown: Mapping[str, Any]) -> list[str]:
    """Plain-language warnings for score components that were left out for lack of data."""
    missing = list(breakdown.get("unavailable_components") or [])
    if not missing:
        return []
    used = list(breakdown.get("effective_weights") or [])
    warnings = [
        f"{_join(missing).capitalize()} data unavailable — not part of the route score, "
        f"which is based on {_join(used)} only"
    ]
    if "weather" in missing and breakdown.get("preference") == "weather_cautious":
        warnings.append("The weather-cautious preference had no weather data to act on")
    return warnings


def _component_scores(inp: ScoringInput) -> dict[str, float | None]:
    """0-100 score per component; None for a component whose data is unknown."""
    ete_ratio = inp.ete_minutes / max(inp.baseline_ete_minutes, 1.0)
    time_score = _clamp_score(100 - (ete_ratio - 1.0) * 80)

    fuel_ratio = inp.fuel_burn_gal / max(inp.baseline_fuel_gal, 1.0)
    fuel_score = _clamp_score(100 - (fuel_ratio - 1.0) * 80)

    weather_pen = _weather_penalty_total(inp)
    weather_score = None if weather_pen is None else _clamp_score(100 - weather_pen)

    delay_pen = _delay_penalty_total(inp)
    delay_score = None if delay_pen is None else _clamp_score(100 - delay_pen * 0.5)

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
        "weather": None if weather_score is None else round(weather_score, 1),
        "delay": None if delay_score is None else round(delay_score, 1),
        "diversion": round(diversion_score, 1),
    }


def calculate_normalized_score(
    inp: ScoringInput, preference: str = "balanced"
) -> dict[str, Any]:
    pref = preference if preference in ROUTE_PREFERENCES else "balanced"
    weights = WEIGHTS[pref]
    components = _component_scores(inp)
    composite, effective_weights = combine_components(components, weights)

    # Legacy penalty-style breakdown for debugging (unknown inputs contribute nothing)
    fuel_penalty = max(0.0, inp.fuel_burn_gal - inp.baseline_fuel_gal) * 2
    delay_penalty = _delay_penalty_total(inp) or 0.0
    weather_penalty = _weather_penalty_total(inp) or 0.0
    diversion_penalty = 50.0 if inp.diversion_count == 0 else (20.0 if inp.min_diversion_runway_ft < 3000 else 0.0)
    legacy_total = (
        inp.ete_minutes + fuel_penalty + delay_penalty + weather_penalty + diversion_penalty
    )

    return {
        "preference": pref,
        "composite_score": composite,
        "component_scores": components,
        "weights": weights,
        # Weights actually used (renormalised over the components that have data) and the components left out.
        "effective_weights": effective_weights,
        "unavailable_components": [key for key in weights if components[key] is None],
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
