from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from app.auth import get_current_user_id, row_to_airport
from app.db import get_supabase
from app.db_utils import fetch_one
from app.geo.conus import CONUS_MAX_LAT, CONUS_MAX_LON, CONUS_MIN_LAT, CONUS_MIN_LON
from app.geo.utils import path_from_waypoints
from app.planning_constraints import (
    FORECAST_HORIZON_DAYS,
    WEATHER_ELIGIBLE_TYPES,
    is_weather_eligible_airport,
)
from app.rate_limit import route_calculate_limiter
from app.schemas import (
    UUID_PATTERN,
    AircraftCreate,
    AircraftProfile,
    AirportSummary,
    CopilotChatRequest,
    CopilotChatResponse,
    CopilotStatusResponse,
    HealthResponse,
    RouteBriefResponse,
    RouteCalculateRequest,
    RouteListItem,
    RouteResultDetail,
    RouteSegmentDetail,
)
from app.services.aircraft_presets import ensure_aircraft_presets
from app.services.copilot import (
    answer_with_llm,
    is_copilot_available,
)
from app.services.copilot_intent import OPERATIONAL_INTENTS, build_intent_context, generate_suggested_questions
from app.services.ml_logging import log_model_prediction, log_training_samples
from app.services.route_brief import build_deterministic_brief
from app.services.route_calculator import route_calculator
from app.services.route_context_bundle import get_route_context
from app.services.route_loader import load_route_bundle

logger = logging.getLogger(__name__)

router = APIRouter()

# Malformed ids are rejected with 422 instead of reaching PostgREST (which answers with a database error).
RouteId = Annotated[str, Path(pattern=UUID_PATTERN)]


def _load_ml_predictions(supabase: Any, route_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    rows = (
        supabase.table("model_predictions")
        .select("*")
        .eq("route_result_id", route_id)
        .order("created_at", desc=True)
        .execute()
    ).data or []
    delay_pred = ete_pred = None
    for row in rows:
        pred = row.get("prediction") or {}
        target = pred.get("model_target", "")
        if delay_pred is None and (target == "delay_risk" or "delay" in (row.get("model_name") or "")):
            delay_pred = {**pred, "model_name": row.get("model_name"), "confidence": row.get("confidence")}
        if ete_pred is None and (target == "ete_prediction" or "ete" in (row.get("model_name") or "")):
            ete_pred = {**pred, "model_name": row.get("model_name"), "confidence": row.get("confidence")}
    return delay_pred, ete_pred


def _load_delay_prediction(supabase: Any, route_id: str) -> dict[str, Any] | None:
    delay, _ = _load_ml_predictions(supabase, route_id)
    return delay


def _faa_status_from_weather(weather: dict[str, Any] | None) -> dict[str, Any] | None:
    if not weather or not isinstance(weather, dict):
        return None
    return weather.get("faa_status")


async def _load_route_bundle(
    supabase: Any, route_id: str, user_id: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    bundle = await load_route_bundle(supabase, route_id, user_id)
    route_data, request_data, dep, dest, aircraft, segments, diversions, _alt = bundle
    return route_data, request_data, dep, dest, aircraft, segments, diversions


async def _load_route_bundle_full(
    supabase: Any, route_id: str, user_id: str
):
    return await load_route_bundle(supabase, route_id, user_id)


def _build_route_result_detail(
    result_id: str,
    route_request_id: str,
    status: str,
    calc_result: dict[str, Any],
    dep_result: dict[str, Any],
    dest_result: dict[str, Any],
    aircraft_result: dict[str, Any],
    diversion_details: list[dict[str, Any]],
    created_at: str | None,
    route_preference: str,
) -> RouteResultDetail:
    primary = calc_result["primary"]
    alternate = calc_result.get("alternate")

    return RouteResultDetail(
        id=result_id,
        route_request_id=route_request_id,
        status=status,
        primary_distance_nm=primary.distance_nm,
        primary_ete_minutes=primary.ete_minutes,
        primary_fuel_burn_gal=primary.fuel_burn_gal,
        primary_fuel_cost_usd=primary.fuel_cost_usd,
        primary_score=primary.score,
        primary_path=path_from_waypoints(primary.waypoints),
        alternate_distance_nm=alternate.distance_nm if alternate else None,
        alternate_ete_minutes=alternate.ete_minutes if alternate else None,
        alternate_fuel_burn_gal=alternate.fuel_burn_gal if alternate else None,
        alternate_fuel_cost_usd=alternate.fuel_cost_usd if alternate else None,
        alternate_score=alternate.score if alternate else None,
        alternate_path=path_from_waypoints(alternate.waypoints) if alternate else None,
        score_breakdown=primary.score_breakdown,
        normalized_score_breakdown=primary.score_breakdown,
        fuel_breakdown=primary.fuel_breakdown,
        weather_checkpoints=calc_result.get("weather_checkpoints") or [],
        route_candidates=calc_result.get("candidate_summaries") or [],
        wind_data_quality=calc_result.get("wind_data_quality"),
        route_preference=route_preference,
        warnings=calc_result["warnings"],
        departure_weather=calc_result["departure_weather"],
        destination_weather=calc_result["destination_weather"],
        departure_status=_faa_status_from_weather(calc_result.get("departure_weather")),
        destination_status=_faa_status_from_weather(calc_result.get("destination_weather")),
        delay_prediction=calc_result.get("delay_prediction"),
        ete_prediction=calc_result.get("ete_prediction"),
        live_data_snapshot=calc_result.get("live_data_snapshot"),
        performance={"provider_timings": calc_result.get("provider_timings")},
        segments=primary.segments,
        diversion_airports=diversion_details,
        departure_airport=AirportSummary(**row_to_airport(dep_result)),
        destination_airport=AirportSummary(**row_to_airport(dest_result)),
        aircraft_profile=AircraftProfile(**aircraft_result),
        created_at=created_at,
    )


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    try:
        supabase = get_supabase()
        supabase.table("airports").select("id", count="exact").limit(0).execute()
    except Exception as exc:
        logger.error("Supabase health check failed: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return HealthResponse(status="ok")


@router.get("/planning/constraints")
async def get_planning_constraints() -> dict[str, int | list[str]]:
    return {
        "forecast_horizon_days": FORECAST_HORIZON_DAYS,
        "weather_eligible_types": list(WEATHER_ELIGIBLE_TYPES),
    }


@router.get("/airports/search", response_model=list[AirportSummary])
async def search_airports(q: str = Query(min_length=1, max_length=50)) -> list[AirportSummary]:
    supabase = get_supabase()
    query = q.strip().upper()

    result = (
        supabase.table("airports")
        .select("*")
        .gte("latitude", CONUS_MIN_LAT)
        .lte("latitude", CONUS_MAX_LAT)
        .gte("longitude", CONUS_MIN_LON)
        .lte("longitude", CONUS_MAX_LON)
        .not_.is_("icao_code", "null")
        .like("icao_code", "K%")
        .in_("airport_type", list(WEATHER_ELIGIBLE_TYPES))
        .or_(
            f"icao_code.ilike.%{query}%,iata_code.ilike.%{query}%,ident.ilike.%{query}%,name.ilike.%{query}%"
        )
        .order("airport_type", desc=True)
        .limit(20)
        .execute()
    )

    return [AirportSummary(**row_to_airport(row)) for row in (result.data or [])]


@router.get("/aircraft/presets", response_model=list[AircraftProfile])
async def get_aircraft_presets() -> list[AircraftProfile]:
    supabase = get_supabase()
    rows = ensure_aircraft_presets(supabase)
    if not rows:
        raise HTTPException(status_code=503, detail="Aircraft presets unavailable")
    return [AircraftProfile(**row) for row in rows]


@router.post("/aircraft", response_model=AircraftProfile, status_code=201)
async def create_aircraft(
    body: AircraftCreate,
    user_id: str = Depends(get_current_user_id),
) -> AircraftProfile:
    result = (
        get_supabase()
        .table("aircraft_profiles")
        .insert(
            {
                "name": body.name,
                "cruise_speed_kt": body.cruise_speed_kt,
                "fuel_burn_gph": body.fuel_burn_gph,
                "is_preset": False,
                "user_id": user_id,
            }
        )
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create aircraft profile")
    return AircraftProfile(**result.data[0])


@router.get("/routes", response_model=list[RouteListItem])
async def list_routes(user_id: str = Depends(get_current_user_id)) -> list[RouteListItem]:
    supabase = get_supabase()
    requests = (
        supabase.table("route_requests")
        .select("id, status, created_at, departure_airport_id, destination_airport_id")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )

    items: list[RouteListItem] = []
    for req in requests.data or []:
        result = fetch_one(supabase.table("route_results").select("*").eq("route_request_id", req["id"]))
        if not result:
            continue

        dep = fetch_one(supabase.table("airports").select("*").eq("id", req["departure_airport_id"]))
        dest = fetch_one(supabase.table("airports").select("*").eq("id", req["destination_airport_id"]))
        if not dep or not dest:
            logger.warning("Skipping route %s in listing: airport row missing", result["id"])
            continue

        items.append(
            RouteListItem(
                id=result["id"],
                route_request_id=req["id"],
                status=req["status"],
                departure_airport=AirportSummary(**row_to_airport(dep)),
                destination_airport=AirportSummary(**row_to_airport(dest)),
                primary_distance_nm=result["primary_distance_nm"],
                primary_ete_minutes=result["primary_ete_minutes"],
                primary_score=result["primary_score"],
                created_at=result["created_at"],
            )
        )
    return items


@router.post("/routes/calculate", response_model=RouteResultDetail, status_code=201)
async def calculate_route(
    body: RouteCalculateRequest,
    user_id: str = Depends(get_current_user_id),
) -> RouteResultDetail:
    if not route_calculate_limiter.check(user_id):
        raise HTTPException(status_code=429, detail="Rate limit exceeded — try again shortly")

    supabase = get_supabase()

    if body.departure_airport_id == body.destination_airport_id:
        raise HTTPException(status_code=400, detail="Departure and destination must differ")

    departure = fetch_one(supabase.table("airports").select("*").eq("id", body.departure_airport_id))
    destination = fetch_one(supabase.table("airports").select("*").eq("id", body.destination_airport_id))
    if not departure:
        raise HTTPException(status_code=404, detail="Departure airport not found")
    if not destination:
        raise HTTPException(status_code=404, detail="Destination airport not found")
    if not is_weather_eligible_airport(departure):
        raise HTTPException(
            status_code=400,
            detail="Departure airport is not supported (requires US ICAO medium/large airport with weather data)",
        )
    if not is_weather_eligible_airport(destination):
        raise HTTPException(
            status_code=400,
            detail="Destination airport is not supported (requires US ICAO medium/large airport with weather data)",
        )

    aircraft = fetch_one(supabase.table("aircraft_profiles").select("*").eq("id", body.aircraft_profile_id))
    if not aircraft:
        raise HTTPException(status_code=404, detail="Aircraft profile not found")

    logger.info(
        "route_calculation_started",
        extra={
            "user_id": user_id,
            "departure": departure.get("icao_code"),
            "destination": destination.get("icao_code"),
            "preference": body.route_preference,
        },
    )

    request_row = (
        supabase.table("route_requests")
        .insert(
            {
                "user_id": user_id,
                "departure_airport_id": body.departure_airport_id,
                "destination_airport_id": body.destination_airport_id,
                "aircraft_profile_id": body.aircraft_profile_id,
                "departure_time": body.departure_time.isoformat(),
                "fuel_price_usd_per_gal": body.fuel_price_usd_per_gal,
                "route_preference": body.route_preference,
                "status": "processing",
            }
        )
        .execute()
    )
    if not request_row.data:
        raise HTTPException(status_code=500, detail="Failed to create route request")

    route_request_id = request_row.data[0]["id"]

    try:
        checkpoint_candidates = (
            supabase.table("airports")
            .select(
                "id, ident, icao_code, iata_code, name, municipality, "
                "latitude, longitude, airport_type, longest_runway_ft"
            )
            .gte("latitude", CONUS_MIN_LAT)
            .lte("latitude", CONUS_MAX_LAT)
            .gte("longitude", CONUS_MIN_LON)
            .lte("longitude", CONUS_MAX_LON)
            .in_("airport_type", ["medium_airport", "large_airport"])
            .not_.is_("icao_code", "null")
            .like("icao_code", "K%")
            .limit(5000)
            .execute()
        ).data or []

        calc_result = await route_calculator.calculate(
            departure=departure,
            destination=destination,
            aircraft=aircraft,
            fuel_price=body.fuel_price_usd_per_gal,
            supabase=supabase,
            checkpoint_candidates=checkpoint_candidates,
            departure_time=body.departure_time,
            route_preference=body.route_preference,
        )

        primary = calc_result["primary"]
        alternate = calc_result.get("alternate")

        result_row = (
            supabase.table("route_results")
            .insert(
                {
                    "route_request_id": route_request_id,
                    "primary_distance_nm": primary.distance_nm,
                    "primary_ete_minutes": primary.ete_minutes,
                    "primary_fuel_burn_gal": primary.fuel_burn_gal,
                    "primary_fuel_cost_usd": primary.fuel_cost_usd,
                    "primary_score": primary.score,
                    "primary_path": path_from_waypoints(primary.waypoints),
                    "alternate_distance_nm": alternate.distance_nm if alternate else None,
                    "alternate_ete_minutes": alternate.ete_minutes if alternate else None,
                    "alternate_fuel_burn_gal": alternate.fuel_burn_gal if alternate else None,
                    "alternate_fuel_cost_usd": alternate.fuel_cost_usd if alternate else None,
                    "alternate_score": alternate.score if alternate else None,
                    "alternate_path": path_from_waypoints(alternate.waypoints) if alternate else None,
                    "score_breakdown": primary.score_breakdown,
                    "normalized_score_breakdown": primary.score_breakdown,
                    "fuel_breakdown": primary.fuel_breakdown,
                    "weather_checkpoints": calc_result.get("weather_checkpoints") or [],
                    "route_candidates": calc_result.get("candidate_summaries") or [],
                    "wind_data_quality": calc_result.get("wind_data_quality"),
                    "warnings": calc_result["warnings"],
                    "departure_weather": calc_result["departure_weather"],
                    "destination_weather": calc_result["destination_weather"],
                }
            )
            .execute()
        )
        if not result_row.data:
            raise HTTPException(status_code=500, detail="Failed to save route result")

        result_id = result_row.data[0]["id"]

        if calc_result.get("live_data_snapshot"):
            try:
                from app.services.live_data.live_data_orchestrator import live_data_orchestrator
                from app.services.live_data.types import LiveDataSnapshot

                snap_dict = calc_result["live_data_snapshot"]
                snap_dict["route_id"] = result_id
                snapshot = LiveDataSnapshot(
                    route_id=result_id,
                    fetched_at=snap_dict["fetched_at"],
                    departure_icao=snap_dict.get("departure_icao"),
                    destination_icao=snap_dict.get("destination_icao"),
                    weather=snap_dict.get("weather", {}),
                    restrictions=snap_dict.get("restrictions", {}),
                    faa_status=snap_dict.get("faa_status", {}),
                    confidence=snap_dict.get("confidence", {}),
                    sources=snap_dict.get("sources", {}),
                    warnings=snap_dict.get("warnings", []),
                )
                await live_data_orchestrator.persist_snapshot(supabase, result_id, user_id, snapshot)
            except Exception as exc:
                logger.debug("Live data snapshot persist skipped: %s", exc)

        for seg in primary.segments:
            supabase.table("route_segments").insert(
                {"route_result_id": result_id, "route_variant": "primary", **seg}
            ).execute()

        if alternate:
            for seg in alternate.segments:
                supabase.table("route_segments").insert(
                    {"route_result_id": result_id, "route_variant": "alternate", **seg}
                ).execute()

        diversion_details = []
        for rank, div in enumerate(calc_result["diversion_airports"], start=1):
            supabase.table("diversion_airports").insert(
                {
                    "route_result_id": result_id,
                    "airport_id": div["airport"]["id"],
                    "distance_from_route_nm": div["distance_from_route_nm"],
                    "rank": rank,
                }
            ).execute()
            diversion_details.append(
                {
                    "airport": AirportSummary(**row_to_airport(div["airport"])),
                    "distance_from_route_nm": div["distance_from_route_nm"],
                    "rank": rank,
                }
            )

        try:
            route_result_payload = {
                **result_row.data[0],
                "normalized_score_breakdown": primary.score_breakdown,
                "route_candidates": calc_result.get("candidate_summaries"),
                "live_data_snapshot": calc_result.get("live_data_snapshot"),
            }
            log_training_samples(
                supabase,
                route_request_id,
                result_id,
                request_row.data[0],
                route_result_payload,
                aircraft,
                primary.segments,
                calc_result["diversion_airports"],
            )
            if calc_result.get("delay_prediction"):
                dp = calc_result["delay_prediction"]
                log_model_prediction(
                    supabase,
                    result_id,
                    dp.get("model_name", "rules_baseline_v1"),
                    dp.get("model_version", "v1"),
                    "delay_risk",
                    dp,
                    features=calc_result.get("delay_features"),
                    confidence=dp.get("confidence"),
                )
            if calc_result.get("ete_prediction"):
                ep = calc_result["ete_prediction"]
                log_model_prediction(
                    supabase,
                    result_id,
                    ep.get("model_name", "deterministic_engine_v1"),
                    ep.get("model_version", "v1"),
                    "ete_prediction",
                    ep,
                    features=calc_result.get("ete_features"),
                    confidence=ep.get("confidence"),
                )
        except Exception as exc:
            logger.debug("ML logging skipped: %s", exc)

        supabase.table("route_requests").update(
            {"status": "completed", "updated_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", route_request_id).execute()

        logger.info(
            "route_calculation_completed",
            extra={"route_result_id": result_id, "score": primary.score},
        )

        return _build_route_result_detail(
            result_id,
            route_request_id,
            "completed",
            calc_result,
            departure,
            destination,
            aircraft,
            diversion_details,
            result_row.data[0]["created_at"],
            body.route_preference,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Route calculation failed: %s", exc)
        supabase.table("route_requests").update(
            {
                "status": "failed",
                "error_message": str(exc),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", route_request_id).execute()
        raise HTTPException(status_code=500, detail=f"Route calculation failed: {exc}") from exc


@router.get("/routes/{route_id}", response_model=RouteResultDetail)
async def get_route(
    route_id: RouteId,
    user_id: str = Depends(get_current_user_id),
) -> RouteResultDetail:
    supabase = get_supabase()

    result, request, dep, dest, aircraft, segment_rows, diversion_details, _ = await load_route_bundle(
        supabase, route_id, user_id
    )

    score_breakdown = result.get("normalized_score_breakdown") or result.get("score_breakdown")
    delay_prediction, ete_prediction = _load_ml_predictions(supabase, route_id)

    live_snap = None
    live_data_snapshot = None
    try:
        live_snap = (
            supabase.table("live_data_snapshots")
            .select("snapshot")
            .eq("route_result_id", route_id)
            .order("fetched_at", desc=True)
            .limit(1)
            .execute()
        )
        if live_snap.data:
            live_data_snapshot = live_snap.data[0].get("snapshot")
    except Exception as exc:
        logger.debug("live_data_snapshots lookup skipped: %s", exc)

    try:
        validated_segments = [RouteSegmentDetail(**row).model_dump() for row in segment_rows]
    except Exception as exc:
        logger.warning("Route segment validation failed, omitting segments: %s", exc)
        validated_segments = []

    return RouteResultDetail(
        id=result["id"],
        route_request_id=result["route_request_id"],
        status=request["status"],
        primary_distance_nm=result["primary_distance_nm"],
        primary_ete_minutes=result["primary_ete_minutes"],
        primary_fuel_burn_gal=result["primary_fuel_burn_gal"],
        primary_fuel_cost_usd=result["primary_fuel_cost_usd"],
        primary_score=result["primary_score"],
        primary_path=result["primary_path"],
        alternate_distance_nm=result.get("alternate_distance_nm"),
        alternate_ete_minutes=result.get("alternate_ete_minutes"),
        alternate_fuel_burn_gal=result.get("alternate_fuel_burn_gal"),
        alternate_fuel_cost_usd=result.get("alternate_fuel_cost_usd"),
        alternate_score=result.get("alternate_score"),
        alternate_path=result.get("alternate_path"),
        score_breakdown=score_breakdown,
        normalized_score_breakdown=score_breakdown,
        fuel_breakdown=result.get("fuel_breakdown"),
        weather_checkpoints=result.get("weather_checkpoints") or [],
        route_candidates=result.get("route_candidates") or [],
        wind_data_quality=result.get("wind_data_quality"),
        route_preference=request.get("route_preference"),
        fuel_price_usd_per_gal=request.get("fuel_price_usd_per_gal"),
        delay_prediction=delay_prediction,
        ete_prediction=ete_prediction,
        warnings=result.get("warnings") or [],
        departure_weather=result.get("departure_weather"),
        destination_weather=result.get("destination_weather"),
        departure_status=_faa_status_from_weather(result.get("departure_weather")),
        destination_status=_faa_status_from_weather(result.get("destination_weather")),
        segments=validated_segments,
        diversion_airports=diversion_details,
        departure_airport=AirportSummary(**row_to_airport(dep)),
        destination_airport=AirportSummary(**row_to_airport(dest)),
        aircraft_profile=AircraftProfile(**aircraft),
        created_at=result["created_at"],
        live_data_snapshot=live_data_snapshot,
    )


def _load_live_snapshot(supabase: Any, route_id: str) -> dict[str, Any] | None:
    row = (
        supabase.table("live_data_snapshots")
        .select("snapshot")
        .eq("route_result_id", route_id)
        .order("fetched_at", desc=True)
        .limit(1)
        .execute()
    )
    if row.data:
        return row.data[0].get("snapshot")
    return None


@router.post("/routes/{route_id}/live-data/refresh")
async def refresh_live_data(
    route_id: RouteId,
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    """Refresh live TFR, hazard, and NOTAM snapshot without full recalculation."""
    supabase = get_supabase()
    route_data, request_data, dep, dest, aircraft, segments, diversions = await _load_route_bundle(
        supabase, route_id, user_id
    )
    dep_icao = dep.get("icao_code") or dep.get("ident")
    dest_icao = dest.get("icao_code") or dest.get("ident")
    path = route_data.get("primary_path") or []
    route_path = [{"lat": p["lat"], "lon": p["lon"]} for p in path if "lat" in p and "lon" in p]

    from app.services.live_data.live_data_orchestrator import live_data_orchestrator
    from app.services.live_data.types import LiveDataSnapshot

    snapshot, timings = await live_data_orchestrator.build_snapshot(
        route_id=route_id,
        departure_icao=dep_icao,
        destination_icao=dest_icao,
        route_path=route_path,
        supabase=supabase,
    )
    snap = LiveDataSnapshot(
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
    )
    await live_data_orchestrator.persist_snapshot(supabase, route_id, user_id, snap)
    return {
        "live_data_snapshot": snapshot.to_dict(),
        "provider_timings": timings,
        "disclaimer": snapshot.to_dict()["disclaimer"],
    }


@router.get("/copilot/status", response_model=CopilotStatusResponse)
async def copilot_status() -> CopilotStatusResponse:
    from app.config import settings

    return CopilotStatusResponse(
        enabled=is_copilot_available(),
        model=settings.gemini_model if is_copilot_available() else None,
        suggested_questions=[
            "Summarize the biggest risks for this route.",
            "Compare primary and alternate routes.",
            "Which segment has the strongest headwind?",
        ],
    )


@router.get("/routes/{route_id}/copilot/suggestions", response_model=CopilotStatusResponse)
async def copilot_route_suggestions(
    route_id: RouteId,
    user_id: str = Depends(get_current_user_id),
) -> CopilotStatusResponse:
    from app.config import settings

    supabase = get_supabase()
    ctx = await get_route_context(supabase, route_id, user_id, include_full_segments=False)
    questions = generate_suggested_questions(ctx)
    return CopilotStatusResponse(
        enabled=is_copilot_available(),
        model=settings.gemini_model if is_copilot_available() else None,
        suggested_questions=questions,
    )


@router.post("/routes/{route_id}/brief/draft", response_model=RouteBriefResponse, status_code=201)
async def draft_route_brief(
    route_id: RouteId,
    user_id: str = Depends(get_current_user_id),
) -> RouteBriefResponse:
    supabase = get_supabase()
    route_data, request_data, dep, dest, aircraft, segments, diversions = await _load_route_bundle(
        supabase, route_id, user_id
    )

    route_payload = {**route_data, "id": route_id}
    content = build_deterministic_brief(
        route_payload,
        request_data,
        segments,
        diversions,
        dep,
        dest,
        aircraft,
    )

    brief_row = (
        supabase.table("route_briefs")
        .insert(
            {
                "route_result_id": route_id,
                "brief_type": "deterministic",
                "content": content,
            }
        )
        .execute()
    )

    return RouteBriefResponse(
        route_result_id=route_id,
        brief_type="deterministic",
        content=content,
        created_at=brief_row.data[0]["created_at"] if brief_row.data else None,
    )


@router.post("/routes/{route_id}/copilot/chat", response_model=CopilotChatResponse)
async def copilot_chat(
    route_id: RouteId,
    body: CopilotChatRequest,
    user_id: str = Depends(get_current_user_id),
) -> CopilotChatResponse:
    safety_note = (
        "Educational tool only — not certified flight-planning software. "
        "Verify all operational decisions with official briefings, NOTAMs, POH, dispatch, and pilot judgment."
    )

    if not is_copilot_available():
        raise HTTPException(
            status_code=503,
            detail="AeroRoute Copilot is not enabled. Set COPILOT_ENABLED=true and GEMINI_API_KEY in apps/api/.env",
        )

    supabase = get_supabase()

    try:
        intent, context, sources_used = await build_intent_context(
            supabase, route_id, user_id, body.question
        )
    except Exception as exc:
        logger.exception("Copilot context build failed for route %s: %s", route_id, exc)
        raise HTTPException(status_code=500, detail=f"Could not load route context: {exc}") from exc

    try:
        answer, sources = await answer_with_llm(
            context,
            body.question,
            intent=intent,
            sources_used=sources_used,
            include_operational_safety=intent in OPERATIONAL_INTENTS,
        )
    except RuntimeError as exc:
        logger.exception("Copilot LLM failed for route %s: %s", route_id, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    try:
        supabase.table("route_briefs").insert(
            {
                "route_result_id": route_id,
                "brief_type": "llm_chat",
                "content": {
                    "question": body.question,
                    "answer": answer,
                    "intent": intent,
                    "sources_used": sources,
                },
            }
        ).execute()
    except Exception as exc:
        logger.debug("Could not persist copilot chat: %s", exc)

    logger.info(
        "copilot_chat_completed",
        extra={"route_id": route_id, "user_id": user_id, "intent": intent},
    )

    return CopilotChatResponse(
        answer=answer,
        sources_used=sources,
        safety_note=safety_note,
        intent=intent,
    )
