from __future__ import annotations

import logging
from typing import Any

from app.services.ml_features import (
    DATASET_VERSION,
    delay_label_from_features,
    ete_label_from_route,
    extract_delay_features,
    extract_ete_features,
)

logger = logging.getLogger(__name__)


def log_training_samples(
    supabase: Any,
    route_request_id: str,
    route_result_id: str,
    route_request: dict[str, Any],
    route_result: dict[str, Any],
    aircraft: dict[str, Any],
    segments: list[dict[str, Any]],
    diversions: list[dict[str, Any]],
) -> None:
    """Persist delay_risk and ete_prediction training samples after route calc."""
    enriched_request = {
        **route_request,
        "_aircraft_cruise_speed_kt": aircraft.get("cruise_speed_kt"),
        "_cruise_altitude_ft": aircraft.get("cruise_altitude_ft"),
    }
    delay_features = extract_delay_features(enriched_request, route_result, segments, diversions)
    ete_features = extract_ete_features(enriched_request, route_result, segments)
    live_snap = route_result.get("live_data_snapshot")
    if live_snap:
        from app.services.live_data.live_data_scoring import live_data_feature_flags

        delay_features.update(live_data_feature_flags(live_snap))
    delay_label = delay_label_from_features(delay_features)
    ete_label = ete_label_from_route(route_result)

    rows = [
        {
            "route_request_id": route_request_id,
            "route_result_id": route_result_id,
            "model_target": "delay_risk",
            "features": delay_features,
            "labels": delay_label,
            "label_source": delay_label["label_source"],
            "dataset_version": DATASET_VERSION,
        },
        {
            "route_request_id": route_request_id,
            "route_result_id": route_result_id,
            "model_target": "ete_prediction",
            "features": ete_features,
            "labels": ete_label,
            "label_source": ete_label["label_source"],
            "dataset_version": DATASET_VERSION,
        },
    ]
    for row in rows:
        try:
            supabase.table("model_training_samples").insert(row).execute()
        except Exception as exc:
            logger.debug("Training sample insert skipped (%s): %s", row["model_target"], exc)


def log_model_prediction(
    supabase: Any,
    route_result_id: str,
    model_name: str,
    model_version: str,
    model_target: str,
    prediction: dict[str, Any],
    features: dict[str, Any] | None = None,
    confidence: float | None = None,
) -> None:
    payload = {**prediction, "model_target": model_target}
    try:
        supabase.table("model_predictions").insert(
            {
                "route_result_id": route_result_id,
                "model_name": model_name,
                "model_version": model_version,
                "prediction": payload,
                "features": features,
                "confidence": confidence,
            }
        ).execute()
    except Exception as exc:
        logger.debug("Prediction insert skipped: %s", exc)
