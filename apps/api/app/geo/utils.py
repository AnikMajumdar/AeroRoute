"""Geospatial utilities for route calculation."""

import math
from typing import Iterable

EARTH_RADIUS_NM = 3440.065


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in nautical miles."""
    lat1_r, lon1_r = math.radians(lat1), math.radians(lon1)
    lat2_r, lon2_r = math.radians(lat2), math.radians(lon2)
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_NM * math.asin(math.sqrt(a))


def initial_bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from point 1 to point 2 in degrees (0-360)."""
    lat1_r, lon1_r = math.radians(lat1), math.radians(lon1)
    lat2_r, lon2_r = math.radians(lat2), math.radians(lon2)
    dlon = lon2_r - lon1_r
    x = math.sin(dlon) * math.cos(lat2_r)
    y = math.cos(lat1_r) * math.sin(lat2_r) - math.sin(lat1_r) * math.cos(lat2_r) * math.cos(dlon)
    bearing = math.degrees(math.atan2(x, y))
    return (bearing + 360) % 360


def destination_point(lat: float, lon: float, bearing_deg: float, distance_nm: float) -> tuple[float, float]:
    """Return (lat, lon) reached from start point along bearing for distance_nm."""
    lat_r = math.radians(lat)
    lon_r = math.radians(lon)
    bearing_r = math.radians(bearing_deg)
    angular_distance = distance_nm / EARTH_RADIUS_NM

    lat2 = math.asin(
        math.sin(lat_r) * math.cos(angular_distance)
        + math.cos(lat_r) * math.sin(angular_distance) * math.cos(bearing_r)
    )
    lon2 = lon_r + math.atan2(
        math.sin(bearing_r) * math.sin(angular_distance) * math.cos(lat_r),
        math.cos(angular_distance) - math.sin(lat_r) * math.sin(lat2),
    )
    return math.degrees(lat2), (math.degrees(lon2) + 540) % 360 - 180


def intermediate_points(
    lat1: float, lon1: float, lat2: float, lon2: float, num_points: int
) -> list[tuple[float, float]]:
    """Linear interpolation of lat/lon points along great-circle path."""
    if num_points <= 0:
        return []
    points: list[tuple[float, float]] = []
    total_dist = haversine_nm(lat1, lon1, lat2, lon2)
    if total_dist == 0:
        return [(lat1, lon1)] * num_points
    bearing = initial_bearing_deg(lat1, lon1, lat2, lon2)
    for i in range(1, num_points + 1):
        fraction = i / (num_points + 1)
        dist = total_dist * fraction
        points.append(destination_point(lat1, lon1, bearing, dist))
    return points


def cross_track_distance_nm(
    route_lat1: float,
    route_lon1: float,
    route_lat2: float,
    route_lon2: float,
    point_lat: float,
    point_lon: float,
) -> float:
    """Perpendicular distance from point to great-circle route segment, in NM."""
    dist_13 = haversine_nm(route_lat1, route_lon1, point_lat, point_lon) / EARTH_RADIUS_NM
    if dist_13 == 0:
        return 0.0
    bearing_13 = math.radians(initial_bearing_deg(route_lat1, route_lon1, point_lat, point_lon))
    bearing_12 = math.radians(initial_bearing_deg(route_lat1, route_lon1, route_lat2, route_lon2))
    cross_track_rad = math.asin(math.sin(dist_13) * math.sin(bearing_13 - bearing_12))
    return abs(cross_track_rad * EARTH_RADIUS_NM)


def along_track_distance_nm(
    route_lat1: float,
    route_lon1: float,
    route_lat2: float,
    route_lon2: float,
    point_lat: float,
    point_lon: float,
) -> float:
    """Along-route distance from start to point when the point lies on the segment."""
    return haversine_nm(route_lat1, route_lon1, point_lat, point_lon)


def _segment_position_ok(
    dep_lat: float,
    dep_lon: float,
    dest_lat: float,
    dest_lon: float,
    point_lat: float,
    point_lon: float,
    margin_from_ends_nm: float = 25.0,
    segment_slack_nm: float = 20.0,
) -> bool:
    total = haversine_nm(dep_lat, dep_lon, dest_lat, dest_lon)
    if total <= margin_from_ends_nm * 2:
        return False

    dist_from_dep = haversine_nm(dep_lat, dep_lon, point_lat, point_lon)
    dist_to_dest = haversine_nm(point_lat, point_lon, dest_lat, dest_lon)

    if dist_from_dep < margin_from_ends_nm or dist_to_dest < margin_from_ends_nm:
        return False
    if dist_from_dep >= total - margin_from_ends_nm:
        return False
    if dist_from_dep + dist_to_dest > total + segment_slack_nm:
        return False
    return True


def is_on_route_between(
    dep_lat: float,
    dep_lon: float,
    dest_lat: float,
    dest_lon: float,
    point_lat: float,
    point_lon: float,
    margin_from_ends_nm: float = 25.0,
    max_cross_track_nm: float = 75.0,
    segment_slack_nm: float = 20.0,
) -> bool:
    """True if point lies on the great-circle segment between dep and dest (not past either end)."""
    if not _segment_position_ok(
        dep_lat, dep_lon, dest_lat, dest_lon, point_lat, point_lon, margin_from_ends_nm, segment_slack_nm
    ):
        return False
    cross_nm = cross_track_distance_nm(dep_lat, dep_lon, dest_lat, dest_lon, point_lat, point_lon)
    return cross_nm <= max_cross_track_nm


def is_in_route_corridor(
    dep_lat: float,
    dep_lon: float,
    dest_lat: float,
    dest_lon: float,
    point_lat: float,
    point_lon: float,
    margin_from_ends_nm: float = 25.0,
    max_cross_track_nm: float = 150.0,
    segment_slack_nm: float = 25.0,
) -> bool:
    """Like is_on_route_between but allows wider cross-track (diversion airports)."""
    if not _segment_position_ok(
        dep_lat, dep_lon, dest_lat, dest_lon, point_lat, point_lon, margin_from_ends_nm, segment_slack_nm
    ):
        return False
    cross_nm = cross_track_distance_nm(dep_lat, dep_lon, dest_lat, dest_lon, point_lat, point_lon)
    return cross_nm <= max_cross_track_nm


def path_from_waypoints(waypoints: Iterable[tuple[float, float]]) -> list[dict[str, float]]:
    return [{"lat": lat, "lon": lon} for lat, lon in waypoints]
