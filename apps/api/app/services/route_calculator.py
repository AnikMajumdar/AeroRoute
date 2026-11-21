from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.geo.utils import (
    destination_point,
    haversine_nm,
    initial_bearing_deg,
    intermediate_points,
)
from app.services.aviation_weather import aviation_weather_client
from app.services.delay_risk import predict_delay_risk
from app.services.diversion_postgis import find_diversion_airports_postgis
from app.services.ml_features import extract_delay_features, extract_ete_features
from app.services.faa_nas import faa_nas_client
from app.services.fuel_model import calculate_fuel_breakdown
from app.services.open_meteo import open_meteo_client, wind_quality_from_segments
from app.services.route_scoring import ScoringInput, calculate_normalized_score
from app.services.weather_checkpoints import (
    best_weather_checkpoint,
    fetch_checkpoint_weather,
    select_checkpoint_airports,
)
from app.services.wind_altitude import groundspeed_kt

logger = logging.getLogger(__name__)

OFFSET_NM = 35.0

# Average speed while climbing / descending as a fraction of cruise speed (light piston and turboprop typical).
CLIMB_SPEED_FACTOR = 0.7
DESCENT_SPEED_FACTOR = 0.9
# Planning floor for the groundspeed (fraction of cruise speed) so extreme winds cannot produce absurd ETEs.
MIN_GROUNDSPEED_FRACTION = 0.25


@dataclass(frozen=True)
class FlightPhases:
    """Climb flown from the start of a route and descent flown up to its end; the rest is cruise."""

    climb_minutes: float
    descent_minutes: float
    climb_nm: float
    descent_nm: float

    def climb_minutes_for(self, nm: float) -> float:
        return self.climb_minutes * nm / self.climb_nm if self.climb_nm > 0 else 0.0

    def descent_minutes_for(self, nm: float) -> float:
        return self.descent_minutes * nm / self.descent_nm if self.descent_nm > 0 else 0.0


def plan_phases(distance_nm: float, aircraft: dict[str, Any]) -> FlightPhases:
    """Time and distance of the climb and descent; both shrink proportionally on routes too short to reach cruise."""
    cruise_speed = float(aircraft["cruise_speed_kt"])
    climb_min = float(aircraft.get("climb_time_min") or 12)
    descent_min = float(aircraft.get("descent_time_min") or 8)
    climb_nm = climb_min / 60.0 * cruise_speed * CLIMB_SPEED_FACTOR
    descent_nm = descent_min / 60.0 * cruise_speed * DESCENT_SPEED_FACTOR
    covered = climb_nm + descent_nm
    scale = min(1.0, distance_nm / covered) if covered > 0 else 1.0
    return FlightPhases(climb_min * scale, descent_min * scale, climb_nm * scale, descent_nm * scale)


def split_leg_distances(
    leg_distances: list[float], climb_nm: float, descent_nm: float
) -> list[tuple[float, float, float]]:
    """(climb, cruise, descent) distance of every leg: the climb is flown first, the descent last."""
    climb = [0.0] * len(leg_distances)
    descent = [0.0] * len(leg_distances)
    remaining = climb_nm
    for i, dist in enumerate(leg_distances):
        if remaining <= 0:
            break
        climb[i] = min(dist, remaining)
        remaining -= climb[i]
    remaining = descent_nm
    for i in reversed(range(len(leg_distances))):
        if remaining <= 0:
            break
        descent[i] = min(leg_distances[i] - climb[i], remaining)
        remaining -= descent[i]
    return [
        (climb[i], max(0.0, leg_distances[i] - climb[i] - descent[i]), descent[i]) for i in range(len(leg_distances))
    ]


@dataclass
class RouteVariant:
    name: str
    waypoints: list[tuple[float, float]]
    distance_nm: float
    ete_minutes: float
    fuel_burn_gal: float
    fuel_cost_usd: float
    segments: list[dict[str, Any]]
    score: float
    score_breakdown: dict[str, Any]
    fuel_breakdown: dict[str, Any] = field(default_factory=dict)
    slow_legs: int = 0  # legs whose groundspeed was raised to the planning floor


def _build_route_variants(
    dep_lat: float,
    dep_lon: float,
    dest_lat: float,
    dest_lon: float,
    diversion_airport: dict[str, Any] | None = None,
    weather_checkpoint: dict[str, Any] | None = None,
) -> list[tuple[str, list[tuple[float, float]]]]:
    direct = [(dep_lat, dep_lon), (dest_lat, dest_lon)]
    bearing = initial_bearing_deg(dep_lat, dep_lon, dest_lat, dest_lon)
    mid_dist = haversine_nm(dep_lat, dep_lon, dest_lat, dest_lon) / 2
    mid_lat, mid_lon = destination_point(dep_lat, dep_lon, bearing, mid_dist)

    # Offsets are defined relative to the direction of travel; labelling them "north"/"south" was wrong
    # on westbound routes (and meaningless on north/south routes).
    left_mid = destination_point(mid_lat, mid_lon, (bearing + 270) % 360, OFFSET_NM)
    right_mid = destination_point(mid_lat, mid_lon, (bearing + 90) % 360, OFFSET_NM)

    variants: list[tuple[str, list[tuple[float, float]]]] = [
        ("direct", direct),
        ("left_offset", [(dep_lat, dep_lon), left_mid, (dest_lat, dest_lon)]),
        ("right_offset", [(dep_lat, dep_lon), right_mid, (dest_lat, dest_lon)]),
    ]

    if diversion_airport:
        dlat, dlon = diversion_airport["latitude"], diversion_airport["longitude"]
        variants.append(
            ("via_diversion", [(dep_lat, dep_lon), (dlat, dlon), (dest_lat, dest_lon)])
        )

    if weather_checkpoint:
        wlat, wlon = weather_checkpoint["latitude"], weather_checkpoint["longitude"]
        variants.append(
            ("via_weather_checkpoint", [(dep_lat, dep_lon), (wlat, wlon), (dest_lat, dest_lon)])
        )

    return variants


def wind_quality_warnings(segments: list[dict[str, Any]]) -> list[str]:
    """Plain-language warnings when a route's winds are missing or degraded.

    Legs without wind data are planned with zero wind, which must never happen silently.
    """
    sources = [segment.get("wind_source") for segment in segments]
    total = len(sources)
    missing = sum(1 for source in sources if not source)
    fallback = sources.count("surface_fallback")
    warnings: list[str] = []
    if total == 0 or missing == total:
        warnings.append(
            "Wind data unavailable — ETE and fuel assume still air (zero wind). "
            "Check winds aloft before relying on these numbers."
        )
        return warnings
    if missing:
        warnings.append(
            f"Wind data unavailable for {missing} of {total} legs — those legs assume zero wind "
            "(educational estimate only)"
        )
    if fallback == total - missing:
        warnings.append(
            "Cruise-altitude winds unavailable — using surface wind fallback (educational estimate only)"
        )
    elif fallback:
        warnings.append(
            f"Cruise-altitude winds unavailable for {fallback} of {total} legs — "
            "using surface wind for those legs (educational estimate only)"
        )
    return warnings


def _cruise_minutes(
    samples: list[dict[str, Any]],
    cruise_from_nm: float,
    cruise_to_nm: float,
    cruise_speed_kt: float,
    min_groundspeed: float,
) -> tuple[float, bool]:
    """Cruise time over the part of a leg between two distances, with the groundspeed of each wind sample."""
    minutes = 0.0
    floored = False
    for sample in samples:
        overlap = min(sample["end_nm"], cruise_to_nm) - max(sample["start_nm"], cruise_from_nm)
        if overlap <= 1e-9:
            continue
        achievable = groundspeed_kt(
            cruise_speed_kt, sample["headwind_component_kt"] or 0.0, sample["crosswind_component_kt"] or 0.0
        )
        floored = floored or achievable < min_groundspeed
        minutes += overlap / max(min_groundspeed, achievable) * 60
    return minutes, floored


async def _compute_variant_metrics(
    name: str,
    waypoints: list[tuple[float, float]],
    aircraft: dict[str, Any],
    fuel_price: float,
    scoring_context: dict[str, Any],
    route_preference: str,
    departure_time: datetime | None = None,
) -> RouteVariant:
    cruise_speed_kt = int(aircraft["cruise_speed_kt"])
    fuel_burn_gph = float(aircraft["fuel_burn_gph"])
    cruise_altitude_ft = int(aircraft.get("cruise_altitude_ft") or 10000)

    leg_distances = [
        haversine_nm(waypoints[i][0], waypoints[i][1], waypoints[i + 1][0], waypoints[i + 1][1])
        for i in range(len(waypoints) - 1)
    ]
    total_distance = sum(leg_distances)
    phases = plan_phases(total_distance, aircraft)
    leg_phases = split_leg_distances(leg_distances, phases.climb_nm, phases.descent_nm)
    cruise_ete = 0.0
    min_groundspeed = MIN_GROUNDSPEED_FRACTION * cruise_speed_kt
    slow_legs = 0
    segments: list[dict[str, Any]] = []

    wind_segments, wind_quality = await open_meteo_client.sample_route_winds(
        waypoints,
        cruise_altitude_ft=cruise_altitude_ft,
        forecast_time=departure_time,
        cruise_speed_kt=cruise_speed_kt,
    )

    for i in range(len(waypoints) - 1):
        lat1, lon1 = waypoints[i]
        lat2, lon2 = waypoints[i + 1]
        leg_dist = leg_distances[i]
        climb_nm, cruise_nm, descent_nm = leg_phases[i]
        bearing = initial_bearing_deg(lat1, lon1, lat2, lon2)

        wind_data = wind_segments[i] if i < len(wind_segments) else {}
        signed_hw = wind_data.get("headwind_component_kt") or 0.0
        crosswind = wind_data.get("crosswind_component_kt") or 0.0
        samples = wind_data.get("samples") or [
            {
                "start_nm": 0.0,
                "end_nm": leg_dist,
                "headwind_component_kt": signed_hw,
                "crosswind_component_kt": crosswind,
            }
        ]
        leg_cruise_ete, floored = _cruise_minutes(
            samples, climb_nm, climb_nm + cruise_nm, cruise_speed_kt, min_groundspeed
        )
        if floored:
            slow_legs += 1
        cruise_ete += leg_cruise_ete
        leg_ete = leg_cruise_ete + phases.climb_minutes_for(climb_nm) + phases.descent_minutes_for(descent_nm)
        groundspeed = (
            leg_dist / leg_ete * 60
            if leg_ete > 0
            else max(min_groundspeed, groundspeed_kt(cruise_speed_kt, signed_hw, crosswind))
        )

        hw_stored = max(0.0, signed_hw) if wind_data.get("wind_speed_kt") is not None else None
        tw_stored = max(0.0, -signed_hw) if wind_data.get("wind_speed_kt") is not None else None

        segments.append(
            {
                "segment_index": i,
                "start_lat": lat1,
                "start_lon": lon1,
                "end_lat": lat2,
                "end_lon": lon2,
                "distance_nm": round(leg_dist, 2),
                "bearing_deg": round(bearing, 2),
                "wind_speed_kt": wind_data.get("wind_speed_kt"),
                "wind_direction_deg": wind_data.get("wind_direction_deg"),
                "headwind_component_kt": round(hw_stored, 2) if hw_stored is not None else None,
                "tailwind_component_kt": round(tw_stored, 2) if tw_stored is not None else None,
                "wind_altitude_ft": wind_data.get("wind_altitude_ft"),
                "wind_pressure_level_hpa": wind_data.get("wind_pressure_level_hpa"),
                "wind_source": wind_data.get("wind_source"),
                "groundspeed_kt": round(groundspeed, 2),
                "ete_minutes": round(leg_ete, 2),
            }
        )

    total_ete = cruise_ete + phases.climb_minutes + phases.descent_minutes
    fuel_breakdown = calculate_fuel_breakdown(
        aircraft,
        cruise_ete_minutes=cruise_ete,
        climb_ete_minutes=phases.climb_minutes,
        descent_ete_minutes=phases.descent_minutes,
    )
    fuel_burn = fuel_breakdown.trip_fuel_gal
    fuel_cost = fuel_breakdown.total_required_gal * fuel_price

    score_input = ScoringInput(
        ete_minutes=total_ete,
        fuel_burn_gal=fuel_breakdown.total_required_gal,
        baseline_ete_minutes=scoring_context["baseline_ete_minutes"],
        baseline_fuel_gal=scoring_context["baseline_fuel_gal"],
        departure_delay_min=scoring_context.get("departure_delay_min", 0),
        destination_delay_min=scoring_context.get("destination_delay_min", 0),
        departure_closed=scoring_context.get("departure_closed", False),
        destination_closed=scoring_context.get("destination_closed", False),
        departure_ground_stop=scoring_context.get("departure_ground_stop", False),
        destination_ground_stop=scoring_context.get("destination_ground_stop", False),
        departure_flight_category=scoring_context.get("departure_flight_category"),
        destination_flight_category=scoring_context.get("destination_flight_category"),
        checkpoint_weather_penalty=scoring_context.get("checkpoint_weather_penalty", 0),
        diversion_count=scoring_context.get("diversion_count", 5),
        min_diversion_runway_ft=scoring_context.get("min_diversion_runway_ft", 5000),
    )
    breakdown = calculate_normalized_score(score_input, preference=route_preference)

    return RouteVariant(
        name=name,
        waypoints=waypoints,
        distance_nm=round(total_distance, 2),
        ete_minutes=round(total_ete, 2),
        fuel_burn_gal=round(fuel_burn, 2),
        fuel_cost_usd=round(fuel_breakdown.total_required_gal * fuel_price, 2),
        segments=segments,
        score=breakdown["composite_score"],
        score_breakdown=breakdown,
        fuel_breakdown=fuel_breakdown.to_dict(),
        slow_legs=slow_legs,
    )


class RouteCalculatorService:
    async def calculate(
        self,
        departure: dict[str, Any],
        destination: dict[str, Any],
        aircraft: dict[str, Any],
        fuel_price: float,
        supabase: Any | None = None,
        checkpoint_candidates: list[dict[str, Any]] | None = None,
        departure_time: datetime | None = None,
        route_preference: str = "balanced",
    ) -> dict[str, Any]:
        dep_lat, dep_lon = departure["latitude"], departure["longitude"]
        dest_lat, dest_lon = destination["latitude"], destination["longitude"]
        cruise = int(aircraft["cruise_speed_kt"])
        fuel_burn_gph = float(aircraft["fuel_burn_gph"])
        min_runway = int(aircraft.get("min_runway_ft") or 3000)

        warnings: list[str] = [
            "Live weather and FAA data integrations are not connected. "
            "Route scoring uses winds (Open-Meteo) and airport geometry only. "
            "Verify METAR, TAF, TFRs, NOTAMs, and NAS status through official briefings."
        ]

        dep_icao = departure.get("icao_code") or departure.get("ident")
        dest_icao = destination.get("icao_code") or destination.get("ident")

        async def _metar(icao: str | None):
            return await aviation_weather_client.get_metar(icao) if icao else None

        async def _taf(icao: str | None):
            return await aviation_weather_client.get_taf(icao) if icao else None

        async def _faa(icao: str | None):
            return await faa_nas_client.get_airport_status(icao, supabase=supabase) if icao else {}

        (
            dep_weather,
            dest_weather,
            dep_taf,
            dest_taf,
            dep_status,
            dest_status,
        ) = await asyncio.gather(
            _metar(dep_icao),
            _metar(dest_icao),
            _taf(dep_icao),
            _taf(dest_icao),
            _faa(dep_icao),
            _faa(dest_icao),
        )
        dep_status = dep_status or {}
        dest_status = dest_status or {}

        direct_dist = haversine_nm(dep_lat, dep_lon, dest_lat, dest_lon)
        baseline_phases = plan_phases(direct_dist, aircraft)
        baseline_cruise_ete = (direct_dist - baseline_phases.climb_nm - baseline_phases.descent_nm) / cruise * 60
        baseline_ete = baseline_cruise_ete + baseline_phases.climb_minutes + baseline_phases.descent_minutes
        baseline_fuel = calculate_fuel_breakdown(
            aircraft,
            cruise_ete_minutes=baseline_cruise_ete,
            climb_ete_minutes=baseline_phases.climb_minutes,
            descent_ete_minutes=baseline_phases.descent_minutes,
        ).total_required_gal

        direct_waypoints = [(dep_lat, dep_lon), (dest_lat, dest_lon)]

        diversion_airports: list[dict[str, Any]] = []
        if supabase:
            diversion_airports = find_diversion_airports_postgis(
                supabase,
                dep_lon,
                dep_lat,
                dest_lon,
                dest_lat,
                departure["id"],
                destination["id"],
                min_runway_ft=min_runway,
                fallback_candidates=checkpoint_candidates or [],
            )
        if not diversion_airports:
            warnings.append("No suitable diversion airports found — verify alternate airports manually")

        best_diversion = diversion_airports[0]["airport"] if diversion_airports else None

        checkpoints_raw = select_checkpoint_airports(
            direct_waypoints,
            checkpoint_candidates or [],
            departure["id"],
            destination["id"],
        )
        checkpoint_weather = await fetch_checkpoint_weather(checkpoints_raw)
        checkpoint_penalty = sum(c.get("weather_penalty", 0) for c in checkpoint_weather) / max(
            len(checkpoint_weather), 1
        )
        best_wx_cp = best_weather_checkpoint(checkpoint_weather)

        scoring_context = {
            "baseline_ete_minutes": baseline_ete,
            "baseline_fuel_gal": baseline_fuel,
            "departure_delay_min": dep_status.get("delay_minutes", 0),
            "destination_delay_min": dest_status.get("delay_minutes", 0),
            "departure_closed": dep_status.get("is_closed", False),
            "destination_closed": dest_status.get("is_closed", False),
            "departure_ground_stop": dep_status.get("ground_stop", False),
            "destination_ground_stop": dest_status.get("ground_stop", False),
            "departure_flight_category": (dep_weather or {}).get("flight_category"),
            "destination_flight_category": (dest_weather or {}).get("flight_category"),
            "checkpoint_weather_penalty": checkpoint_penalty,
            "diversion_count": len(diversion_airports),
            "min_diversion_runway_ft": min(
                (d["airport"].get("longest_runway_ft") or 99999 for d in diversion_airports),
                default=0,
            ),
        }

        variant_defs = _build_route_variants(
            dep_lat,
            dep_lon,
            dest_lat,
            dest_lon,
            diversion_airport=best_diversion,
            weather_checkpoint=best_wx_cp,
        )

        variant_tasks = [
            _compute_variant_metrics(
                vname,
                waypoints,
                aircraft,
                fuel_price,
                scoring_context,
                route_preference,
                departure_time=departure_time,
            )
            for vname, waypoints in variant_defs
        ]
        variants = list(await asyncio.gather(*variant_tasks))

        variants.sort(key=lambda v: v.score, reverse=True)
        primary = variants[0]
        alternate = variants[1] if len(variants) > 1 else None

        # The stored quality and the warnings describe the winds of the route that is actually returned.
        wind_quality = wind_quality_from_segments(primary.segments)
        warnings.extend(wind_quality_warnings(primary.segments))
        warnings.extend(primary.fuel_breakdown.get("warnings") or [])
        if primary.slow_legs:
            warnings.append(
                f"Very strong winds on {primary.slow_legs} leg(s): groundspeed was limited to "
                f"{MIN_GROUNDSPEED_FRACTION:.0%} of cruise speed, so ETE and fuel are unreliable "
                "(educational estimate only)"
            )

        route_path = [{"lat": lat, "lon": lon} for lat, lon in primary.waypoints]
        checkpoint_icaos = [c.get("icao") for c in checkpoint_weather if c.get("icao")]

        from app.services.live_data.live_data_orchestrator import live_data_orchestrator
        from app.services.live_data.live_data_scoring import (
            apply_live_penalties_to_score_breakdown,
            compute_live_penalties,
            live_data_feature_flags,
            live_data_warnings,
        )

        live_snapshot, provider_timings = await live_data_orchestrator.build_snapshot(
            route_id=None,
            departure_icao=dep_icao,
            destination_icao=dest_icao,
            route_path=route_path,
            checkpoint_icaos=checkpoint_icaos,
            supabase=supabase,
        )
        live_penalties = compute_live_penalties(live_snapshot)
        warnings.extend(live_data_warnings(live_snapshot))
        primary.score_breakdown = apply_live_penalties_to_score_breakdown(
            primary.score_breakdown, live_penalties
        )
        primary.score = primary.score_breakdown.get("composite_score", primary.score)
        live_flags = live_data_feature_flags(live_snapshot)

        candidate_summaries = [
            {
                "name": v.name,
                "distance_nm": v.distance_nm,
                "ete_minutes": v.ete_minutes,
                "fuel_burn_gal": v.fuel_burn_gal,
                "score": v.score,
                "selected": v.name in (primary.name, alternate.name if alternate else ""),
            }
            for v in variants
        ]

        enriched_request = {
            "departure_airport_id": departure.get("id"),
            "destination_airport_id": destination.get("id"),
            "aircraft_profile_id": aircraft.get("id"),
            "route_preference": route_preference,
            "_aircraft_cruise_speed_kt": cruise,
            "_cruise_altitude_ft": int(aircraft.get("cruise_altitude_ft") or 10000),
        }
        route_result_stub = {
            "primary_distance_nm": primary.distance_nm,
            "primary_ete_minutes": primary.ete_minutes,
            "primary_score": primary.score,
            "normalized_score_breakdown": primary.score_breakdown,
            "departure_weather": {"metar": dep_weather, "faa_status": dep_status},
            "destination_weather": {"metar": dest_weather, "faa_status": dest_status},
            "weather_checkpoints": checkpoint_weather,
            "route_candidates": candidate_summaries,
            "wind_data_quality": wind_quality,
            "live_data_snapshot": live_snapshot.to_dict(),
        }
        delay_features = extract_delay_features(
            enriched_request, route_result_stub, primary.segments, diversion_airports
        )
        delay_features.update(live_flags)
        ete_features = extract_ete_features(enriched_request, route_result_stub, primary.segments)
        ete_features["weather_penalty"] = live_penalties.get("weather_penalty", 0)
        ete_features["tfr_hazard_reroute_penalty"] = live_penalties.get("tfr_reroute_penalty", 0)

        try:
            from ml.inference.delay_risk_model import delay_risk_model
            from ml.inference.ete_model import ete_prediction_model

            delay_prediction = delay_risk_model.predict(delay_features)
            ete_prediction = ete_prediction_model.predict(ete_features, primary.ete_minutes)
        except ImportError:
            delay_prediction = predict_delay_risk(delay_features)
            delay_prediction["model_target"] = "delay_risk"
            ete_prediction = {
                "model_name": "deterministic_engine_v1",
                "model_target": "ete_prediction",
                "ete_minutes": primary.ete_minutes,
                "ml_adjusted_ete_minutes": primary.ete_minutes,
                "is_surrogate": True,
            }

        return {
            "primary": primary,
            "alternate": alternate,
            "variants": variants,
            "candidate_summaries": candidate_summaries,
            "warnings": list(dict.fromkeys(warnings)),
            "departure_weather": {"metar": dep_weather, "taf": dep_taf, "faa_status": dep_status},
            "destination_weather": {"metar": dest_weather, "taf": dest_taf, "faa_status": dest_status},
            "diversion_airports": diversion_airports,
            "weather_checkpoints": checkpoint_weather,
            "wind_data_quality": wind_quality,
            "delay_prediction": delay_prediction,
            "ete_prediction": ete_prediction,
            "delay_features": delay_features,
            "ete_features": ete_features,
            "route_preference": route_preference,
            "enriched_request": enriched_request,
            "live_data_snapshot": live_snapshot.to_dict(),
            "provider_timings": provider_timings,
        }


route_calculator = RouteCalculatorService()


# Geometric corridor search retained for unit tests (production uses PostGIS)
def find_diversion_airports(
    route_waypoints: list[tuple[float, float]],
    all_airports: list[dict[str, Any]],
    departure_id: str,
    destination_id: str,
    min_runway_ft: int = 3000,
) -> list[dict[str, Any]]:
    from app.geo.utils import cross_track_distance_nm

    candidates: list[dict[str, Any]] = []
    for airport in all_airports:
        if airport["id"] in (departure_id, destination_id):
            continue
        if airport.get("airport_type") not in ("small_airport", "medium_airport", "large_airport"):
            continue
        if (airport.get("longest_runway_ft") or 0) < min_runway_ft:
            continue
        apt_lat, apt_lon = airport["latitude"], airport["longitude"]
        min_ct = float("inf")
        for i in range(len(route_waypoints) - 1):
            lat1, lon1 = route_waypoints[i]
            lat2, lon2 = route_waypoints[i + 1]
            min_ct = min(min_ct, cross_track_distance_nm(lat1, lon1, lat2, lon2, apt_lat, apt_lon))
        if 25.0 <= min_ct <= 50.0:
            candidates.append(
                {"airport": airport, "distance_from_route_nm": round(min_ct, 2)}
            )
    candidates.sort(key=lambda c: c["distance_from_route_nm"])
    return candidates[:10]
