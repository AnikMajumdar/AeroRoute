"""Approximate civil (wall-clock) time for continental-US coordinates.

Airports carry no stored time zone and the planner only covers the contiguous US, so the zone is chosen from the
coordinates with the simplified boundaries below. The result is exact away from a zone boundary; within a few tens
of miles of one (e.g. the Indiana, Kentucky or Dakota lines) it can be one hour off, which is irrelevant for the
time-of-day features it feeds. Daylight-saving rules come from the system tz database (``zoneinfo``); when that is
missing, the standard-time offset implied by the longitude is used.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_EASTERN = "America/New_York"
_CENTRAL = "America/Chicago"
_MOUNTAIN = "America/Denver"
_PACIFIC = "America/Los_Angeles"
_ARIZONA = "America/Phoenix"  # no daylight saving time


def _is_mountain(lat: float, lon: float) -> bool:
    """Mountain/Central boundary (lon is west of it when negative enough)."""
    if lat >= 41.5:  # Nebraska panhandle, Dakotas
        return lon < -101.0
    if lat >= 36.5:  # Colorado, western Kansas
        return lon < -101.6
    if lat >= 32.0:  # New Mexico east edge
        return lon < -103.04
    return lon < -104.9  # far west Texas (El Paso)


def _eastern_edge(lat: float) -> float:
    """Longitude east of which the Eastern zone starts (Central/Eastern boundary)."""
    if lat >= 46.0:  # Michigan upper peninsula
        return -88.0
    if lat >= 42.0:  # Wisconsin / Michigan
        return -87.4
    if lat >= 37.0:  # Illinois / Indiana / Kentucky
        return -86.6
    return -85.4  # Tennessee, Alabama, Georgia, Florida panhandle


def conus_timezone_name(lat: float, lon: float) -> str | None:
    """IANA zone for a point in the contiguous US, or None outside it."""
    if not (24.0 <= lat <= 50.0 and -125.0 <= lon <= -66.0):
        return None
    if 31.3 <= lat <= 37.0 and -114.85 <= lon <= -109.05:
        return _ARIZONA
    southern_idaho_or_east_oregon = 42.0 <= lat <= 45.4 and lon > -117.1
    if lon < -114.5 and not southern_idaho_or_east_oregon:
        return _PACIFIC
    if _is_mountain(lat, lon):
        return _MOUNTAIN
    return _EASTERN if lon > _eastern_edge(lat) else _CENTRAL


def to_local_time(moment: datetime, lat: float | None, lon: float | None) -> datetime:
    """``moment`` expressed in the local civil time at the given point (UTC when the point is unknown)."""
    moment = moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment.astimezone(timezone.utc)
    if lat is None or lon is None:
        return moment
    name = conus_timezone_name(lat, lon)
    if name:
        try:
            return moment.astimezone(ZoneInfo(name))
        except ZoneInfoNotFoundError:
            pass  # no tz database installed: fall back to the longitude-based offset below
    return moment.astimezone(timezone(timedelta(hours=round(lon / 15.0))))
