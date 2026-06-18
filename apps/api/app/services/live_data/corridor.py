from __future__ import annotations

import math
from typing import Any

from app.geo.utils import cross_track_distance_nm, haversine_nm, is_in_route_corridor

CORRIDOR_HALF_WIDTH_NM = 50.0
NEARBY_TFR_NM = 75.0


def route_corridor_waypoints(
    primary_path: list[dict[str, float]] | list[tuple[float, float]],
) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for item in primary_path or []:
        if isinstance(item, dict):
            points.append((float(item["lat"]), float(item["lon"])))
        else:
            points.append((float(item[0]), float(item[1])))
    return points


def point_near_corridor(
    lat: float,
    lon: float,
    waypoints: list[tuple[float, float]],
    max_cross_track_nm: float = CORRIDOR_HALF_WIDTH_NM,
) -> tuple[bool, float]:
    """Return (on_corridor, min_cross_track_nm)."""
    if len(waypoints) < 2:
        return False, float("inf")
    dep_lat, dep_lon = waypoints[0]
    dest_lat, dest_lon = waypoints[-1]
    if is_in_route_corridor(dep_lat, dep_lon, dest_lat, dest_lon, lat, lon, max_cross_track_nm):
        ct = cross_track_distance_nm(dep_lat, dep_lon, dest_lat, dest_lon, lat, lon)
        return True, ct
    min_ct = float("inf")
    for i in range(len(waypoints) - 1):
        lat1, lon1 = waypoints[i]
        lat2, lon2 = waypoints[i + 1]
        min_ct = min(min_ct, cross_track_distance_nm(lat1, lon1, lat2, lon2, lat, lon))
    return min_ct <= max_cross_track_nm, min_ct


def tfr_impact_for_point(
    tfr_lat: float,
    tfr_lon: float,
    radius_nm: float | None,
    waypoints: list[tuple[float, float]],
) -> tuple[str, float]:
    """Classify TFR as intersects, nearby, or none; return impact and distance."""
    if not waypoints:
        return "unmapped", 0.0
    dep_lat, dep_lon = waypoints[0]
    dest_lat, dest_lon = waypoints[-1]
    dist_from_route = cross_track_distance_nm(dep_lat, dep_lon, dest_lat, dest_lon, tfr_lat, tfr_lon)
    along_ok = is_in_route_corridor(dep_lat, dep_lon, dest_lat, dest_lon, tfr_lat, tfr_lon, margin_from_ends_nm=10)

    if radius_nm and radius_nm > 0:
        if along_ok and dist_from_route <= radius_nm + CORRIDOR_HALF_WIDTH_NM:
            return "intersects", dist_from_route
        if dist_from_route <= radius_nm + NEARBY_TFR_NM:
            return "nearby", dist_from_route

    on_corridor, ct = point_near_corridor(tfr_lat, tfr_lon, waypoints)
    if on_corridor:
        return "intersects", ct
    if ct <= NEARBY_TFR_NM:
        return "nearby", ct
    return "none", ct


def pirep_near_corridor(
    lat: float,
    lon: float,
    waypoints: list[tuple[float, float]],
    max_nm: float = 40.0,
) -> tuple[bool, float]:
    if not waypoints:
        return False, float("inf")
    dep_lat, dep_lon = waypoints[0]
    dest_lat, dest_lon = waypoints[-1]
    if is_in_route_corridor(dep_lat, dep_lon, dest_lat, dest_lon, lat, lon, max_nm):
        d = haversine_nm(dep_lat, dep_lon, lat, lon)
        return True, d
    on_corridor, ct = point_near_corridor(lat, lon, waypoints, max_nm)
    return on_corridor, ct
