from __future__ import annotations

from typing import Any


def predict_delay_risk(features: dict[str, Any]) -> dict[str, Any]:
    """
    Rules-based delay risk baseline. Structured for future CatBoost/logistic regression.
    """
    dep_delay = int(features.get("departure_delay_minutes") or features.get("departure_delay_min", 0) or 0)
    dest_delay = int(features.get("destination_delay_minutes") or features.get("destination_delay_min", 0) or 0)
    dep_closed = bool(features.get("departure_closed"))
    dest_closed = bool(features.get("destination_closed"))
    dep_gs = bool(features.get("departure_ground_stop"))
    dest_gs = bool(features.get("destination_ground_stop"))
    dep_cat = (
        features.get("departure_flight_category")
        or features.get("departure_flight_category_ord")
        or "VFR"
    )
    dest_cat = (
        features.get("destination_flight_category")
        or features.get("destination_flight_category_ord")
        or "VFR"
    )
    if isinstance(dep_cat, int):
        dep_cat = ["VFR", "MVFR", "IFR", "LIFR"][min(dep_cat, 3)]
    if isinstance(dest_cat, int):
        dest_cat = ["VFR", "MVFR", "IFR", "LIFR"][min(dest_cat, 3)]
    dep_cat = str(dep_cat).upper()
    dest_cat = str(dest_cat).upper()

    score = 0.0
    if dep_closed or dest_closed:
        score += 0.6
    if dep_gs or dest_gs:
        score += 0.4
    score += min(0.3, (dep_delay + dest_delay) / 200.0)
    if dep_cat in ("IFR", "LIFR") or dest_cat in ("IFR", "LIFR"):
        score += 0.15

    if score >= 0.55:
        level = "high"
        confidence = min(0.95, 0.6 + score * 0.3)
    elif score >= 0.25:
        level = "medium"
        confidence = 0.55 + score * 0.2
    else:
        level = "low"
        confidence = 0.7 - score * 0.2

    return {
        "model_name": "rules_baseline_v1",
        "delay_risk": level,
        "confidence": round(confidence, 3),
        "feature_snapshot": features,
    }
