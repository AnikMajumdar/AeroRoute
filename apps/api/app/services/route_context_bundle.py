from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.services.ml_features import extract_delay_features, extract_ete_features
from app.services.route_loader import load_route_bundle

logger = logging.getLogger(__name__)

SAFETY_LIMITATIONS = [
    "Educational tool only — not certified for operational flight planning.",
    "Does not include NOTAMs, TFRs, or published airways/SID/STAR procedures.",
    "Winds are GFS model estimates; METAR/TAF may be stale at chat time.",
    "ML ETE predictions use surrogate labels until real track data is available.",
    "Verify all decisions with official briefings, POH, dispatch, and pilot judgment.",
]


def _faa_status_from_weather(weather: dict[str, Any] | None) -> dict[str, Any] | None:
    if not weather or not isinstance(weather, dict):
        return None
    return weather.get("faa_status")


def _load_predictions(supabase: Any, route_id: str) -> dict[str, Any]:
    rows = (
        supabase.table("model_predictions")
        .select("*")
        .eq("route_result_id", route_id)
        .order("created_at", desc=True)
        .execute()
    ).data or []
    delay = ete = None
    for row in rows:
        target = (row.get("prediction") or {}).get("model_target")
        name = row.get("model_name", "")
        if delay is None and (target == "delay_risk" or "delay" in name):
            delay = row
        if ete is None and (target == "ete_prediction" or "ete" in name):
            ete = row
    return {"delay_risk": delay, "ete_prediction": ete}


def _wind_summary(segments: list[dict[str, Any]], wind_quality: str | None) -> dict[str, Any]:
    if not segments:
        return {"available": False, "wind_data_quality": wind_quality}
    headwinds = [float(s["headwind_component_kt"]) for s in segments if s.get("headwind_component_kt") is not None]
    tailwinds = [float(s["tailwind_component_kt"]) for s in segments if s.get("tailwind_component_kt") is not None]
    strongest_hw = None
    if headwinds:
        idx = max(range(len(headwinds)), key=lambda i: headwinds[i])
        strongest_hw = {
            "segment_index": segments[idx].get("segment_index", idx),
            "headwind_kt": round(headwinds[idx], 1),
            "distance_nm": segments[idx].get("distance_nm"),
        }
    return {
        "available": True,
        "wind_data_quality": wind_quality,
        "segment_count": len(segments),
        "avg_headwind_kt": round(sum(headwinds) / len(headwinds), 1) if headwinds else None,
        "max_headwind_kt": round(max(headwinds), 1) if headwinds else None,
        "avg_tailwind_kt": round(sum(tailwinds) / len(tailwinds), 1) if tailwinds else None,
        "strongest_headwind_segment": strongest_hw,
    }


async def get_route_context(
    supabase: Any,
    route_id: str,
    user_id: str,
    *,
    include_full_segments: bool = False,
    refresh_weather: bool = False,
) -> dict[str, Any]:
    """Structured route context for copilot tools and RAG."""
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
    from app.services.route_brief import compare_routes, explain_score

    (
        route_data,
        request_data,
        dep,
        dest,
        aircraft,
        segments,
        diversions,
        alternate_segments,
    ) = await load_route_bundle(supabase, route_id, user_id)

    route_payload = {**route_data, "id": route_id}
    predictions = _load_predictions(supabase, route_id)

    dep_wx = route_data.get("departure_weather") or {}
    dest_wx = route_data.get("destination_weather") or {}
    dep_metar = dep_wx.get("metar") if isinstance(dep_wx, dict) else None
    dest_metar = dest_wx.get("metar") if isinstance(dest_wx, dict) else None
    dep_taf = dep_wx.get("taf") if isinstance(dep_wx, dict) else None
    dest_taf = dest_wx.get("taf") if isinstance(dest_wx, dict) else None
    dep_status = _faa_status_from_weather(dep_wx)
    dest_status = _faa_status_from_weather(dest_wx)

    weather_refreshed_at = None
    if refresh_weather:
        from app.services.aviation_weather import aviation_weather_client
        from app.services.faa_nas import faa_nas_client

        dep_icao = dep.get("icao_code") or dep.get("ident")
        dest_icao = dest.get("icao_code") or dest.get("ident")
        if dep_icao:
            dep_metar = await aviation_weather_client.get_metar(dep_icao) or dep_metar
            dep_taf = await aviation_weather_client.get_taf(dep_icao) or dep_taf
            dep_status = await faa_nas_client.get_airport_status(dep_icao) or dep_status
        if dest_icao:
            dest_metar = await aviation_weather_client.get_metar(dest_icao) or dest_metar
            dest_taf = await aviation_weather_client.get_taf(dest_icao) or dest_taf
            dest_status = await faa_nas_client.get_airport_status(dest_icao) or dest_status
        weather_refreshed_at = datetime.now(timezone.utc).isoformat()

    enriched_request = {
        **request_data,
        "_aircraft_cruise_speed_kt": aircraft.get("cruise_speed_kt"),
        "_cruise_altitude_ft": aircraft.get("cruise_altitude_ft"),
    }

    return {
        "route_id": route_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_source_timestamps": {
            "route_calculated_at": route_data.get("created_at"),
            "weather_refreshed_at": weather_refreshed_at,
            "context_built_at": datetime.now(timezone.utc).isoformat(),
        },
        "limitations": SAFETY_LIMITATIONS,
        "quick_facts": build_quick_facts(route_payload, request_data, dep, dest, aircraft, diversions),
        "departure": airport_snapshot(dep, "departure"),
        "destination": airport_snapshot(dest, "destination"),
        "aircraft": aircraft_snapshot(aircraft),
        "departure_time": request_data.get("departure_time"),
        "route_preference": request_data.get("route_preference", "balanced"),
        "planning_economics": planning_economics(request_data, route_payload),
        "runway_suitability": runway_suitability(dep, dest, aircraft, diversions),
        "primary_route": {
            "distance_nm": route_data.get("primary_distance_nm"),
            "ete_minutes": route_data.get("primary_ete_minutes"),
            "fuel_burn_gal": route_data.get("primary_fuel_burn_gal"),
            "fuel_cost_usd": route_data.get("primary_fuel_cost_usd"),
            "score": route_data.get("primary_score"),
        },
        "alternate_route": {
            "distance_nm": route_data.get("alternate_distance_nm"),
            "ete_minutes": route_data.get("alternate_ete_minutes"),
            "fuel_burn_gal": route_data.get("alternate_fuel_burn_gal"),
            "fuel_cost_usd": route_data.get("alternate_fuel_cost_usd"),
            "score": route_data.get("alternate_score"),
        },
        "comparison": compare_routes(route_payload),
        "score_breakdown": explain_score(route_payload),
        "fuel_breakdown": route_data.get("fuel_breakdown"),
        "departure_weather": {
            "metar": metar_snapshot(dep_metar),
            "taf": taf_snapshot(dep_taf),
            "faa_status": faa_status_snapshot(dep_status),
            "source": "aviationweather.gov",
        },
        "destination_weather": {
            "metar": metar_snapshot(dest_metar),
            "taf": taf_snapshot(dest_taf),
            "faa_status": faa_status_snapshot(dest_status),
            "source": "aviationweather.gov",
        },
        "weather_checkpoints": checkpoint_snapshots(route_data.get("weather_checkpoints") or []),
        "wind_summary": _wind_summary(segments, route_data.get("wind_data_quality")),
        "diversions": [
            {
                "rank": i + 1,
                "icao": d.get("airport", {}).get("icao_code") or d.get("airport", {}).get("ident"),
                "name": d.get("airport", {}).get("name"),
                "distance_from_route_nm": d.get("distance_from_route_nm"),
                "longest_runway_ft": d.get("airport", {}).get("longest_runway_ft"),
            }
            for i, d in enumerate(diversions)
        ],
        "warnings": route_data.get("warnings") or [],
        "route_candidates": route_data.get("route_candidates") or [],
        "ml_predictions": predictions,
        "segments": {
            "primary": segment_snapshots(segments, "primary") if include_full_segments else [],
            "alternate": segment_snapshots(alternate_segments, "alternate") if include_full_segments else [],
            "summary_only": not include_full_segments,
        },
        "feature_snapshots": {
            "delay": extract_delay_features(enriched_request, route_payload, segments, diversions),
            "ete": extract_ete_features(enriched_request, route_payload, segments),
        },
    }
