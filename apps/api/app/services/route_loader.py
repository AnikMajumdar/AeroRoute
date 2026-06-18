from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.auth import row_to_airport


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
    result = supabase.table("route_results").select("*").eq("id", route_id).maybe_single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Route not found")

    request = (
        supabase.table("route_requests")
        .select("*")
        .eq("id", result.data["route_request_id"])
        .maybe_single()
        .execute()
    )
    if not request.data or request.data["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Route not found")

    dep = supabase.table("airports").select("*").eq("id", request.data["departure_airport_id"]).single().execute()
    dest = (
        supabase.table("airports").select("*").eq("id", request.data["destination_airport_id"]).single().execute()
    )
    aircraft = (
        supabase.table("aircraft_profiles")
        .select("*")
        .eq("id", request.data["aircraft_profile_id"])
        .single()
        .execute()
    )
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
        result.data,
        request.data,
        dep.data,
        dest.data,
        aircraft.data,
        segments,
        diversions,
        alternate_segments,
    )
