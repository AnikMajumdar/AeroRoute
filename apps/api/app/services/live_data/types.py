from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

HazardSeverity = Literal["advisory", "medium", "high", "unknown"]
TfrImpact = Literal["intersects", "nearby", "unmapped", "none"]


@dataclass
class DataSourceMeta:
    source_name: str
    source_url: str | None = None
    fetched_at: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    error: str | None = None
    available: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "source_url": self.source_url,
            "fetched_at": self.fetched_at,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "error": self.error,
            "available": self.available,
        }


@dataclass
class ProviderResult:
    data: Any
    meta: DataSourceMeta

    def to_dict(self) -> dict[str, Any]:
        return {"data": self.data, "meta": self.meta.to_dict()}


@dataclass
class TfrRecord:
    notam_number: str
    title: str
    summary: str
    effective_start: str | None
    effective_end: str | None
    facility: str | None = None
    raw_text: str | None = None
    geometry: dict[str, Any] | None = None
    centroid_lat: float | None = None
    centroid_lon: float | None = None
    radius_nm: float | None = None
    impact: TfrImpact = "none"
    distance_nm: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "notam_number": self.notam_number,
            "title": self.title,
            "summary": self.summary,
            "effective_start": self.effective_start,
            "effective_end": self.effective_end,
            "facility": self.facility,
            "raw_text": self.raw_text,
            "geometry": self.geometry,
            "centroid_lat": self.centroid_lat,
            "centroid_lon": self.centroid_lon,
            "radius_nm": self.radius_nm,
            "impact": self.impact,
            "distance_nm": self.distance_nm,
        }


@dataclass
class NotamRecord:
    notam_id: str
    airport_icao: str
    raw_text: str
    category: str = "unknown"
    effective_start: str | None = None
    effective_end: str | None = None
    severity: HazardSeverity = "advisory"

    def to_dict(self) -> dict[str, Any]:
        return {
            "notam_id": self.notam_id,
            "airport_icao": self.airport_icao,
            "raw_text": self.raw_text,
            "category": self.category,
            "effective_start": self.effective_start,
            "effective_end": self.effective_end,
            "severity": self.severity,
        }


@dataclass
class WeatherHazard:
    hazard_type: str
    severity: HazardSeverity
    summary: str
    raw_text: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    geometry: dict[str, Any] | None = None
    intersects_route: bool = False
    distance_nm: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "hazard_type": self.hazard_type,
            "severity": self.severity,
            "summary": self.summary,
            "raw_text": self.raw_text,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "geometry": self.geometry,
            "intersects_route": self.intersects_route,
            "distance_nm": self.distance_nm,
        }


@dataclass
class LiveDataSnapshot:
    route_id: str | None
    fetched_at: str
    departure_icao: str | None = None
    destination_icao: str | None = None
    weather: dict[str, Any] = field(default_factory=dict)
    restrictions: dict[str, Any] = field(default_factory=dict)
    faa_status: dict[str, Any] = field(default_factory=dict)
    confidence: dict[str, Any] = field(default_factory=dict)
    sources: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_id": self.route_id,
            "fetched_at": self.fetched_at,
            "departure_icao": self.departure_icao,
            "destination_icao": self.destination_icao,
            "weather": self.weather,
            "restrictions": self.restrictions,
            "faa_status": self.faa_status,
            "confidence": self.confidence,
            "sources": self.sources,
            "warnings": self.warnings,
            "disclaimer": (
                "Educational live data snapshot only. Verify all restrictions, weather, "
                "and NOTAMs through official FAA briefings before any flight."
            ),
        }
