from __future__ import annotations

from typing import Any


def airport_snapshot(airport: dict[str, Any], role: str) -> dict[str, Any]:
    """Structured airport facts for copilot / briefings."""
    return {
        "role": role,
        "icao": airport.get("icao_code") or airport.get("ident"),
        "iata": airport.get("iata_code"),
        "name": airport.get("name"),
        "municipality": airport.get("municipality"),
        "airport_type": airport.get("airport_type"),
        "latitude": airport.get("latitude"),
        "longitude": airport.get("longitude"),
        "elevation_ft": airport.get("elevation_ft"),
        "longest_runway_ft": airport.get("longest_runway_ft"),
    }


def aircraft_snapshot(aircraft: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": aircraft.get("name"),
        "cruise_speed_kt": aircraft.get("cruise_speed_kt"),
        "fuel_burn_gph": float(aircraft["fuel_burn_gph"]) if aircraft.get("fuel_burn_gph") else None,
        "cruise_altitude_ft": aircraft.get("cruise_altitude_ft"),
        "climb_fuel_gal": aircraft.get("climb_fuel_gal"),
        "climb_time_min": aircraft.get("climb_time_min"),
        "descent_time_min": aircraft.get("descent_time_min"),
        "reserve_fuel_min": aircraft.get("reserve_fuel_min"),
        "min_runway_ft": aircraft.get("min_runway_ft"),
        "is_preset": aircraft.get("is_preset"),
    }


def planning_economics(request: dict[str, Any], route: dict[str, Any]) -> dict[str, Any]:
    """Fuel price and cost figures from this route plan (not market averages)."""
    fuel_price = float(request.get("fuel_price_usd_per_gal") or 0)
    trip_gal = route.get("primary_fuel_burn_gal")
    trip_cost = route.get("primary_fuel_cost_usd")
    breakdown = route.get("fuel_breakdown") or {}
    total_required = breakdown.get("total_required_gal")
    total_cost = (float(total_required) * fuel_price) if total_required and fuel_price else None
    return {
        "fuel_price_usd_per_gal": fuel_price,
        "note": (
            "This is the user-entered planning fuel price for this route, "
            "not a live market or national average."
        ),
        "primary_trip_fuel_gal": trip_gal,
        "primary_trip_fuel_cost_usd": trip_cost,
        "total_required_fuel_gal": total_required,
        "estimated_total_fuel_cost_usd": total_cost,
        "reserve_fuel_gal": breakdown.get("reserve_fuel_gal"),
    }


def runway_suitability(
    dep: dict[str, Any],
    dest: dict[str, Any],
    aircraft: dict[str, Any],
    diversions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Runway length vs aircraft minimum for dep, dest, and diversions."""
    min_rw = int(aircraft.get("min_runway_ft") or 0)

    def check(apt: dict[str, Any], label: str) -> dict[str, Any]:
        rw = apt.get("longest_runway_ft")
        meets = rw is not None and min_rw > 0 and int(rw) >= min_rw
        return {
            "airport": apt.get("icao_code") or apt.get("ident"),
            "longest_runway_ft": rw,
            "aircraft_min_runway_ft": min_rw,
            "meets_aircraft_minimum": meets if rw is not None and min_rw else None,
            "runway_margin_ft": (int(rw) - min_rw) if rw is not None and min_rw else None,
        }

    return {
        "aircraft_min_runway_ft": min_rw,
        "departure": check(dep, "departure"),
        "destination": check(dest, "destination"),
        "diversions": [
            {
                **check(d.get("airport") or {}, "diversion"),
                "rank": i + 1,
                "distance_from_route_nm": d.get("distance_from_route_nm"),
            }
            for i, d in enumerate(diversions)
        ],
    }


def segment_snapshots(segments: list[dict[str, Any]], variant: str = "primary") -> list[dict[str, Any]]:
    return [
        {
            "variant": variant,
            "index": s.get("segment_index"),
            "distance_nm": s.get("distance_nm"),
            "bearing_deg": s.get("bearing_deg"),
            "headwind_kt": s.get("headwind_component_kt"),
            "tailwind_kt": s.get("tailwind_component_kt"),
            "groundspeed_kt": s.get("groundspeed_kt"),
            "ete_minutes": s.get("ete_minutes"),
            "wind_speed_kt": s.get("wind_speed_kt"),
            "wind_direction_deg": s.get("wind_direction_deg"),
            "wind_source": s.get("wind_source"),
            "wind_altitude_ft": s.get("wind_altitude_ft"),
            "wind_pressure_level_hpa": s.get("wind_pressure_level_hpa"),
            "start_lat": s.get("start_lat"),
            "start_lon": s.get("start_lon"),
            "end_lat": s.get("end_lat"),
            "end_lon": s.get("end_lon"),
        }
        for s in segments
    ]


def metar_snapshot(metar: dict[str, Any] | None) -> dict[str, Any]:
    if not metar:
        return {"available": False}
    return {
        "available": True,
        "flight_category": metar.get("flight_category"),
        "raw": metar.get("raw") or metar.get("rawOb") or metar.get("raw_text"),
        "observation_time": metar.get("observation_time") or metar.get("obsTime"),
        "temp_c": metar.get("temp_c") or metar.get("temp"),
        "dewpoint_c": metar.get("dewpoint_c") or metar.get("dewp"),
        "wind_speed_kt": metar.get("wind_speed_kt") or metar.get("wspd"),
        "wind_direction_deg": metar.get("wind_direction_deg") or metar.get("wdir"),
        "visibility_sm": metar.get("visibility_sm") or metar.get("visib"),
        "altimeter_inhg": metar.get("altimeter_inhg") or metar.get("altim"),
        "clouds": metar.get("clouds") or metar.get("cloudLayers"),
    }


def taf_snapshot(taf: dict[str, Any] | None) -> dict[str, Any]:
    if not taf:
        return {"available": False}
    return {
        "available": True,
        "raw": taf.get("raw") or taf.get("rawTAF"),
        "issue_time": taf.get("issue_time") or taf.get("issueTime"),
        "valid_from": taf.get("valid_from") or taf.get("validTimeFrom"),
        "valid_to": taf.get("valid_to") or taf.get("validTimeTo"),
    }


def faa_status_snapshot(status: dict[str, Any] | None) -> dict[str, Any]:
    if not status:
        return {"available": False}
    return {
        "available": True,
        "status": status.get("status"),
        "delay_minutes": status.get("delay_minutes", 0),
        "is_closed": status.get("is_closed", False),
        "ground_stop": status.get("ground_stop", False),
        "ground_delay": status.get("ground_delay", False),
        "parse_success": status.get("parse_success", True),
        "summary": status.get("summary") or status.get("status_text"),
        "warnings": status.get("warnings") or [],
    }


def checkpoint_snapshots(checkpoints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "icao": cp.get("icao"),
            "name": cp.get("name"),
            "flight_category": cp.get("flight_category"),
            "distance_along_route_nm": cp.get("distance_along_route_nm"),
            "cross_track_nm": cp.get("cross_track_nm"),
            "weather_penalty": cp.get("weather_penalty"),
            "metar": metar_snapshot((cp.get("metar") if isinstance(cp.get("metar"), dict) else None)),
        }
        for cp in checkpoints
    ]


def build_quick_facts(
    route: dict[str, Any],
    request: dict[str, Any],
    dep: dict[str, Any],
    dest: dict[str, Any],
    aircraft: dict[str, Any],
    diversions: list[dict[str, Any]],
) -> dict[str, Any]:
    dep_icao = dep.get("icao_code") or dep.get("ident")
    dest_icao = dest.get("icao_code") or dest.get("ident")
    div_count = len(diversions)
    top_div = diversions[0] if diversions else None
    top_div_icao = None
    if top_div:
        top_div_icao = (top_div.get("airport") or {}).get("icao_code")

    summary_lines = [
        f"Route {dep_icao} ({dep.get('name')}) → {dest_icao} ({dest.get('name')})",
        f"Primary: {route.get('primary_distance_nm')} NM, ETE {route.get('primary_ete_minutes')} min, score {route.get('primary_score')}/100",
        f"Aircraft: {aircraft.get('name')} — cruise {aircraft.get('cruise_speed_kt')} kt, min runway {aircraft.get('min_runway_ft')} ft",
        f"Departure runway: {dep.get('longest_runway_ft')} ft; destination runway: {dest.get('longest_runway_ft')} ft",
        f"Fuel planning price: ${request.get('fuel_price_usd_per_gal')}/gal; trip fuel {route.get('primary_fuel_burn_gal')} gal",
        f"Diversion airports along route: {div_count}" + (f" (nearest: {top_div_icao})" if top_div_icao else ""),
        f"Route preference: {request.get('route_preference', 'balanced')}",
    ]

    return {
        "summary_lines": summary_lines,
        "departure_icao": dep_icao,
        "destination_icao": dest_icao,
        "primary_distance_nm": route.get("primary_distance_nm"),
        "primary_ete_minutes": route.get("primary_ete_minutes"),
        "primary_score": route.get("primary_score"),
        "alternate_score": route.get("alternate_score"),
        "diversion_count": div_count,
        "wind_data_quality": route.get("wind_data_quality"),
    }

