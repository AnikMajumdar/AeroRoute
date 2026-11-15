from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.geo.timezones import to_local_time
from app.services.weather_checkpoints import normalize_flight_category
from app.utils.datetime_parse import parse_iso_datetime

DATASET_VERSION = "v1"
CATEGORY_RANK = {"VFR": 0, "MVFR": 1, "IFR": 2, "LIFR": 3}
# Missing weather must not look like good weather: unknown categories get their own value instead of VFR's 0.
UNKNOWN_CATEGORY_ORD = -1

DELAY_FEATURE_COLUMNS = [
    "departure_hour_local",
    "departure_day_of_week",
    "departure_month",
    "route_distance_nm",
    "aircraft_cruise_speed_kt",
    "cruise_altitude_ft",
    "departure_flight_category_ord",
    "destination_flight_category_ord",
    "worst_enroute_flight_category_ord",
    "number_of_ifr_checkpoints",
    "number_of_lifr_checkpoints",
    "avg_headwind_component_kt",
    "max_headwind_component_kt",
    "diversion_count",
    "departure_delay_minutes",
    "destination_delay_minutes",
    "departure_closed",
    "destination_closed",
    "departure_ground_stop",
    "destination_ground_stop",
    "departure_faa_unknown",
    "destination_faa_unknown",
    "weather_score",
    "delay_score",
]

ETE_FEATURE_COLUMNS = [
    "route_distance_nm",
    "aircraft_cruise_speed_kt",
    "cruise_altitude_ft",
    "avg_headwind_component_kt",
    "max_headwind_component_kt",
    "avg_tailwind_component_kt",
    "departure_hour_local",
    "departure_month",
    "weather_score",
    "delay_score",
    "number_of_segments",
    "route_candidate_type_ord",
]


def _category_ord(cat: Any) -> int:
    return CATEGORY_RANK.get(normalize_flight_category(cat), UNKNOWN_CATEGORY_ORD)


def _faa_status_from_weather(weather: dict[str, Any] | None) -> dict[str, Any]:
    if not weather or not isinstance(weather, dict):
        return {}
    return weather.get("faa_status") or {}


def _faa_unknown(faa: dict[str, Any]) -> int:
    """1 when there is no usable FAA NAS status (absent, 'unknown' or unparsable), else 0."""
    return int(not faa or faa.get("status") in (None, "unknown") or not faa.get("parse_success", True))


def _metar_from_weather(weather: dict[str, Any] | None) -> dict[str, Any]:
    if not weather or not isinstance(weather, dict):
        return {}
    metar = weather.get("metar")
    return metar if isinstance(metar, dict) else {}


def _score_component(score_breakdown: dict[str, Any] | None, key: str) -> float:
    if not score_breakdown:
        return 50.0
    components = score_breakdown.get("component_scores") or {}
    return float(components.get(key, 50))


def _segment_wind_stats(segments: list[dict[str, Any]]) -> dict[str, float]:
    headwinds: list[float] = []
    tailwinds: list[float] = []
    for seg in segments:
        hw = seg.get("headwind_component_kt")
        tw = seg.get("tailwind_component_kt")
        if hw is not None:
            headwinds.append(float(hw))
        if tw is not None:
            tailwinds.append(float(tw))
    return {
        "avg_headwind_component_kt": sum(headwinds) / len(headwinds) if headwinds else 0.0,
        "max_headwind_component_kt": max(headwinds) if headwinds else 0.0,
        "avg_tailwind_component_kt": sum(tailwinds) / len(tailwinds) if tailwinds else 0.0,
    }


def _checkpoint_stats(checkpoints: list[dict[str, Any]]) -> dict[str, Any]:
    ifr = lifr = 0
    cats: list[str] = []
    for cp in checkpoints:
        cat = normalize_flight_category(cp.get("flight_category"))
        cats.append(cat)
        if cat == "IFR":
            ifr += 1
        elif cat == "LIFR":
            lifr += 1
    worst = max(
        (CATEGORY_RANK[c] for c in cats if c in CATEGORY_RANK),
        default=UNKNOWN_CATEGORY_ORD,  # no checkpoint with known weather
    )
    return {
        "number_of_ifr_checkpoints": ifr,
        "number_of_lifr_checkpoints": lifr,
        "worst_enroute_flight_category_ord": worst,
    }


def _departure_time_parts(
    request: dict[str, Any], lat: float | None = None, lon: float | None = None
) -> tuple[int, int, int]:
    """(hour, weekday, month) of the departure in the local time of the departure airport.

    Without coordinates the UTC values are returned.
    """
    raw = request.get("departure_time")
    dt = parse_iso_datetime(raw) if isinstance(raw, str) and raw else raw
    if not isinstance(dt, datetime):
        dt = datetime.now(timezone.utc)
    local = to_local_time(dt, lat, lon)
    return local.hour, local.weekday(), local.month


def _departure_coordinates(
    route_result: dict[str, Any], segments: list[dict[str, Any]] | None
) -> tuple[float | None, float | None]:
    """Coordinates of the departure airport: the route path (or first leg) starts there."""
    path = route_result.get("primary_path") or []
    if path and isinstance(path[0], dict) and path[0].get("lat") is not None and path[0].get("lon") is not None:
        return float(path[0]["lat"]), float(path[0]["lon"])
    for seg in sorted(segments or [], key=lambda s: s.get("segment_index", 0)):
        if seg.get("start_lat") is not None and seg.get("start_lon") is not None:
            return float(seg["start_lat"]), float(seg["start_lon"])
    return None, None


def _primary_candidate_type(route: dict[str, Any]) -> str:
    candidates = route.get("route_candidates") or []
    for c in candidates:
        if c.get("selected") and c.get("name"):
            return str(c["name"])
    return "direct"


def _candidate_type_ord(name: str) -> int:
    order = {
        "direct": 0,
        "left_offset": 1,
        "right_offset": 2,
        "via_diversion": 3,
        "via_weather_checkpoint": 4,
        # Names stored (and used for the training data) before offsets were labelled by side of track:
        # "north_offset" was always the left-of-track candidate, "south_offset" the right-of-track one.
        "north_offset": 1,
        "south_offset": 2,
    }
    return order.get(name, 0)


def extract_delay_features(
    route_request: dict[str, Any],
    route_result: dict[str, Any],
    segments: list[dict[str, Any]] | None = None,
    diversions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    dep_wx = route_result.get("departure_weather") or {}
    dest_wx = route_result.get("destination_weather") or {}
    dep_metar = _metar_from_weather(dep_wx)
    dest_metar = _metar_from_weather(dest_wx)
    dep_faa = _faa_status_from_weather(dep_wx)
    dest_faa = _faa_status_from_weather(dest_wx)
    checkpoints = route_result.get("weather_checkpoints") or []
    score_breakdown = route_result.get("normalized_score_breakdown") or route_result.get("score_breakdown")
    wind_stats = _segment_wind_stats(segments or [])
    cp_stats = _checkpoint_stats(checkpoints)
    hour, dow, month = _departure_time_parts(route_request, *_departure_coordinates(route_result, segments))

    return {
        "departure_airport": route_request.get("departure_airport_id"),
        "destination_airport": route_request.get("destination_airport_id"),
        "departure_icao": dep_metar.get("icao"),
        "destination_icao": dest_metar.get("icao"),
        "aircraft_type": route_request.get("aircraft_profile_id"),
        "departure_hour_local": hour,
        "departure_day_of_week": dow,
        "departure_month": month,
        "route_distance_nm": float(route_result.get("primary_distance_nm") or 0),
        "aircraft_cruise_speed_kt": float(route_request.get("_aircraft_cruise_speed_kt") or 0),
        "cruise_altitude_ft": float(route_request.get("_cruise_altitude_ft") or 10000),
        "departure_flight_category": dep_metar.get("flight_category"),
        "destination_flight_category": dest_metar.get("flight_category"),
        "departure_flight_category_ord": _category_ord(dep_metar.get("flight_category")),
        "destination_flight_category_ord": _category_ord(dest_metar.get("flight_category")),
        "worst_enroute_flight_category_ord": cp_stats["worst_enroute_flight_category_ord"],
        "number_of_ifr_checkpoints": cp_stats["number_of_ifr_checkpoints"],
        "number_of_lifr_checkpoints": cp_stats["number_of_lifr_checkpoints"],
        "avg_headwind_component_kt": wind_stats["avg_headwind_component_kt"],
        "max_headwind_component_kt": wind_stats["max_headwind_component_kt"],
        "diversion_count": len(diversions or []),
        "departure_faa_status": dep_faa.get("status"),
        "destination_faa_status": dest_faa.get("status"),
        "departure_delay_minutes": int(dep_faa.get("delay_minutes") or 0),
        "destination_delay_minutes": int(dest_faa.get("delay_minutes") or 0),
        "departure_closed": int(bool(dep_faa.get("is_closed"))),
        "destination_closed": int(bool(dest_faa.get("is_closed"))),
        "departure_ground_stop": int(bool(dep_faa.get("ground_stop"))),
        "destination_ground_stop": int(bool(dest_faa.get("ground_stop"))),
        "departure_faa_unknown": _faa_unknown(dep_faa),
        "destination_faa_unknown": _faa_unknown(dest_faa),
        "weather_score": _score_component(score_breakdown, "weather"),
        "delay_score": _score_component(score_breakdown, "delay"),
        "route_preference": route_request.get("route_preference", "balanced"),
        "wind_data_quality": route_result.get("wind_data_quality"),
    }


def extract_ete_features(
    route_request: dict[str, Any],
    route_result: dict[str, Any],
    segments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    score_breakdown = route_result.get("normalized_score_breakdown") or route_result.get("score_breakdown")
    wind_stats = _segment_wind_stats(segments or [])
    hour, _, month = _departure_time_parts(route_request, *_departure_coordinates(route_result, segments))
    candidate_type = _primary_candidate_type(route_result)

    return {
        "route_distance_nm": float(route_result.get("primary_distance_nm") or 0),
        "aircraft_cruise_speed_kt": float(route_request.get("_aircraft_cruise_speed_kt") or 0),
        "cruise_altitude_ft": float(route_request.get("_cruise_altitude_ft") or 10000),
        "avg_headwind_component_kt": wind_stats["avg_headwind_component_kt"],
        "max_headwind_component_kt": wind_stats["max_headwind_component_kt"],
        "avg_tailwind_component_kt": wind_stats["avg_tailwind_component_kt"],
        "route_candidate_type": candidate_type,
        "route_candidate_type_ord": _candidate_type_ord(candidate_type),
        "departure_hour_local": hour,
        "departure_month": month,
        "weather_score": _score_component(score_breakdown, "weather"),
        "delay_score": _score_component(score_breakdown, "delay"),
        "number_of_segments": len(segments or []),
        "wind_data_quality": route_result.get("wind_data_quality"),
        "route_preference_ord": {"balanced": 0, "fastest": 1, "fuel_saver": 2, "weather_cautious": 3}.get(
            route_request.get("route_preference", "balanced"), 0
        ),
        "weather_penalty": float(route_result.get("_weather_penalty") or 0),
        "tfr_hazard_reroute_penalty": float(route_result.get("_tfr_hazard_reroute_penalty") or 0),
    }


def refresh_delay_feature_categories(features: dict[str, Any]) -> dict[str, Any]:
    """Recompute category ords and FAA-unknown flags from the raw stored values (fixes legacy stored features).

    Legacy rows encoded missing weather as VFR (0) and missing FAA data as "known"; both are corrected here.
    """
    feat = dict(features)
    for role in ("departure", "destination"):
        cat = feat.get(f"{role}_flight_category")
        feat[f"{role}_flight_category_ord"] = _category_ord(cat)
        if f"{role}_faa_status" in feat and feat[f"{role}_faa_status"] in (None, "unknown"):
            feat[f"{role}_faa_unknown"] = 1
    return feat


def _composite_delay_risk_score(features: dict[str, Any]) -> float:
    """Route-derived risk score when FAA NAS data is mostly unknown (training/inference aid)."""
    score = 0.0
    score += min(35.0, float(features.get("max_headwind_component_kt") or 0) * 1.2)
    score += int(features.get("number_of_ifr_checkpoints") or 0) * 12
    score += int(features.get("number_of_lifr_checkpoints") or 0) * 22
    score += max(0.0, 100.0 - float(features.get("weather_score") or 100)) * 0.4
    score += max(0.0, 100.0 - float(features.get("delay_score") or 100)) * 0.4
    if int(features.get("diversion_count") or 0) == 0:
        score += 12
    if features.get("wind_data_quality") == "surface_fallback":
        score += 10
    # Longer routes slightly higher planning complexity (educational proxy)
    score += min(15.0, float(features.get("route_distance_nm") or 0) / 200.0)
    return round(score, 1)


def delay_label_from_features(features: dict[str, Any]) -> dict[str, Any]:
    """low / medium / high delay risk from FAA, weather, live data, and route composite signals."""
    dep_delay = int(features.get("departure_delay_minutes") or 0)
    dest_delay = int(features.get("destination_delay_minutes") or 0)
    max_delay = max(dep_delay, dest_delay)

    closed = bool(features.get("departure_closed")) or bool(features.get("destination_closed"))
    ground_stop = bool(features.get("departure_ground_stop")) or bool(features.get("destination_ground_stop"))
    dep_unknown = bool(features.get("departure_faa_unknown"))
    dest_unknown = bool(features.get("destination_faa_unknown"))
    lifr = (
        int(features.get("departure_flight_category_ord") or 0) == 3
        or int(features.get("destination_flight_category_ord") or 0) == 3
        or int(features.get("worst_enroute_flight_category_ord") or 0) == 3
    )
    ifr = (
        int(features.get("departure_flight_category_ord") or 0) >= 2
        or int(features.get("destination_flight_category_ord") or 0) >= 2
        or int(features.get("worst_enroute_flight_category_ord") or 0) >= 2
    )
    tfr_intersects = bool(features.get("tfr_intersects_route"))
    sigmet = bool(features.get("sigmet_intersects"))
    airmet = bool(features.get("airmet_intersects"))
    adverse_pireps = int(features.get("adverse_pirep_count") or 0)
    notam_closure = bool(features.get("notam_airport_closure")) or bool(features.get("notam_runway_closure"))
    composite = _composite_delay_risk_score(features)

    reasons: list[str] = []
    if closed:
        reasons.append("airport_closure_faa_nas")
    if ground_stop:
        reasons.append("ground_stop_faa_nas")
    if max_delay >= 30:
        reasons.append("faa_delay_ge_30")
    if tfr_intersects:
        reasons.append("tfr_intersects_route")
    if sigmet:
        reasons.append("sigmet_intersects_route")
    if lifr:
        reasons.append("lifr_dep_dest_or_checkpoint")
    if notam_closure:
        reasons.append("notam_closure")

    if closed or ground_stop or max_delay >= 30 or tfr_intersects or sigmet or lifr or notam_closure:
        level = "high"
        label_source = {"rules": "live_data_rules_v2", "reasons": reasons}
    elif (max_delay > 0 and max_delay < 30) or ifr or airmet or adverse_pireps >= 2 or int(features.get("tfr_nearby_count") or 0) > 0:
        level = "medium"
        if max_delay > 0:
            reasons.append("faa_delay_lt_30")
        if ifr:
            reasons.append("ifr_dep_dest_or_checkpoint")
        if airmet:
            reasons.append("airmet_intersects")
        if adverse_pireps >= 2:
            reasons.append("multiple_adverse_pireps")
        if int(features.get("tfr_nearby_count") or 0) > 0:
            reasons.append("tfr_nearby")
        label_source = {"rules": "live_data_rules_v2", "reasons": reasons}
    elif composite >= 50:
        level = "high"
        label_source = {"rules": "composite_proxy_v1", "reasons": ["composite_score_ge_50"]}
    elif composite >= 22 or adverse_pireps == 1:
        level = "medium"
        label_source = {"rules": "composite_proxy_v1", "reasons": ["composite_score_ge_22" if composite >= 22 else "adverse_pirep"]}
    else:
        level = "low"
        label_source = {"rules": "live_data_rules_v2" if not (dep_unknown or dest_unknown) else "composite_proxy_v1", "reasons": ["no_major_signals"]}

    return {
        "delay_risk": level,
        "label_source": label_source,
        "max_delay_minutes": max_delay,
        "composite_risk_score": composite,
        "data_basis": [
            s for s, ok in [
                ("FAA NAS", not (dep_unknown and dest_unknown)),
                ("METAR/TAF", bool(features.get("departure_flight_category"))),
                ("TFR", tfr_intersects or int(features.get("tfr_nearby_count") or 0) > 0),
                ("weather hazards", sigmet or airmet or adverse_pireps > 0),
                ("NOTAM", bool(features.get("notam_connected"))),
            ] if ok
        ],
        "confidence": features.get("live_data_confidence", "medium"),
    }


def ete_label_from_route(route_result: dict[str, Any]) -> dict[str, Any]:
    ete = float(route_result.get("primary_ete_minutes") or 0)
    return {
        "ete_minutes": ete,
        "label_source": "deterministic_engine_v1",
    }


def features_to_vector(features: dict[str, Any], columns: list[str]) -> list[float]:
    return [float(features.get(col, 0) or 0) for col in columns]
