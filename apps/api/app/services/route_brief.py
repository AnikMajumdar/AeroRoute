from __future__ import annotations

from typing import Any


def get_route_summary(route: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    return {
        "route_result_id": route.get("id"),
        "distance_nm": route.get("primary_distance_nm"),
        "ete_minutes": route.get("primary_ete_minutes"),
        "fuel_burn_gal": route.get("primary_fuel_burn_gal"),
        "score": route.get("primary_score"),
        "departure_time": request.get("departure_time"),
        "route_preference": request.get("route_preference", "balanced"),
    }


def get_route_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return segments


def get_weather_summary(route: dict[str, Any]) -> dict[str, Any]:
    return {
        "departure": route.get("departure_weather"),
        "destination": route.get("destination_weather"),
        "checkpoints": route.get("weather_checkpoints") or [],
        "wind_data_quality": route.get("wind_data_quality"),
    }


def get_diversion_airports(diversion_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return diversion_rows


def compare_routes(route: dict[str, Any]) -> dict[str, Any]:
    return {
        "primary": {
            "distance_nm": route.get("primary_distance_nm"),
            "ete_minutes": route.get("primary_ete_minutes"),
            "fuel_burn_gal": route.get("primary_fuel_burn_gal"),
            "score": route.get("primary_score"),
        },
        "alternate": {
            "distance_nm": route.get("alternate_distance_nm"),
            "ete_minutes": route.get("alternate_ete_minutes"),
            "fuel_burn_gal": route.get("alternate_fuel_burn_gal"),
            "score": route.get("alternate_score"),
        },
    }


def explain_score(route: dict[str, Any]) -> dict[str, Any]:
    return route.get("normalized_score_breakdown") or route.get("score_breakdown") or {}


def build_deterministic_brief(
    route: dict[str, Any],
    request: dict[str, Any],
    segments: list[dict[str, Any]],
    diversions: list[dict[str, Any]],
    dep_airport: dict[str, Any],
    dest_airport: dict[str, Any],
    aircraft: dict[str, Any],
) -> dict[str, Any]:
    """Structured educational briefing without LLM."""
    summary = get_route_summary(route, request)
    weather = get_weather_summary(route)
    comparison = compare_routes(route)
    score = explain_score(route)
    fuel = route.get("fuel_breakdown") or {}

    risks: list[str] = []
    for w in route.get("warnings") or []:
        risks.append(w)
    if fuel.get("warnings"):
        risks.extend(fuel["warnings"])

    return {
        "disclaimer": (
            "Educational planning summary only. Not for operational use. "
            "Verify with official briefings, NOTAMs, POH, and dispatch."
        ),
        "route_summary": summary,
        "airports": {
            "departure": dep_airport.get("icao_code") or dep_airport.get("ident"),
            "destination": dest_airport.get("icao_code") or dest_airport.get("ident"),
        },
        "aircraft": aircraft.get("name"),
        "primary_vs_alternate": comparison,
        "fuel_plan": fuel,
        "weather": weather,
        "score_explanation": score,
        "segment_count": len(segments),
        "diversion_count": len(diversions),
        "top_diversions": [
            {
                "icao": d.get("airport", {}).get("icao_code"),
                "distance_from_route_nm": d.get("distance_from_route_nm"),
            }
            for d in diversions[:3]
        ],
        "identified_risks": risks[:10],
        "wind_note": (
            f"Wind data quality: {route.get('wind_data_quality', 'unknown')}. "
            "Cruise winds use nearest GFS pressure level when available."
        ),
    }
