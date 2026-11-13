from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.auth import row_to_airport
from app.db_utils import fetch_one


async def load_route_bundle(
    supabase: Any, route_id: str, user_id: str
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Load route result and related rows; raise 404 if not found or not owned."""
    result = fetch_one(supabase.table("route_results").select("*").eq("id", route_id))
    if not result:
        raise HTTPException(status_code=404, detail="Route not found")

    request = fetch_one(supabase.table("route_requests").select("*").eq("id", result["route_request_id"]))
    if not request or request["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Route not found")

    dep = fetch_one(supabase.table("airports").select("*").eq("id", request["departure_airport_id"]))
    dest = fetch_one(supabase.table("airports").select("*").eq("id", request["destination_airport_id"]))
    aircraft = fetch_one(supabase.table("aircraft_profiles").select("*").eq("id", request["aircraft_profile_id"]))
    if not dep or not dest or not aircraft:
        raise HTTPException(status_code=500, detail="Route data is incomplete")
    segments = (
        supabase.table("route_segments")
        .select("*")
        .eq("route_result_id", route_id)
        .eq("route_variant", "primary")
        .order("segment_index")
        .execute()
    ).data or []

    alternate_segments = (
        supabase.table("route_segments")
        .select("*")
        .eq("route_result_id", route_id)
        .eq("route_variant", "alternate")
        .order("segment_index")
        .execute()
    ).data or []

    diversions_result = (
        supabase.table("diversion_airports")
        .select("*, airports(*)")
        .eq("route_result_id", route_id)
        .order("rank")
        .execute()
    )
    diversions = []
    for div in diversions_result.data or []:
        diversions.append(
            {
                "airport": row_to_airport(div.get("airports") or {}),
                "distance_from_route_nm": div["distance_from_route_nm"],
                "rank": div.get("rank"),
            }
        )

    return (
        result,
        request,
        dep,
        dest,
        aircraft,
        segments,
        diversions,
        alternate_segments,
    )
