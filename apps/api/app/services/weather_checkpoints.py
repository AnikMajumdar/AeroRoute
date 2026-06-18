from __future__ import annotations

import logging
from typing import Any

from app.geo.utils import cross_track_distance_nm, haversine_nm, is_on_route_between
from app.services.aviation_weather import aviation_weather_client

logger = logging.getLogger(__name__)

WEATHER_CATEGORY_PENALTY = {"VFR": 0, "MVFR": 15, "IFR": 35, "LIFR": 55}
CATEGORY_ORDER = {"VFR": 0, "MVFR": 1, "IFR": 2, "LIFR": 3}

# Checkpoints must be between dep/dest with this buffer from each end (NM)
END_MARGIN_NM = 25.0
MAX_CROSS_TRACK_NM = 75.0


def normalize_flight_category(category: Any) -> str:
    """METAR APIs may return null or omit flight category."""
    if category is None:
        return "UNKNOWN"
    text = str(category).strip().upper()
    return text if text else "UNKNOWN"


def _is_eligible_checkpoint(
    airport: dict[str, Any],
    route_waypoints: list[tuple[float, float]],
    departure_id: str,
    destination_id: str,
) -> bool:
    if airport["id"] in (departure_id, destination_id):
        return False
    icao = airport.get("icao_code")
    if not icao or not str(icao).startswith("K"):
        return False
    if airport.get("airport_type") not in ("medium_airport", "large_airport"):
        return False

    dep_lat, dep_lon = route_waypoints[0]
    dest_lat, dest_lon = route_waypoints[-1]
    apt_lat, apt_lon = airport["latitude"], airport["longitude"]

    if not is_on_route_between(dep_lat, dep_lon, dest_lat, dest_lon, apt_lat, apt_lon, END_MARGIN_NM):
        return False

    ct = cross_track_distance_nm(dep_lat, dep_lon, dest_lat, dest_lon, apt_lat, apt_lon)
    return ct <= MAX_CROSS_TRACK_NM


def select_checkpoint_airports(
    route_waypoints: list[tuple[float, float]],
    candidate_airports: list[dict[str, Any]],
    departure_id: str,
    destination_id: str,
    min_count: int = 1,
    max_count: int = 5,
) -> list[dict[str, Any]]:
    """Pick en-route METAR checkpoints strictly between departure and destination."""
    dep_lat, dep_lon = route_waypoints[0]
    dest_lat, dest_lon = route_waypoints[-1]
    total_dist = haversine_nm(dep_lat, dep_lon, dest_lat, dest_lon)

    if total_dist < END_MARGIN_NM * 3:
        return []

    # Scale checkpoint count to route length
    max_count = min(max_count, max(1, int(total_dist / 200)))
    min_count = min(min_count, max_count)
    spacing_nm = max(100.0, total_dist / (max_count + 1))

    eligible: list[dict[str, Any]] = []
    for airport in candidate_airports:
        if not _is_eligible_checkpoint(airport, route_waypoints, departure_id, destination_id):
            continue
        apt_lat, apt_lon = airport["latitude"], airport["longitude"]
        ct = cross_track_distance_nm(dep_lat, dep_lon, dest_lat, dest_lon, apt_lat, apt_lon)
        along = haversine_nm(dep_lat, dep_lon, apt_lat, apt_lon)
        eligible.append({**airport, "_cross_track_nm": ct, "_along_nm": along})

    eligible.sort(key=lambda a: a["_along_nm"])

    selected: list[dict[str, Any]] = []
    last_along = -spacing_nm

    for airport in eligible:
        if len(selected) >= max_count:
            break
        if airport["_along_nm"] - last_along < spacing_nm * 0.5 and selected:
            continue
        selected.append(airport)
        last_along = airport["_along_nm"]

    if len(selected) < min_count:
        for airport in eligible:
            if airport not in selected:
                selected.append(airport)
            if len(selected) >= min_count:
                break

    return selected[:max_count]


async def fetch_checkpoint_weather(
    checkpoints: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for airport in checkpoints:
        icao = airport.get("icao_code") or airport.get("ident")
        metar = await aviation_weather_client.get_metar(icao) if icao else None
        category = normalize_flight_category((metar or {}).get("flight_category"))
        results.append(
            {
                "airport_id": airport["id"],
                "icao": icao,
                "name": airport.get("name"),
                "latitude": airport["latitude"],
                "longitude": airport["longitude"],
                "flight_category": category,
                "metar": metar,
                "weather_penalty": WEATHER_CATEGORY_PENALTY.get(category, 10),
                "distance_along_route_nm": round(airport.get("_along_nm", 0), 1),
                "cross_track_nm": round(airport.get("_cross_track_nm", 0), 1),
            }
        )
    return results


def best_weather_checkpoint(checkpoints: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not checkpoints:
        return None
    scored = [
        c
        for c in checkpoints
        if normalize_flight_category(c.get("flight_category")) != "UNKNOWN"
    ]
    if not scored:
        return checkpoints[0] if checkpoints else None
    scored.sort(
        key=lambda c: CATEGORY_ORDER.get(normalize_flight_category(c.get("flight_category")), 99)
    )
    return scored[0]
