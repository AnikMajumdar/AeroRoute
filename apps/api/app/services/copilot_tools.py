from __future__ import annotations

from typing import Any

from app.services.route_context_bundle import get_route_context


async def get_route_summary(supabase: Any, route_id: str, user_id: str) -> dict[str, Any]:
    ctx = await get_route_context(supabase, route_id, user_id)
    return {
        "source": "route_context_bundle",
        "timestamp": ctx["data_source_timestamps"],
        "quick_facts": ctx["quick_facts"],
        "primary_route": ctx["primary_route"],
        "alternate_route": ctx["alternate_route"],
        "warnings": ctx["warnings"],
        "limitations": ctx["limitations"],
    }


async def get_route_score_explanation(supabase: Any, route_id: str, user_id: str) -> dict[str, Any]:
    ctx = await get_route_context(supabase, route_id, user_id)
    return {
        "source": "score_breakdown",
        "timestamp": ctx["data_source_timestamps"],
        "score_breakdown": ctx["score_breakdown"],
        "route_preference": ctx["route_preference"],
        "primary_score": ctx["primary_route"].get("score"),
        "route_candidates": ctx["route_candidates"],
    }


async def get_primary_vs_alternate_comparison(supabase: Any, route_id: str, user_id: str) -> dict[str, Any]:
    ctx = await get_route_context(supabase, route_id, user_id)
    return {
        "source": "route_comparison",
        "timestamp": ctx["data_source_timestamps"],
        "comparison": ctx["comparison"],
        "primary_route": ctx["primary_route"],
        "alternate_route": ctx["alternate_route"],
        "score_breakdown": ctx["score_breakdown"],
    }


async def get_segment_wind_summary(supabase: Any, route_id: str, user_id: str) -> dict[str, Any]:
    ctx = await get_route_context(supabase, route_id, user_id, include_full_segments=True)
    return {
        "source": "route_segments + open_meteo",
        "timestamp": ctx["data_source_timestamps"],
        "wind_summary": ctx["wind_summary"],
        "segments": ctx["segments"]["primary"],
        "wind_data_quality": ctx["wind_summary"].get("wind_data_quality"),
    }


async def get_fuel_breakdown(supabase: Any, route_id: str, user_id: str) -> dict[str, Any]:
    ctx = await get_route_context(supabase, route_id, user_id)
    fuel = ctx.get("fuel_breakdown") or {}
    return {
        "source": "fuel_model",
        "timestamp": ctx["data_source_timestamps"],
        "fuel_breakdown": fuel,
        "planning_economics": ctx["planning_economics"],
        "reserve_fuel_gal": fuel.get("reserve_fuel_gal"),
        "total_required_gal": fuel.get("total_required_gal"),
        "trip_fuel_gal": fuel.get("trip_fuel_gal"),
    }


async def get_weather_risk_summary(supabase: Any, route_id: str, user_id: str) -> dict[str, Any]:
    ctx = await get_route_context(supabase, route_id, user_id, refresh_weather=True)
    missing: list[str] = []
    dep_metar = ctx["departure_weather"]["metar"]
    dest_metar = ctx["destination_weather"]["metar"]
    if not dep_metar.get("available"):
        missing.append("departure METAR")
    if not dest_metar.get("available"):
        missing.append("destination METAR")
    if not ctx["departure_weather"]["taf"].get("available"):
        missing.append("departure TAF")
    if not ctx["destination_weather"]["taf"].get("available"):
        missing.append("destination TAF")

    return {
        "source": "aviationweather.gov + checkpoints",
        "timestamp": ctx["data_source_timestamps"],
        "departure_weather": ctx["departure_weather"],
        "destination_weather": ctx["destination_weather"],
        "weather_checkpoints": ctx["weather_checkpoints"],
        "missing_data": missing,
        "warnings": [w for w in ctx["warnings"] if "METAR" in w or "weather" in w.lower() or "FAA" in w],
    }


async def get_diversion_recommendation(supabase: Any, route_id: str, user_id: str) -> dict[str, Any]:
    ctx = await get_route_context(supabase, route_id, user_id)
    diversions = ctx["diversions"]
    runway = ctx["runway_suitability"]
    best = diversions[0] if diversions else None
    return {
        "source": "diversion_airports + runway_suitability",
        "timestamp": ctx["data_source_timestamps"],
        "diversions": diversions,
        "runway_suitability": runway,
        "recommended": best,
        "diversion_count": len(diversions),
    }


async def refresh_route_weather(supabase: Any, route_id: str, user_id: str) -> dict[str, Any]:
    ctx = await get_route_context(supabase, route_id, user_id, refresh_weather=True)
    return {
        "source": "aviationweather.gov (live refresh)",
        "timestamp": ctx["data_source_timestamps"],
        "departure_weather": ctx["departure_weather"],
        "destination_weather": ctx["destination_weather"],
        "weather_checkpoints": ctx["weather_checkpoints"],
        "note": "Checkpoint METARs are from route calculation time unless recalculated.",
    }
