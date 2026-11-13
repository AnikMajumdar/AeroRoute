from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash-lite"

# Tried in order when the primary model fails with quota/availability errors
FALLBACK_GEMINI_MODELS = (
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-flash-lite-latest",
)

SYSTEM_PROMPT = """You are AeroRoute Copilot, an educational flight route planning assistant.

STRICT RULES:
1. Answer using the route context JSON below. Prefer quick_facts and weather sections for basic questions about airports, distance, ETE, fuel, scores, and weather.
2. If specific data is missing, say: "That data is not available in this route result." National average fuel prices are NOT in the dataset — only the user-entered fuel price in planning_economics.
3. Always remind the user this is an educational tool, NOT certified flight-planning software. Verify with official briefings, NOTAMs, POH, dispatch, and pilot judgment.
4. AviationWeather.gov and FAA live APIs are NOT connected — never invent METAR, TAF, TFR, SIGMET, or NOTAM data. State clearly when weather or restriction data is unavailable.
5. Keep answers concise (2-6 sentences) unless comparing routes or listing airports — then use short bullets.
6. Do not recommend flying in unsafe conditions. Never say "safe to fly."

CONTEXT FIELD GUIDE (read top to bottom):
- quick_facts.summary_lines: one-line answers for "what route", "how far", "how long", "what aircraft"
- departure / destination: ICAO, name, municipality, elevation, longest runway, coordinates
- departure_weather / destination_weather: may be empty — live METAR/TAF integration is disabled
- faa_status: may be empty — FAA NAS integration is disabled
- weather_checkpoints: en-route checkpoint airports (no live METAR when integration disabled)
- runway_suitability: whether runways meet aircraft min_runway_ft (dep, dest, each diversion)
- planning_economics: fuel price used, trip/total fuel gallons and USD cost
- fuel_breakdown: climb, cruise, descent, reserve, total required fuel
- aircraft: cruise speed, altitude, fuel burn, climb/descent times, min runway
- primary_route / alternate_route / comparison / route_candidates: distances, ETE, fuel, scores
- score_breakdown: normalized 0-100 composite and component scores
- segments.primary / segments.alternate: per-leg wind, headwind/tailwind, groundspeed, ETE
- diversions: ranked alternate airports along the corridor with runway length and distance from route
- ml_predictions.delay_risk: rules-based baseline only — not operational dispatch advice
- warnings: data gaps and educational disclaimers from route calculation
- primary_path / alternate_path: lat/lon waypoints for the planned routes
"""

SUGGESTED_QUESTIONS = [
    "Why was this route selected?",
    "What are the biggest risks?",
    "How does wind affect this route?",
    "Compare primary and alternate.",
    "Which diversion airport looks best and why?",
    "Are departure and destination runways long enough for this aircraft?",
    "What fuel price was used and what is the total fuel cost?",
]


def _gemini_generate_url(model: str) -> str:
    return (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )


def is_copilot_available() -> bool:
    return bool(settings.copilot_enabled and settings.gemini_api_key)


def _models_to_try() -> list[str]:
    primary = settings.gemini_model or DEFAULT_GEMINI_MODEL
    ordered: list[str] = [primary]
    for model in FALLBACK_GEMINI_MODELS:
        if model not in ordered:
            ordered.append(model)
    return ordered


def _parse_gemini_error(response: httpx.Response) -> str:
    """Map a Gemini error response to a message that is safe to show to end users (details go to the log)."""
    try:
        message = str(response.json().get("error", {}).get("message", ""))
    except Exception:
        message = ""
    logger.warning("Gemini API error HTTP %s: %s", response.status_code, message[:300])
    status = response.status_code
    if status == 429:
        if "limit: 0" in message or "quota" in message.lower():
            return "The AI service has reached its usage limit. Please try again later."
        return "The AI service is busy. Please wait a moment and try again."
    if status == 404:
        return "The configured AI model is not available."
    if status in (401, 403):
        return "The AI service is not configured correctly."
    return f"The AI service returned an error (HTTP {status})."


def _faa_status_from_route_weather(route: dict[str, Any], role: str) -> dict[str, Any] | None:
    weather = route.get(f"{role}_weather")
    if isinstance(weather, dict):
        status = weather.get("faa_status")
        if status:
            return status
    legacy = route.get(f"{role}_status")
    return legacy if isinstance(legacy, dict) else None


async def build_route_context(
    route: dict[str, Any],
    request: dict[str, Any],
    segments: list[dict[str, Any]],
    diversions: list[dict[str, Any]],
    dep_airport: dict[str, Any],
    dest_airport: dict[str, Any],
    aircraft: dict[str, Any],
    alternate_segments: list[dict[str, Any]] | None = None,
    delay_prediction: dict[str, Any] | None = None,
    departure_status: dict[str, Any] | None = None,
    destination_status: dict[str, Any] | None = None,
    refresh_live_weather: bool = True,
) -> dict[str, Any]:
    """Retrieve structured route context for RAG (no LLM)."""
    from app.services.aviation_weather import aviation_weather_client
    from app.services.faa_nas import faa_nas_client
    from app.services.route_brief import (
        build_deterministic_brief,
        compare_routes,
        explain_score,
        get_weather_summary,
    )
    from app.services.route_context import (
        aircraft_snapshot,
        airport_snapshot,
        build_quick_facts,
        checkpoint_snapshots,
        faa_status_snapshot,
        metar_snapshot,
        planning_economics,
        runway_suitability,
        segment_snapshots,
        taf_snapshot,
    )

    dep_icao = dep_airport.get("icao_code") or dep_airport.get("ident")
    dest_icao = dest_airport.get("icao_code") or dest_airport.get("ident")

    stored_dep_wx = route.get("departure_weather") or {}
    stored_dest_wx = route.get("destination_weather") or {}
    dep_metar = stored_dep_wx.get("metar") if isinstance(stored_dep_wx, dict) else None
    dep_taf = stored_dep_wx.get("taf") if isinstance(stored_dep_wx, dict) else None
    dest_metar = stored_dest_wx.get("metar") if isinstance(stored_dest_wx, dict) else None
    dest_taf = stored_dest_wx.get("taf") if isinstance(stored_dest_wx, dict) else None

    dep_status = departure_status or _faa_status_from_route_weather(route, "departure")
    dest_status = destination_status or _faa_status_from_route_weather(route, "destination")

    if refresh_live_weather:
        if dep_icao:
            dep_metar = await aviation_weather_client.get_metar(dep_icao) or dep_metar
            dep_taf = await aviation_weather_client.get_taf(dep_icao) or dep_taf
        if dest_icao:
            dest_metar = await aviation_weather_client.get_metar(dest_icao) or dest_metar
            dest_taf = await aviation_weather_client.get_taf(dest_icao) or dest_taf
        if dep_icao and not dep_status:
            dep_status = await faa_nas_client.get_airport_status(dep_icao)
        if dest_icao and not dest_status:
            dest_status = await faa_nas_client.get_airport_status(dest_icao)

    brief = build_deterministic_brief(
        route, request, segments, diversions, dep_airport, dest_airport, aircraft
    )
    dep = airport_snapshot(dep_airport, "departure")
    dest = airport_snapshot(dest_airport, "destination")
    checkpoints = route.get("weather_checkpoints") or []

    return {
        "quick_facts": build_quick_facts(route, request, dep_airport, dest_airport, aircraft, diversions),
        "route_id": route.get("id"),
        "departure": dep,
        "destination": dest,
        "aircraft": aircraft_snapshot(aircraft),
        "planning": {
            "departure_time": request.get("departure_time"),
            "route_preference": request.get("route_preference", "balanced"),
            "fuel_price_usd_per_gal": request.get("fuel_price_usd_per_gal"),
        },
        "planning_economics": planning_economics(request, route),
        "runway_suitability": runway_suitability(dep_airport, dest_airport, aircraft, diversions),
        "departure_weather": {
            "metar": metar_snapshot(dep_metar),
            "flight_category": (dep_metar or {}).get("flight_category"),
        },
        "destination_weather": {
            "metar": metar_snapshot(dest_metar),
            "flight_category": (dest_metar or {}).get("flight_category"),
        },
        "departure_taf": taf_snapshot(dep_taf),
        "destination_taf": taf_snapshot(dest_taf),
        "primary_route": {
            "distance_nm": route.get("primary_distance_nm"),
            "ete_minutes": route.get("primary_ete_minutes"),
            "fuel_burn_gal": route.get("primary_fuel_burn_gal"),
            "fuel_cost_usd": route.get("primary_fuel_cost_usd"),
            "score": route.get("primary_score"),
        },
        "alternate_route": {
            "distance_nm": route.get("alternate_distance_nm"),
            "ete_minutes": route.get("alternate_ete_minutes"),
            "fuel_burn_gal": route.get("alternate_fuel_burn_gal"),
            "fuel_cost_usd": route.get("alternate_fuel_cost_usd"),
            "score": route.get("alternate_score"),
        },
        "comparison": compare_routes(route),
        "score_breakdown": explain_score(route),
        "fuel_breakdown": route.get("fuel_breakdown"),
        "weather": get_weather_summary(route),
        "weather_checkpoints": checkpoint_snapshots(checkpoints),
        "faa_status": {
            "departure": faa_status_snapshot(dep_status),
            "destination": faa_status_snapshot(dest_status),
        },
        "wind_data_quality": route.get("wind_data_quality"),
        "warnings": route.get("warnings") or [],
        "route_candidates": route.get("route_candidates") or [],
        "primary_path": route.get("primary_path"),
        "alternate_path": route.get("alternate_path"),
        "segments": {
            "primary": segment_snapshots(segments, "primary"),
            "alternate": segment_snapshots(alternate_segments or [], "alternate"),
        },
        "diversions": [
            {
                "rank": i + 1,
                "icao": d.get("airport", {}).get("icao_code") or d.get("airport", {}).get("ident"),
                "iata": d.get("airport", {}).get("iata_code"),
                "name": d.get("airport", {}).get("name"),
                "municipality": d.get("airport", {}).get("municipality"),
                "airport_type": d.get("airport", {}).get("airport_type"),
                "latitude": d.get("airport", {}).get("latitude"),
                "longitude": d.get("airport", {}).get("longitude"),
                "distance_from_route_nm": d.get("distance_from_route_nm"),
                "longest_runway_ft": d.get("airport", {}).get("longest_runway_ft"),
            }
            for i, d in enumerate(diversions)
        ],
        "ml_predictions": {
            "delay_risk": delay_prediction,
            "note": (
                "Rules-based baseline (rules_baseline_v1). "
                "Structured for future CatBoost/logistic regression — not trained ML yet."
            ),
        },
        "brief_summary": brief,
    }


def _extract_gemini_text(data: dict[str, Any]) -> str:
    candidates = data.get("candidates") or []
    if not candidates:
        block = data.get("promptFeedback", {})
        logger.warning("Gemini returned no candidates: %s", block)
        raise RuntimeError("The AI service could not answer this question.")
    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    text_parts = [p["text"] for p in parts if isinstance(p, dict) and p.get("text")]
    if not text_parts:
        raise RuntimeError("The AI service returned an empty response.")
    return "\n".join(text_parts).strip()


def _should_retry_model(status_code: int, error_text: str) -> bool:
    if status_code == 404:
        return True
    if status_code == 429 and ("limit: 0" in error_text or "quota" in error_text.lower()):
        return True
    if status_code == 503:
        return True
    return False


async def _call_gemini_model(
    client: httpx.AsyncClient, model: str, payload: dict[str, Any]
) -> tuple[str, str]:
    response = await client.post(
        _gemini_generate_url(model),
        headers={"Content-Type": "application/json", "x-goog-api-key": settings.gemini_api_key},
        json=payload,
    )
    if response.is_error:
        error_text = response.text
        if _should_retry_model(response.status_code, error_text):
            raise httpx.HTTPStatusError(
                f"Retry model {model}",
                request=response.request,
                response=response,
            )
        raise RuntimeError(_parse_gemini_error(response))
    return _extract_gemini_text(response.json()), model


async def answer_with_llm(
    context: dict[str, Any],
    question: str,
    *,
    intent: str | None = None,
    sources_used: list[str] | None = None,
    include_operational_safety: bool = False,
) -> tuple[str, list[str]]:
    """Call Google Gemini with intent-filtered route context only."""
    if not is_copilot_available():
        raise RuntimeError("Copilot is not configured")

    sources = sources_used or ["route_context_bundle"]
    context_json = json.dumps(context, indent=2, default=str)
    safety_extra = (
        "\nInclude a brief reminder that this is educational only — not for operational dispatch."
        if include_operational_safety
        else ""
    )
    user_prompt = (
        f"Intent: {intent or 'general'}\n"
        f"Data sources used: {', '.join(sources)}\n"
        f"Route context (use ONLY this data; cite source labels and timestamps when relevant):\n"
        f"```json\n{context_json}\n```\n\n"
        f"Question: {question}\n"
        f"If data is missing, state exactly what is unavailable. Do not invent NOTAMs, airspace, or airports."
        f"{safety_extra}"
    )

    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 1200,
        },
    }

    last_error: Exception | None = None
    models = _models_to_try()

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=5.0)) as client:
            for model in models:
                try:
                    answer, used_model = await _call_gemini_model(client, model, payload)
                    if used_model != models[0]:
                        logger.info("Copilot used fallback Gemini model: %s", used_model)
                    return answer, sources
                except httpx.HTTPStatusError as exc:
                    last_error = exc
                    logger.warning(
                        "Gemini model %s unavailable (%s), trying next",
                        model,
                        exc.response.status_code if exc.response else "?",
                    )
                    continue
            if last_error and last_error.response is not None:
                raise RuntimeError(_parse_gemini_error(last_error.response)) from last_error
            raise RuntimeError("The AI service is currently unavailable.")
    except RuntimeError:
        raise
    except Exception as exc:
        logger.exception("Copilot LLM call failed: %s", exc)
        raise RuntimeError("The AI service is currently unavailable.") from exc
