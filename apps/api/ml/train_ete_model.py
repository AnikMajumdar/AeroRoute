#!/usr/bin/env python3
"""Train ETE regressor from exported parquet."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.services.ml_features import ETE_FEATURE_COLUMNS  # noqa: E402

ARTIFACT_DIR = API_ROOT / "ml" / "artifacts"
DEFAULT_DATA = Path(__file__).resolve().parents[3] / "data" / "ml" / "ete_training_v1.parquet"


def main() -> None:
    parser = argparse.ArgumentParser(description="Train ETE model")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    args = parser.parse_args()

    if not args.data.exists():
        print(f"No training data at {args.data}. Run scripts/export_ete_dataset.py first.")
        sys.exit(1)

    import joblib
    import numpy as np
    import pandas as pd
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.metrics import mean_absolute_error, mean_squared_error
    from sklearn.model_selection import train_test_split

    df = pd.read_parquet(args.data)
    X = df[ETE_FEATURE_COLUMNS].fillna(0).astype(float)
    y = df["ete_minutes"].astype(float)

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    model = RandomForestRegressor(n_estimators=100, random_state=42, max_depth=12)
    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)

    mae = mean_absolute_error(y_test, y_pred)
    rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))
    mape = float(np.mean(np.abs((y_test - y_pred) / y_test.clip(lower=1))) * 100)

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, ARTIFACT_DIR / "ete_model_v1.joblib")
    metadata = {
        "model_name": "ete_regressor_v1",
        "model_version": "v1",
        "feature_columns": ETE_FEATURE_COLUMNS,
        "mae_minutes": round(mae, 2),
        "rmse_minutes": round(rmse, 2),
        "mape_pct": round(mape, 2),
        "train_samples": len(X_train),
        "test_samples": len(X_test),
        "label_source": "deterministic_engine_v1",
        "is_surrogate": True,
    }
    (ARTIFACT_DIR / "ete_model_v1_metadata.json").write_text(json.dumps(metadata, indent=2))
    print(f"ETE model saved. MAE={mae:.1f} min RMSE={rmse:.1f} min MAPE={mape:.1f}%")


if __name__ == "__main__":
    main()
