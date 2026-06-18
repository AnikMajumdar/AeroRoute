from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from app.services.faa_nas import INTEGRATION_DISABLED_MESSAGE
from app.services.live_data.corridor import route_corridor_waypoints, tfr_impact_for_point
from app.services.live_data.types import DataSourceMeta, ProviderResult, TfrRecord

SOURCE_NAME = "FAA TFR (disabled)"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_tfr_list_item(item: dict[str, Any]) -> TfrRecord | None:
    """Parse TFR list item shape (used by tests; no live fetch)."""
    notam = str(item.get("notamNumber") or item.get("notam_number") or item.get("id") or "").strip()
    if not notam:
        return None
    title = str(item.get("title") or item.get("type") or "TFR").strip()
    summary = str(item.get("description") or item.get("text") or title).strip()
    return TfrRecord(
        notam_number=notam,
        title=title,
        summary=summary[:500],
        effective_start=item.get("effectiveStart") or item.get("startDate"),
        effective_end=item.get("effectiveEnd") or item.get("endDate"),
        facility=item.get("facility") or item.get("center"),
        raw_text=summary,
        centroid_lat=_safe_float(item.get("lat") or item.get("latitude")),
        centroid_lon=_safe_float(item.get("lon") or item.get("longitude")),
        radius_nm=_safe_float(item.get("radius") or item.get("radiusNm")),
    )


def _safe_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _parse_radius_nm(text: str) -> float | None:
    if not text:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:NM|NAUTICAL)", text.upper())
    if m:
        return float(m.group(1))
    m = re.search(r"WITHIN\s+(\d+(?:\.\d+)?)\s*NM", text.upper())
    if m:
        return float(m.group(1))
    return None


class TfrProvider:
    """Stub — no FAA TFR API calls."""

    async def fetch_active_tfrs(self) -> ProviderResult:
        return ProviderResult(
            data=[],
            meta=DataSourceMeta(
                source_name=SOURCE_NAME,
                source_url=None,
                fetched_at=_now_iso(),
                available=False,
                error=INTEGRATION_DISABLED_MESSAGE,
            ),
        )

    async def get_tfrs_for_route(
        self,
        route_path: list[dict[str, float]] | list[tuple[float, float]],
    ) -> ProviderResult:
        return await self.fetch_active_tfrs()


tfr_provider = TfrProvider()
