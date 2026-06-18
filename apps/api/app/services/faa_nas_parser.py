from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class AirportStatus:
    icao: str
    status: str
    delay_minutes: int
    is_closed: bool
    ground_stop: bool
    parse_success: bool
    fetched_at: str
    warnings: list[str]
    raw_payload: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "icao": self.icao,
            "status": self.status,
            "delay_minutes": self.delay_minutes,
            "is_closed": self.is_closed,
            "ground_stop": self.ground_stop,
            "parse_success": self.parse_success,
            "fetched_at": self.fetched_at,
            "warnings": self.warnings,
            "raw": self.raw_payload,
        }


def _extract_delay_minutes(data: dict[str, Any]) -> int:
    for key in ("delay", "arrivalDelay", "departureDelay"):
        val = data.get(key)
        if isinstance(val, dict):
            for sub in ("arrivalDelayMinutes", "departureDelayMinutes", "averageDelay"):
                if sub in val and val[sub] is not None:
                    try:
                        return int(val[sub])
                    except (TypeError, ValueError):
                        continue
        elif isinstance(val, (int, float)):
            return int(val)
    return 0


def parse_faa_airport_status(icao: str, payload: Any) -> AirportStatus:
    """Parse FAA NAS status payload; never guess on failure."""
    fetched_at = datetime.now(timezone.utc).isoformat()
    icao = (icao or "").upper()
    warnings: list[str] = []

    if not isinstance(payload, dict):
        return AirportStatus(
            icao=icao,
            status="unknown",
            delay_minutes=0,
            is_closed=False,
            ground_stop=False,
            parse_success=False,
            fetched_at=fetched_at,
            warnings=[f"{icao}: FAA status could not be parsed — data unavailable"],
            raw_payload=None,
        )

    try:
        is_closed = bool(payload.get("closure") or payload.get("isClosed"))
        ground_stop = bool(payload.get("groundStop") or payload.get("ground_stop"))
        delay_minutes = _extract_delay_minutes(payload)

        if is_closed:
            status = "closed"
            warnings.append(f"{icao}: Airport reported closed")
        elif ground_stop:
            status = "ground_stop"
            warnings.append(f"{icao}: Ground stop in effect")
        elif delay_minutes > 0:
            status = "delayed"
            warnings.append(f"{icao}: Average delay {delay_minutes} minutes")
        else:
            status = "normal"

        return AirportStatus(
            icao=icao,
            status=status,
            delay_minutes=delay_minutes,
            is_closed=is_closed,
            ground_stop=ground_stop,
            parse_success=True,
            fetched_at=fetched_at,
            warnings=warnings,
            raw_payload=payload,
        )
    except Exception:
        return AirportStatus(
            icao=icao,
            status="unknown",
            delay_minutes=0,
            is_closed=False,
            ground_stop=False,
            parse_success=False,
            fetched_at=fetched_at,
            warnings=[f"{icao}: FAA status parse error — showing unknown"],
            raw_payload=payload if isinstance(payload, dict) else None,
        )
