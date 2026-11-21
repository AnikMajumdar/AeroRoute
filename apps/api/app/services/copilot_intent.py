from __future__ import annotations

import logging
import re
from typing import Any, Literal

from fastapi import HTTPException

logger = logging.getLogger(__name__)


CopilotIntent = Literal[
    "route_explanation",
    "weather",
    "wind",
    "fuel",
    "diversion",
    "delay",
    "primary_vs_alternate",
    "general_summary",
    "unknown",
]

INTENT_PATTERNS: list[tuple[CopilotIntent, re.Pattern[str]]] = [
    ("primary_vs_alternate", re.compile(r"\b(compare|alternate|vs|versus|difference|primary)\b", re.I)),
    ("wind", re.compile(r"\b(wind|headwind|tailwind|groundspeed|gfs)\b", re.I)),
    ("weather", re.compile(r"\b(weather|metar|taf|vfr|ifr|mvfr|lifr|ceiling|visibility|cloud|tfr|notam|sigmet|airmet|pirep|hazard|restriction)\b", re.I)),
    ("fuel", re.compile(r"\b(fuel|gallon|gal|reserve|burn|cost|price)\b", re.I)),
    ("diversion", re.compile(r"\b(diversion|alternate airport|divert|alt airport)\b", re.I)),
    ("delay", re.compile(r"\b(delay|ground stop|closure|closed|nas|faa status)\b", re.I)),
    ("route_explanation", re.compile(r"\b(score|why|selected|explain|component|breakdown)\b", re.I)),
    ("general_summary", re.compile(r"\b(summary|overview|risk|biggest|tell me about)\b", re.I)),
]


def classify_copilot_intent(question: str) -> CopilotIntent:
    q = question.strip()
    if not q:
        return "unknown"
    scores: dict[str, int] = {}
    for intent, pattern in INTENT_PATTERNS:
        if pattern.search(q):
            scores[intent] = scores.get(intent, 0) + 1
    if not scores:
        return "general_summary"
    return max(scores, key=lambda k: scores[k])  # type: ignore[return-value]


INTENT_TOOLS: dict[CopilotIntent, list[str]] = {
    "route_explanation": ["get_route_score_explanation", "get_route_summary"],
    "weather": ["get_weather_risk_summary", "get_weather_hazard_summary", "get_tfr_summary", "get_notam_summary", "refresh_live_data"],
    "wind": ["get_segment_wind_summary"],
    "fuel": ["get_fuel_breakdown"],
    "diversion": ["get_diversion_recommendation"],
    "delay": ["get_prediction_summary", "get_weather_risk_summary", "get_live_data_summary"],
    "primary_vs_alternate": ["get_primary_vs_alternate_comparison"],
    "general_summary": ["get_route_summary", "get_route_score_explanation"],
    "unknown": ["get_route_summary"],
}

OPERATIONAL_INTENTS = frozenset({"weather", "wind", "delay", "diversion", "fuel"})


async def build_intent_context(
    supabase: Any,
    route_id: str,
    user_id: str,
    question: str,
) -> tuple[CopilotIntent, dict[str, Any], list[str]]:
    from app.services import copilot_tools
    from app.services.route_context_bundle import get_route_context

    intent = classify_copilot_intent(question)

    # Resolve the route before running any tool: an unknown or foreign route must answer 404 (not 500),
    # and none of the tools (some refresh data or recalculate) may run for it.
    try:
        base = await get_route_context(supabase, route_id, user_id, include_full_segments=False)
    except HTTPException:
        raise
    except Exception as exc:
        raise RuntimeError("Could not load route context") from exc

    tool_names = INTENT_TOOLS[intent]
    sources: list[str] = []
    tool_results: dict[str, Any] = {"intent": intent}

    tool_map = {
        "get_route_summary": copilot_tools.get_route_summary,
        "get_route_score_explanation": copilot_tools.get_route_score_explanation,
        "get_primary_vs_alternate_comparison": copilot_tools.get_primary_vs_alternate_comparison,
        "get_segment_wind_summary": copilot_tools.get_segment_wind_summary,
        "get_fuel_breakdown": copilot_tools.get_fuel_breakdown,
        "get_weather_risk_summary": copilot_tools.get_weather_risk_summary,
        "get_diversion_recommendation": copilot_tools.get_diversion_recommendation,
        "refresh_route_weather": copilot_tools.refresh_route_weather,
        "get_live_data_summary": copilot_tools.get_live_data_summary,
        "get_tfr_summary": copilot_tools.get_tfr_summary,
        "get_notam_summary": copilot_tools.get_notam_summary,
        "get_weather_hazard_summary": copilot_tools.get_weather_hazard_summary,
        "get_prediction_summary": copilot_tools.get_prediction_summary,
        "refresh_live_data": copilot_tools.refresh_live_data,
        "recalculate_with_latest_data": copilot_tools.recalculate_with_latest_data,
    }

    for name in tool_names:
        fn = tool_map[name]
        try:
            result = await fn(supabase, route_id, user_id)
            tool_results[name] = result
            sources.append(result.get("source", name))
        except Exception as exc:
            logger.warning("Copilot tool %s failed: %s", name, exc)
            tool_results[name] = {
                "error": "unavailable",
                "source": name,
                "note": "Tool data unavailable for this route.",
            }
            sources.append(name)

    # Slim base context always included
    slim = {
        "route_id": route_id,
        "intent": intent,
        "quick_facts": base["quick_facts"],
        "limitations": base["limitations"],
        "data_source_timestamps": base["data_source_timestamps"],
        "warnings": base["warnings"][:8],
        "tool_results": tool_results,
    }
    if intent in ("wind",):
        slim["wind_summary"] = base["wind_summary"]
    if intent in ("delay",):
        slim["ml_predictions"] = base.get("ml_predictions")

    return intent, slim, sources


def generate_suggested_questions(context: dict[str, Any]) -> list[str]:
    """Route-specific suggested questions from risk factors."""
    questions: list[str] = []
    primary_score = (context.get("primary_route") or {}).get("score")
    alt = context.get("alternate_route") or {}
    if alt.get("score") and primary_score:
        questions.append("Why did the primary route score higher than the alternate?")

    wind = context.get("wind_summary") or {}
    if wind.get("max_headwind_kt") and float(wind["max_headwind_kt"]) > 15:
        questions.append("Which segment has the strongest headwind?")

    diversions = context.get("diversions") or []
    if diversions:
        questions.append("Which diversion airport is most suitable for this aircraft?")
    else:
        questions.append("Why were no diversion airports found?")

    missing = []
    dep = (context.get("departure_weather") or {}).get("metar", {})
    if not dep.get("available"):
        missing.append("departure")
    dest = (context.get("destination_weather") or {}).get("metar", {})
    if not dest.get("available"):
        missing.append("destination")
    if missing:
        questions.append("What weather data is missing for this route?")

    fuel = context.get("fuel_breakdown") or {}
    if fuel.get("reserve_fuel_gal") is not None:
        questions.append("How much reserve fuel remains in this plan?")

    ml = context.get("ml_predictions") or {}
    if ml.get("delay_risk"):
        questions.append("What does the delay risk estimate mean for this route?")

    warnings = context.get("warnings") or []
    if any("surface" in w.lower() for w in warnings):
        questions.append("How does surface wind fallback affect this route?")

    defaults = [
        "Summarize the biggest risks for this route.",
        "Compare primary and alternate routes.",
        "Are departure and destination runways long enough?",
    ]
    for q in defaults:
        if q not in questions:
            questions.append(q)
    return questions[:7]
