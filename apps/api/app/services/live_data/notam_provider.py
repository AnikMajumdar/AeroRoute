from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Protocol

import httpx

from app.config import settings
from app.services.cache import cache_service
from app.services.live_data.types import DataSourceMeta, NotamRecord, ProviderResult

logger = logging.getLogger(__name__)

NOTAM_CATEGORIES = (
    "runway",
    "taxiway",
    "navaid",
    "airport_closure",
    "lighting",
    "procedure",
    "airspace_security",
    "other",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def categorize_notam_text(text: str) -> tuple[str, str]:
    """Return (category, severity)."""
    upper = text.upper()
    if any(k in upper for k in ("AD CLSD", "AIRPORT CLOSED", "AP CLSD", "AIRPORT CLSD")):
        return "airport_closure", "high"
    if any(k in upper for k in ("RWY", "RUNWAY")) and any(k in upper for k in ("CLSD", "CLOSED", "U/S")):
        return "runway", "high"
    if "TWY" in upper or "TAXIWAY" in upper:
        return "taxiway", "medium"
    if any(k in upper for k in ("NAVAID", "VOR", "ILS", "LOC", "DME", "NDB", "GPS")):
        return "navaid", "medium"
    if any(k in upper for k in ("LGT", "LIGHT", "PAPI", "REIL")):
        return "lighting", "medium"
    if any(k in upper for k in ("SID", "STAR", "APPROACH", "DEPARTURE", "PROCEDURE")):
        return "procedure", "medium"
    if any(k in upper for k in ("TFR", "RESTRICTED", "PROHIBITED", "SECURITY")):
        return "airspace_security", "medium"
    return "other", "advisory"


class NotamProvider(Protocol):
    async def get_airport_notams(self, icao: str) -> ProviderResult: ...
    async def get_route_notams(self, route_geometry: Any) -> ProviderResult: ...


class DisabledNotamProvider:
    """NOTAM integration not connected — verify through official sources."""

    mode = "disabled"

    async def get_airport_notams(self, icao: str) -> ProviderResult:
        return ProviderResult(
            data=[],
            meta=DataSourceMeta(
                source_name="NOTAM (disabled)",
                source_url=None,
                fetched_at=_now_iso(),
                available=False,
                error=(
                    "NOTAM integration not connected. Verify NOTAMs through official sources "
                    "(1800WXBRIEF, FAA NOTAM Search, ForeFlight/Garmin)."
                ),
            ),
        )

    async def get_route_notams(self, route_geometry: Any) -> ProviderResult:
        return await self.get_airport_notams("")


class OfficialApiNotamProvider:
    """FAA NMS API NOTAM provider when credentials are configured."""

    mode = "official_api"

    def __init__(self) -> None:
        self.base_url = (settings.faa_nms_api_base_url or "").rstrip("/")
        self.api_key = settings.faa_nms_api_key or ""
        self.timeout = httpx.Timeout(15.0, connect=5.0)

    async def _fetch(self, icao: str) -> ProviderResult:
        fetched_at = _now_iso()
        if not self.base_url or not self.api_key:
            return ProviderResult(
                data=[],
                meta=DataSourceMeta(
                    source_name="FAA NMS NOTAM",
                    source_url=self.base_url or None,
                    fetched_at=fetched_at,
                    available=False,
                    error="FAA NMS API credentials not configured",
                ),
            )

        cache_key = f"notam:{icao}"
        cached = cache_service.get(cache_key)
        if cached is not None:
            return ProviderResult(
                data=cached,
                meta=DataSourceMeta(
                    source_name="FAA NMS NOTAM",
                    source_url=self.base_url,
                    fetched_at=fetched_at,
                    available=True,
                ),
            )

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/notams",
                    params={"icao": icao.upper()},
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            logger.warning("NOTAM fetch failed for %s: %s", icao, exc)
            return ProviderResult(
                data=[],
                meta=DataSourceMeta(
                    source_name="FAA NMS NOTAM",
                    source_url=self.base_url,
                    fetched_at=fetched_at,
                    available=False,
                    error="NOTAM provider request failed",
                ),
            )

        records: list[dict[str, Any]] = []
        items = payload if isinstance(payload, list) else payload.get("notams") or []
        for item in items:
            if not isinstance(item, dict):
                continue
            raw = str(item.get("text") or item.get("raw_text") or item.get("notamText") or "")
            category, severity = categorize_notam_text(raw)
            notam_id = str(item.get("id") or item.get("notam_id") or item.get("number") or "")
            rec = NotamRecord(
                notam_id=notam_id or f"{icao}-unknown",
                airport_icao=icao.upper(),
                raw_text=raw,
                category=category,
                effective_start=item.get("effectiveStart") or item.get("start"),
                effective_end=item.get("effectiveEnd") or item.get("end"),
                severity=severity,  # type: ignore[arg-type]
            )
            records.append(rec.to_dict())

        cache_service.set(cache_key, records, settings.cache_notam_ttl)
        return ProviderResult(
            data=records,
            meta=DataSourceMeta(
                source_name="FAA NMS NOTAM",
                source_url=self.base_url,
                fetched_at=fetched_at,
                available=True,
            ),
        )

    async def get_airport_notams(self, icao: str) -> ProviderResult:
        return await self._fetch(icao)

    async def get_route_notams(self, route_geometry: Any) -> ProviderResult:
        # Route NOTAMs require corridor query — aggregate dep/dest for now
        icaos = []
        if isinstance(route_geometry, dict):
            if route_geometry.get("departure_icao"):
                icaos.append(route_geometry["departure_icao"])
            if route_geometry.get("destination_icao"):
                icaos.append(route_geometry["destination_icao"])
        all_notams: list[dict[str, Any]] = []
        meta: DataSourceMeta | None = None
        for icao in icaos:
            result = await self._fetch(icao)
            meta = result.meta
            all_notams.extend(result.data or [])
        return ProviderResult(data=all_notams, meta=meta or DataSourceMeta(source_name="FAA NMS NOTAM", fetched_at=_now_iso()))


def build_notam_provider() -> NotamProvider:
    mode = (settings.notam_provider_mode or "disabled").lower()
    if mode == "official_api":
        return OfficialApiNotamProvider()
    return DisabledNotamProvider()


notam_provider = build_notam_provider()
