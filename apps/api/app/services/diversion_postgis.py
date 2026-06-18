from __future__ import annotations

import logging
from typing import Any

from app.geo.utils import cross_track_distance_nm, haversine_nm, is_in_route_corridor
from app.services.wind_altitude import NM_TO_M

logger = logging.getLogger(__name__)

MAX_DIVERSION_AIRPORTS = 10

# (min_nm_from_route, max_nm_from_route) search tiers — widen until results found
DIVERSION_SEARCH_TIERS: list[tuple[float, float]] = [
    (25.0, 50.0),
    (15.0, 75.0),
    (8.0, 100.0),
    (3.0, 150.0),
]


def _row_to_diversion(row: dict[str, Any]) -> dict[str, Any]:
    dist_nm = float(row["distance_from_route_m"]) / NM_TO_M
    return {
        "airport": {
            "id": row["airport_id"],
            "ident": row["ident"],
            "icao_code": row.get("icao_code"),
            "iata_code": row.get("iata_code"),
            "name": row.get("name") or row["ident"],
            "municipality": row.get("municipality"),
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "airport_type": row.get("airport_type", "small_airport"),
            "longest_runway_ft": row.get("longest_runway_ft"),
        },
        "distance_from_route_nm": round(dist_nm, 2),
    }


def _postgis_search(
    supabase: Any,
    dep_lon: float,
    dep_lat: float,
    dest_lon: float,
    dest_lat: float,
    departure_id: str,
    destination_id: str,
    min_runway_ft: int,
    min_nm: float,
    max_nm: float,
) -> list[dict[str, Any]]:
    result = supabase.rpc(
        "find_diversion_airports_in_corridor",
        {
            "dep_lon": dep_lon,
            "dep_lat": dep_lat,
            "dest_lon": dest_lon,
            "dest_lat": dest_lat,
            "min_dist_m": min_nm * NM_TO_M,
            "max_dist_m": max_nm * NM_TO_M,
            "min_runway_ft": min_runway_ft,
            "exclude_dep_id": departure_id,
            "exclude_dest_id": destination_id,
            "result_limit": MAX_DIVERSION_AIRPORTS,
        },
    ).execute()
    return [_row_to_diversion(row) for row in (result.data or [])]


def _python_fallback_search(
    candidates: list[dict[str, Any]],
    dep_lat: float,
    dep_lon: float,
    dest_lat: float,
    dest_lon: float,
    departure_id: str,
    destination_id: str,
    min_runway_ft: int,
    max_cross_track_nm: float = 120.0,
) -> list[dict[str, Any]]:
    """Nearest suitable airports along the route when PostGIS corridor is empty."""
    route = [(dep_lat, dep_lon), (dest_lat, dest_lon)]
    found: list[dict[str, Any]] = []

    for airport in candidates:
        if airport["id"] in (departure_id, destination_id):
            continue
        runway = airport.get("longest_runway_ft") or 0
        if runway < min_runway_ft:
            continue
        apt_type = airport.get("airport_type", "")
        if apt_type not in ("small_airport", "medium_airport", "large_airport"):
            continue
        apt_lat, apt_lon = airport["latitude"], airport["longitude"]
        if not is_in_route_corridor(dep_lat, dep_lon, dest_lat, dest_lon, apt_lat, apt_lon):
            continue
        ct = cross_track_distance_nm(dep_lat, dep_lon, dest_lat, dest_lon, apt_lat, apt_lon)
        if ct > max_cross_track_nm:
            continue
        found.append(
            {
                "airport": airport,
                "distance_from_route_nm": round(ct, 2),
            }
        )

    found.sort(key=lambda d: d["distance_from_route_nm"])
    return found[:MAX_DIVERSION_AIRPORTS]


def _nearest_runway_fallback(
    candidates: list[dict[str, Any]],
    dep_lat: float,
    dep_lon: float,
    dest_lat: float,
    dest_lon: float,
    departure_id: str,
    destination_id: str,
    min_runway_ft: int,
) -> list[dict[str, Any]]:
    """Last resort: closest suitable airport to route midpoint (still not dep/dest)."""
    mid_lat = (dep_lat + dest_lat) / 2
    mid_lon = (dep_lon + dest_lon) / 2
    best: dict[str, Any] | None = None
    best_dist = float("inf")

    for airport in candidates:
        if airport["id"] in (departure_id, destination_id):
            continue
        if (airport.get("longest_runway_ft") or 0) < min_runway_ft:
            continue
        apt_type = airport.get("airport_type", "")
        if apt_type not in ("small_airport", "medium_airport", "large_airport"):
            continue
        d = haversine_nm(mid_lat, mid_lon, airport["latitude"], airport["longitude"])
        if d < best_dist:
            best_dist = d
            best = airport

    if not best:
        return []
    ct = cross_track_distance_nm(dep_lat, dep_lon, dest_lat, dest_lon, best["latitude"], best["longitude"])
    return [{"airport": best, "distance_from_route_nm": round(ct, 2)}]


def find_diversion_airports_postgis(
    supabase: Any,
    dep_lon: float,
    dep_lat: float,
    dest_lon: float,
    dest_lat: float,
    departure_id: str,
    destination_id: str,
    min_runway_ft: int = 3000,
    fallback_candidates: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Query airports within route corridor; widen search and fall back until at least one found."""
    diversions: list[dict[str, Any]] = []

    try:
        for min_nm, max_nm in DIVERSION_SEARCH_TIERS:
            diversions = _postgis_search(
                supabase,
                dep_lon,
                dep_lat,
                dest_lon,
                dest_lat,
                departure_id,
                destination_id,
                min_runway_ft,
                min_nm,
                max_nm,
            )
            if diversions:
                logger.info("Diversion search found %d at %.0f-%.0f NM", len(diversions), min_nm, max_nm)
                break
    except Exception as exc:
        logger.warning("PostGIS diversion query failed: %s", exc)
        diversions = []

    if not diversions and fallback_candidates:
        diversions = _python_fallback_search(
            fallback_candidates,
            dep_lat,
            dep_lon,
            dest_lat,
            dest_lon,
            departure_id,
            destination_id,
            min_runway_ft,
        )
        if diversions:
            logger.info("Diversion python fallback found %d airports", len(diversions))

    if not diversions and fallback_candidates:
        diversions = _nearest_runway_fallback(
            fallback_candidates,
            dep_lat,
            dep_lon,
            dest_lat,
            dest_lon,
            departure_id,
            destination_id,
            min_runway_ft,
        )
        if diversions:
            logger.info("Diversion nearest-runway fallback found %d airports", len(diversions))

    return diversions
