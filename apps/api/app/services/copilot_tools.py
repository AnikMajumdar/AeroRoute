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


async def get_live_data_summary(supabase: Any, route_id: str, user_id: str) -> dict[str, Any]:
    ctx = await get_route_context(supabase, route_id, user_id)
    return {
        "source": "live_data_orchestrator",
        "timestamp": ctx["data_source_timestamps"],
        "live_data_summary": ctx.get("live_data_summary"),
        "live_data_snapshot": ctx.get("live_data_snapshot"),
        "confidence": (ctx.get("live_data_snapshot") or {}).get("confidence"),
        "warnings": ctx["warnings"],
    }


async def get_tfr_summary(supabase: Any, route_id: str, user_id: str) -> dict[str, Any]:
    ctx = await get_route_context(supabase, route_id, user_id)
    snap = ctx.get("live_data_snapshot") or {}
    from app.services.live_data.live_data_scoring import summarize_live_restrictions

    restrictions = summarize_live_restrictions(snap)
    return {
        "source": "FAA TFR (tfr.faa.gov)",
        "timestamp": ctx["data_source_timestamps"],
        "fetched_at": snap.get("fetched_at"),
        "intersecting": restrictions["intersecting"],
        "nearby": restrictions["nearby"],
        "unmapped": restrictions["unmapped"],
        "disclaimer": "Advisory only — verify TFRs through official FAA briefings.",
    }


async def get_notam_summary(supabase: Any, route_id: str, user_id: str) -> dict[str, Any]:
    ctx = await get_route_context(supabase, route_id, user_id)
    snap = ctx.get("live_data_snapshot") or {}
    connected = (snap.get("restrictions") or {}).get("notam_connected", False)
    notams = (snap.get("restrictions") or {}).get("notams") or []
    return {
        "source": "NOTAM provider",
        "timestamp": ctx["data_source_timestamps"],
        "notam_connected": connected,
        "notams": notams,
        "message": (
            None
            if connected
            else "NOTAM integration not connected. Verify NOTAMs through official sources."
        ),
    }


async def get_weather_hazard_summary(supabase: Any, route_id: str, user_id: str) -> dict[str, Any]:
    ctx = await get_route_context(supabase, route_id, user_id)
    snap = ctx.get("live_data_snapshot") or {}
    from app.services.live_data.live_data_scoring import summarize_weather_hazards

    hazards = summarize_weather_hazards(snap)
    return {
        "source": "AviationWeather.gov",
        "timestamp": ctx["data_source_timestamps"],
        "fetched_at": snap.get("fetched_at"),
        **hazards,
    }


async def get_prediction_summary(supabase: Any, route_id: str, user_id: str) -> dict[str, Any]:
    ctx = await get_route_context(supabase, route_id, user_id)
    preds = ctx.get("ml_predictions") or {}
    delay = (preds.get("delay_risk") or {}).get("prediction") or {}
    ete = (preds.get("ete_prediction") or {}).get("prediction") or {}
    return {
        "source": "ml_inference + rules_baseline",
        "timestamp": ctx["data_source_timestamps"],
        "delay_prediction": delay,
        "ete_prediction": ete,
        "note": "AeroRoute estimates only — not operational delay or ETE guarantees.",
    }


async def refresh_live_data(supabase: Any, route_id: str, user_id: str) -> dict[str, Any]:
    from app.services.live_data.live_data_orchestrator import live_data_orchestrator
    from app.services.route_loader import load_route_bundle

    route_data, request_data, dep, dest, aircraft, segments, diversions, _ = await load_route_bundle(
        supabase, route_id, user_id
    )
    dep_icao = dep.get("icao_code") or dep.get("ident")
    dest_icao = dest.get("icao_code") or dest.get("ident")
    path = route_data.get("primary_path") or []
    route_path = [{"lat": p["lat"], "lon": p["lon"]} for p in path if "lat" in p and "lon" in p]
    snapshot, timings = await live_data_orchestrator.build_snapshot(
        route_id=route_id,
        departure_icao=dep_icao,
        destination_icao=dest_icao,
        route_path=route_path,
        supabase=supabase,
    )
    from app.services.live_data.types import LiveDataSnapshot

    await live_data_orchestrator.persist_snapshot(
        supabase,
        route_id,
        user_id,
        LiveDataSnapshot(
            route_id=route_id,
            fetched_at=snapshot.fetched_at,
            departure_icao=snapshot.departure_icao,
            destination_icao=snapshot.destination_icao,
            weather=snapshot.weather,
            restrictions=snapshot.restrictions,
            faa_status=snapshot.faa_status,
            confidence=snapshot.confidence,
            sources=snapshot.sources,
            warnings=snapshot.warnings,
        ),
    )
    return {
        "source": "live_data_orchestrator (refresh)",
        "timestamp": {"live_data_fetched_at": snapshot.fetched_at},
        "live_data_snapshot": snapshot.to_dict(),
        "provider_timings": timings,
    }


async def recalculate_with_latest_data(supabase: Any, route_id: str, user_id: str) -> dict[str, Any]:
    return {
        "source": "route_calculator",
        "message": (
            "Full recalculation requires a new POST /routes/calculate request with the same airports. "
            "Use refresh_live_data to update TFR/hazard/NOTAM snapshot without recomputing winds."
        ),
        "refresh": await refresh_live_data(supabase, route_id, user_id),
    }
