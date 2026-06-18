from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from app.services.live_data.aviation_weather_provider import aviation_weather_provider
from app.services.live_data.faa_status_provider import faa_status_provider
from app.services.live_data.notam_provider import notam_provider
from app.services.live_data.tfr_provider import tfr_provider
from app.services.live_data.types import LiveDataSnapshot

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _confidence_level(sources: dict[str, Any], warnings: list[str]) -> str:
    available = sum(1 for s in sources.values() if s.get("available"))
    total = max(len(sources), 1)
    if available == total and not warnings:
        return "high"
    if available >= total // 2:
        return "medium"
    return "low"


class LiveDataOrchestrator:
    """Fetch and unify live aviation data for a route."""

    async def build_snapshot(
        self,
        *,
        route_id: str | None,
        departure_icao: str | None,
        destination_icao: str | None,
        route_path: list[dict[str, float]] | list[tuple[float, float]],
        checkpoint_icaos: list[str] | None = None,
        supabase: Any | None = None,
    ) -> tuple[LiveDataSnapshot, dict[str, float]]:
        """Return snapshot and per-provider timing in seconds."""
        t0 = time.perf_counter()
        timings: dict[str, float] = {}
        warnings: list[str] = []
        sources: dict[str, Any] = {}

        checkpoint_icaos = checkpoint_icaos or []
        icaos = [c for c in [departure_icao, destination_icao, *checkpoint_icaos] if c]

        async def _timed(name: str, coro):
            start = time.perf_counter()
            result = await coro
            timings[name] = round(time.perf_counter() - start, 3)
            return result

        tasks = {
            "dep_faa": _timed("dep_faa", faa_status_provider.get_airport_status(departure_icao or "", supabase)),
            "dest_faa": _timed("dest_faa", faa_status_provider.get_airport_status(destination_icao or "", supabase)),
            "tfrs": _timed("tfrs", tfr_provider.get_tfrs_for_route(route_path)),
            "hazards": _timed("hazards", aviation_weather_provider.get_route_hazards(route_path)),
            "notams": _timed(
                "notams",
                notam_provider.get_route_notams(
                    {"departure_icao": departure_icao, "destination_icao": destination_icao}
                ),
            ),
        }
        for icao in set(icaos):
            tasks[f"metar_{icao}"] = _timed(f"metar_{icao}", aviation_weather_provider.get_metar(icao))
            tasks[f"taf_{icao}"] = _timed(f"taf_{icao}", aviation_weather_provider.get_taf(icao))

        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        keyed = dict(zip(tasks.keys(), results))

        metars: dict[str, Any] = {}
        tafs: dict[str, Any] = {}
        for key, result in keyed.items():
            if isinstance(result, Exception):
                warnings.append(f"{key}: {result}")
                continue
            if key.startswith("metar_"):
                icao = key.split("_", 1)[1]
                metars[icao] = result.data
                sources[f"metar_{icao}"] = result.meta.to_dict()
            elif key.startswith("taf_"):
                icao = key.split("_", 1)[1]
                tafs[icao] = result.data
                sources[f"taf_{icao}"] = result.meta.to_dict()
            elif key == "dep_faa":
                dep_faa = result
                sources["faa_departure"] = result.meta.to_dict()
            elif key == "dest_faa":
                dest_faa = result
                sources["faa_destination"] = result.meta.to_dict()
            elif key == "tfrs":
                tfr_result = result
                sources["tfr"] = result.meta.to_dict()
            elif key == "hazards":
                hazard_result = result
                sources["weather_hazards"] = result.meta.to_dict()
            elif key == "notams":
                notam_result = result
                sources["notam"] = result.meta.to_dict()

        dep_faa = keyed.get("dep_faa")
        dest_faa = keyed.get("dest_faa")
        tfr_result = keyed.get("tfrs")
        hazard_result = keyed.get("hazards")
        notam_result = keyed.get("notams")

        if isinstance(dep_faa, Exception):
            dep_faa_data = {"status": "unknown"}
        else:
            dep_faa_data = dep_faa.data if dep_faa else {"status": "unknown"}

        if isinstance(dest_faa, Exception):
            dest_faa_data = {"status": "unknown"}
        else:
            dest_faa_data = dest_faa.data if dest_faa else {"status": "unknown"}

        tfrs = []
        if tfr_result and not isinstance(tfr_result, Exception):
            tfrs = tfr_result.data or []
            if tfr_result.meta.error:
                warnings.append(tfr_result.meta.error)

        hazards = []
        if hazard_result and not isinstance(hazard_result, Exception):
            hazards = hazard_result.data or []
            if hazard_result.meta.error:
                warnings.append(hazard_result.meta.error)

        notams = []
        notam_connected = False
        if notam_result and not isinstance(notam_result, Exception):
            notams = notam_result.data or []
            notam_connected = notam_result.meta.available and not notam_result.meta.error
            if notam_result.meta.error and "not connected" in (notam_result.meta.error or "").lower():
                warnings.append(notam_result.meta.error)

        dep_notams = [n for n in notams if n.get("airport_icao") == (departure_icao or "").upper()]
        dest_notams = [n for n in notams if n.get("airport_icao") == (destination_icao or "").upper()]

        missing: list[str] = []
        if not departure_icao:
            missing.append("departure_icao")
        if not destination_icao:
            missing.append("destination_icao")
        if not metars.get(departure_icao or ""):
            missing.append("departure_metar")
        if not metars.get(destination_icao or ""):
            missing.append("destination_metar")

        confidence = {
            "level": _confidence_level(sources, warnings),
            "missing_fields": missing,
            "stale_warnings": [],
            "notam_connected": notam_connected,
            "data_basis": [
                s for s in ("FAA NAS", "METAR/TAF", "TFR", "weather hazards", "NOTAM")
                if (
                    (s == "FAA NAS" and sources.get("faa_departure", {}).get("available"))
                    or (s == "METAR/TAF" and any(k.startswith("metar_") for k in sources))
                    or (s == "TFR" and sources.get("tfr", {}).get("available"))
                    or (s == "weather hazards" and sources.get("weather_hazards", {}).get("available"))
                    or (s == "NOTAM" and notam_connected)
                )
            ],
        }

        snapshot = LiveDataSnapshot(
            route_id=route_id,
            fetched_at=_now_iso(),
            departure_icao=departure_icao,
            destination_icao=destination_icao,
            weather={
                "metars": metars,
                "tafs": tafs,
                "hazards": hazards,
                "pirep_count": sum(1 for h in hazards if h.get("hazard_type") == "pirep"),
                "sigmet_count": sum(1 for h in hazards if "sigmet" in str(h.get("hazard_type", "")).lower()),
            },
            restrictions={
                "tfrs": tfrs,
                "notams": notams,
                "notam_connected": notam_connected,
                "departure_notams": dep_notams,
                "destination_notams": dest_notams,
            },
            faa_status={
                "departure": dep_faa_data,
                "destination": dest_faa_data,
            },
            confidence=confidence,
            sources=sources,
            warnings=warnings,
        )

        timings["total"] = round(time.perf_counter() - t0, 3)
        return snapshot, timings

    async def persist_snapshot(
        self,
        supabase: Any,
        route_result_id: str,
        user_id: str,
        snapshot: LiveDataSnapshot,
    ) -> None:
        try:
            supabase.table("live_data_snapshots").insert(
                {
                    "route_result_id": route_result_id,
                    "user_id": user_id,
                    "snapshot": snapshot.to_dict(),
                    "source_health": snapshot.confidence,
                    "fetched_at": snapshot.fetched_at,
                }
            ).execute()
        except Exception as exc:
            logger.debug("Could not persist live_data_snapshot: %s", exc)

        for tfr in snapshot.restrictions.get("tfrs") or []:
            try:
                supabase.table("tfr_snapshots").insert(
                    {
                        "notam_number": tfr.get("notam_number"),
                        "title": tfr.get("title"),
                        "raw_payload": tfr,
                        "effective_start": tfr.get("effective_start"),
                        "effective_end": tfr.get("effective_end"),
                        "fetched_at": snapshot.fetched_at,
                    }
                ).execute()
            except Exception:
                pass

        for hazard in snapshot.weather.get("hazards") or []:
            try:
                supabase.table("aviation_weather_hazards").insert(
                    {
                        "hazard_type": hazard.get("hazard_type"),
                        "severity": hazard.get("severity"),
                        "summary": hazard.get("summary"),
                        "raw_text": hazard.get("raw_text"),
                        "valid_from": hazard.get("valid_from"),
                        "valid_to": hazard.get("valid_to"),
                        "latitude": hazard.get("latitude"),
                        "longitude": hazard.get("longitude"),
                        "geometry": hazard.get("geometry"),
                        "fetched_at": snapshot.fetched_at,
                    }
                ).execute()
            except Exception:
                pass


live_data_orchestrator = LiveDataOrchestrator()
