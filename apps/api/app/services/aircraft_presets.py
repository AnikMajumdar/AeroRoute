from __future__ import annotations

import logging

from supabase import Client

from app.data.aircraft_presets import AIRCRAFT_PRESETS

logger = logging.getLogger(__name__)


def ensure_aircraft_presets(supabase: Client) -> list[dict]:
    """Upsert canonical preset aircraft and return all preset rows."""
    existing = (
        supabase.table("aircraft_profiles")
        .select("*")
        .eq("is_preset", True)
        .execute()
    )
    by_name = {row["name"]: row for row in (existing.data or [])}

    for preset in AIRCRAFT_PRESETS:
        payload = {
            "name": preset["name"],
            "cruise_speed_kt": preset["cruise_speed_kt"],
            "fuel_burn_gph": preset["fuel_burn_gph"],
            "cruise_altitude_ft": preset["cruise_altitude_ft"],
            "climb_fuel_gal": preset["climb_fuel_gal"],
            "climb_time_min": preset["climb_time_min"],
            "descent_time_min": preset["descent_time_min"],
            "reserve_fuel_min": preset["reserve_fuel_min"],
            "min_runway_ft": preset["min_runway_ft"],
            "is_preset": True,
            "user_id": None,
        }
        if preset["name"] in by_name:
            supabase.table("aircraft_profiles").update(
                {k: v for k, v in payload.items() if k not in ("name", "is_preset", "user_id")}
            ).eq("id", by_name[preset["name"]]["id"]).execute()
        else:
            result = supabase.table("aircraft_profiles").insert(payload).execute()
            if result.data:
                by_name[preset["name"]] = result.data[0]

    refreshed = (
        supabase.table("aircraft_profiles")
        .select("*")
        .eq("is_preset", True)
        .order("name")
        .execute()
    )
    rows = refreshed.data or []
    if not rows:
        logger.error("Failed to ensure aircraft presets in database")
    return rows
