from __future__ import annotations

import logging
from typing import Any

from app.geo.utils import cross_and_along_track_nm, haversine_nm
from app.services.wind_altitude import NM_TO_M

logger = logging.getLogger(__name__)

# At most this many diversion airports are returned (stored and shown).
MAX_DIVERSION_AIRPORTS = 10
# Airports farther than this from the route are not diversion options.
DIVERSION_CORRIDOR_NM = 150.0
# Candidates fetched from PostGIS before the choice that spreads the airports over the route.
DIVERSION_CANDIDATE_LIMIT = 200

DIVERSION_AIRPORT_TYPES = ("small_airport", "medium_airport", "large_airport")


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


def along_route_nm(departure: dict[str, Any], destination: dict[str, Any], airport: dict[str, Any]) -> float | None:
    """Where an airport is abeam of the route departure -> destination, in NM from the departure."""
    try:
        _, along = cross_and_along_track_nm(
            departure["latitude"],
            departure["longitude"],
            destination["latitude"],
            destination["longitude"],
            airport["latitude"],
            airport["longitude"],
        )
    except (KeyError, TypeError):
        return None
    return round(along, 1)


def add_route_position(
    diversions: list[dict[str, Any]], dep_lat: float, dep_lon: float, dest_lat: float, dest_lon: float
) -> list[dict[str, Any]]:
    """Add ``distance_along_route_nm`` (where the airport is abeam of the route, from the departure) to each one."""
    for diversion in diversions:
        airport = diversion["airport"]
        _, along = cross_and_along_track_nm(
            dep_lat, dep_lon, dest_lat, dest_lon, airport["latitude"], airport["longitude"]
        )
        diversion["distance_along_route_nm"] = round(along, 1)
    return diversions


def select_spread_diversions(
    diversions: list[dict[str, Any]], route_nm: float, limit: int = MAX_DIVERSION_AIRPORTS
) -> list[dict[str, Any]]:
    """Up to ``limit`` diversions, closest to the route first, spread over the whole route.

    The closest N airports can all sit around one city and leave the rest of the route without an alternate. The
    route is therefore cut into ``limit`` equal stretches and the airport closest to the track in each stretch is
    taken first; places that are left go to the closest of the other airports. Every diversion needs
    ``distance_along_route_nm`` (see ``add_route_position``).
    """
    ranked = sorted(diversions, key=lambda d: d["distance_from_route_nm"])
    if len(ranked) <= limit or route_nm <= 0:
        return ranked[:limit]
    stretch_nm = route_nm / limit
    chosen: dict[int, dict[str, Any]] = {}
    for diversion in ranked:  # closest first: the first airport seen in a stretch is the closest one in it
        stretch = min(limit - 1, max(0, int(diversion["distance_along_route_nm"] // stretch_nm)))
        chosen.setdefault(stretch, diversion)
    selected = list(chosen.values())
    if len(selected) < limit:
        taken = {id(diversion) for diversion in selected}
        selected.extend([d for d in ranked if id(d) not in taken][: limit - len(selected)])
    return sorted(selected, key=lambda d: d["distance_from_route_nm"])


def _postgis_search(
    supabase: Any,
    dep_lon: float,
    dep_lat: float,
    dest_lon: float,
    dest_lat: float,
    departure_id: str,
    destination_id: str,
    min_runway_ft: int,
) -> list[dict[str, Any]]:
    result = supabase.rpc(
        "find_diversion_airports_in_corridor",
        {
            "dep_lon": dep_lon,
            "dep_lat": dep_lat,
            "dest_lon": dest_lon,
            "dest_lat": dest_lat,
            "min_dist_m": 0,
            "max_dist_m": DIVERSION_CORRIDOR_NM * NM_TO_M,
            "min_runway_ft": min_runway_ft,
            "exclude_dep_id": departure_id,
            "exclude_dest_id": destination_id,
            "result_limit": DIVERSION_CANDIDATE_LIMIT,
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
    max_cross_track_nm: float = DIVERSION_CORRIDOR_NM,
) -> list[dict[str, Any]]:
    """Suitable airports abeam of the route within the corridor, from a list of airports.

    The Python counterpart of the PostGIS function, used when that query fails or finds nothing.
    """
    route_nm = haversine_nm(dep_lat, dep_lon, dest_lat, dest_lon)
    found: list[dict[str, Any]] = []

    for airport in candidates:
        if airport["id"] in (departure_id, destination_id):
            continue
        if (airport.get("longest_runway_ft") or 0) < min_runway_ft:
            continue
        if airport.get("airport_type", "") not in DIVERSION_AIRPORT_TYPES:
            continue
        cross, along = cross_and_along_track_nm(
            dep_lat, dep_lon, dest_lat, dest_lon, airport["latitude"], airport["longitude"]
        )
        if cross > max_cross_track_nm or not 0 < along < route_nm:
            continue
        found.append(
            {
                "airport": airport,
                "distance_from_route_nm": round(cross, 2),
                "distance_along_route_nm": round(along, 1),
            }
        )

    return select_spread_diversions(found, route_nm)


def find_diversion_airports_postgis(
    supabase: Any | None,
    dep_lon: float,
    dep_lat: float,
    dest_lon: float,
    dest_lat: float,
    departure_id: str,
    destination_id: str,
    min_runway_ft: int = 3000,
    fallback_candidates: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Diversion airports along the route: suitable airports abeam of it, closest first, spread over its length.

    Airports within ``DIVERSION_CORRIDOR_NM`` of the route are fetched from PostGIS (``fallback_candidates`` are
    searched in Python when that fails or finds none). There is no minimum distance from the route and airports
    behind the departure or beyond the destination are not options; if nothing qualifies the list is empty.
    """
    route_nm = haversine_nm(dep_lat, dep_lon, dest_lat, dest_lon)
    diversions: list[dict[str, Any]] = []

    if supabase is not None:
        try:
            diversions = _postgis_search(
                supabase, dep_lon, dep_lat, dest_lon, dest_lat, departure_id, destination_id, min_runway_ft
            )
        except Exception as exc:
            logger.warning("PostGIS diversion query failed: %s", exc)

    if diversions:
        add_route_position(diversions, dep_lat, dep_lon, dest_lat, dest_lon)
        # The PostGIS function only returns airports abeam of the route; checking again keeps the result right while
        # a database still runs the previous version of the function (before migration 011).
        diversions = [d for d in diversions if 0 < d["distance_along_route_nm"] < route_nm]
        if diversions:
            selected = select_spread_diversions(diversions, route_nm)
            logger.info("Diversion search found %d airports (%d candidates)", len(selected), len(diversions))
            return selected

    if fallback_candidates:
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

    return diversions
