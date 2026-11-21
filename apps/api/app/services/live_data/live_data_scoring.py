from __future__ import annotations

from typing import Any

from app.services.live_data.types import LiveDataSnapshot
from app.services.route_scoring import combine_components


def summarize_live_restrictions(snapshot: LiveDataSnapshot | dict[str, Any]) -> dict[str, Any]:
    data = snapshot.to_dict() if isinstance(snapshot, LiveDataSnapshot) else snapshot
    tfrs = data.get("restrictions", {}).get("tfrs") or []
    return {
        "intersecting": [t for t in tfrs if t.get("impact") == "intersects"],
        "nearby": [t for t in tfrs if t.get("impact") == "nearby"],
        "unmapped": [t for t in tfrs if t.get("impact") == "unmapped"],
        "notam_connected": data.get("restrictions", {}).get("notam_connected", False),
        "notams": data.get("restrictions", {}).get("notams") or [],
        "fetched_at": data.get("fetched_at"),
    }


def summarize_weather_hazards(snapshot: LiveDataSnapshot | dict[str, Any]) -> dict[str, Any]:
    data = snapshot.to_dict() if isinstance(snapshot, LiveDataSnapshot) else snapshot
    hazards = data.get("weather", {}).get("hazards") or []
    return {
        "hazards": hazards,
        "sigmets": [h for h in hazards if "sigmet" in str(h.get("hazard_type", "")).lower()],
        "airmets": [h for h in hazards if "airmet" in str(h.get("hazard_type", "")).lower() or h.get("hazard_type") == "gairmet"],
        "pireps": [h for h in hazards if h.get("hazard_type") == "pirep"],
        "fetched_at": data.get("fetched_at"),
    }


def live_data_feature_flags(snapshot: LiveDataSnapshot | dict[str, Any]) -> dict[str, Any]:
    """Extract boolean/count flags for delay labeling and scoring."""
    data = snapshot.to_dict() if isinstance(snapshot, LiveDataSnapshot) else snapshot
    restrictions = summarize_live_restrictions(data)
    hazards = summarize_weather_hazards(data)
    notams = restrictions["notams"]
    high_notams = [n for n in notams if n.get("severity") == "high" or n.get("category") in ("airport_closure", "runway")]
    adverse_pireps = [
        h for h in hazards["pireps"]
        if h.get("severity") in ("medium", "high") or any(
            k in (h.get("raw_text") or "").lower() for k in ("turb", "ice", "icing")
        )
    ]
    return {
        "tfr_intersects_route": int(any(t.get("impact") == "intersects" for t in restrictions["intersecting"])),
        "tfr_nearby_count": len(restrictions["nearby"]),
        "tfr_unmapped_count": len(restrictions["unmapped"]),
        "sigmet_intersects": int(any(h.get("intersects_route") for h in hazards["sigmets"])),
        "airmet_intersects": int(any(h.get("intersects_route") for h in hazards["airmets"])),
        "adverse_pirep_count": len(adverse_pireps),
        "notam_airport_closure": int(any(n.get("category") == "airport_closure" for n in notams)),
        "notam_runway_closure": int(any(n.get("category") == "runway" for n in notams)),
        "notam_high_severity_count": len(high_notams),
        "notam_connected": int(restrictions.get("notam_connected", False)),
        "live_data_confidence": data.get("confidence", {}).get("level", "low"),
    }


def compute_live_penalties(snapshot: LiveDataSnapshot | dict[str, Any]) -> dict[str, float]:
    flags = live_data_feature_flags(snapshot)
    weather_pen = 0.0
    delay_pen = 0.0
    if flags["sigmet_intersects"]:
        weather_pen += 35
        delay_pen += 25
    if flags["airmet_intersects"]:
        weather_pen += 18
        delay_pen += 12
    if flags["adverse_pirep_count"] >= 2:
        weather_pen += 15
        delay_pen += 10
    elif flags["adverse_pirep_count"] == 1:
        weather_pen += 8
    if flags["tfr_intersects_route"]:
        delay_pen += 40
        weather_pen += 10
    if flags["tfr_nearby_count"]:
        delay_pen += 10 * min(flags["tfr_nearby_count"], 3)
    if flags["tfr_unmapped_count"]:
        delay_pen += 8 * min(flags["tfr_unmapped_count"], 2)
    if flags["notam_airport_closure"]:
        delay_pen += 50
    if flags["notam_runway_closure"]:
        delay_pen += 30
    return {
        "weather_penalty": weather_pen,
        "delay_penalty": delay_pen,
        "tfr_reroute_penalty": 15.0 if flags["tfr_intersects_route"] else 0.0,
    }


def apply_live_penalties_to_score_breakdown(
    score_breakdown: dict[str, Any],
    penalties: dict[str, float],
) -> dict[str, Any]:
    """Subtract the live-data penalties from the weather and delay components and recompute the composite.

    A component that had no data (None) is not scored, so without a penalty it stays out of the composite. A
    penalty is a real adverse signal, though: it is applied to the no-penalty score of 100 and the component
    then counts.
    """
    updated = dict(score_breakdown)
    components = dict(updated.get("component_scores") or {})
    for component, penalty_key in (("weather", "weather_penalty"), ("delay", "delay_penalty")):
        penalty = penalties.get(penalty_key)
        if penalty:
            base = components.get(component)
            components[component] = max(0.0, (100.0 if base is None else base) - penalty)
    updated["component_scores"] = {k: None if v is None else round(v, 1) for k, v in components.items()}
    weights = updated.get("weights") or {}
    composite, effective_weights = combine_components(components, weights)
    updated["composite_score"] = composite
    updated["effective_weights"] = effective_weights
    updated["unavailable_components"] = [key for key in weights if components.get(key) is None]
    updated["total"] = composite
    updated["live_data_penalties"] = penalties
    return updated


def live_data_warnings(snapshot: LiveDataSnapshot | dict[str, Any]) -> list[str]:
    from app.services.aviation_weather import INTEGRATION_DISABLED_MESSAGE as AWC_MSG
    from app.services.faa_nas import INTEGRATION_DISABLED_MESSAGE as FAA_MSG

    data = snapshot.to_dict() if isinstance(snapshot, LiveDataSnapshot) else snapshot
    warnings: list[str] = [
        AWC_MSG,
        FAA_MSG,
    ]
    warnings.extend(data.get("warnings") or [])
    # The providers repeat the same "not connected" messages; show each one once.
    return list(dict.fromkeys(warnings))
