#!/usr/bin/env python3
"""Train delay risk classifier from exported parquet or Supabase samples."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.services.ml_features import DELAY_FEATURE_COLUMNS  # noqa: E402

ARTIFACT_DIR = API_ROOT / "ml" / "artifacts"
DEFAULT_DATA = Path(__file__).resolve().parents[3] / "data" / "ml" / "delay_risk_training_v1.parquet"
MIN_SAMPLES = 300
MIN_CLASSES = 2
MIN_PER_CLASS = 30


def main() -> None:
    parser = argparse.ArgumentParser(description="Train delay risk model")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--min-samples", type=int, default=MIN_SAMPLES)
    args = parser.parse_args()

    if not args.data.exists():
        print(f"No training data at {args.data}. Run npm run ml:export-delay first.")
        sys.exit(1)

    import joblib
    import pandas as pd
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
    from sklearn.model_selection import train_test_split

    df = pd.read_parquet(args.data)
    class_counts = df["delay_risk"].astype(str).value_counts()
    print(f"Samples: {len(df)}, classes: {class_counts.to_dict()}")

    if len(df) < args.min_samples:
        print(
            f"Need at least {args.min_samples} samples for a stable classifier "
            f"(have {len(df)}). Generate more routes:\n"
            f"  npm run ml:generate -- --max-samples 100 --delay 2"
        )
        sys.exit(1)

    if len(class_counts) < MIN_CLASSES:
        print(
            f"Need at least {MIN_CLASSES} delay_risk classes in training data "
            f"(have only: {list(class_counts.index)}).\n"
            f"Re-export after label update: npm run ml:export-delay\n"
            f"Or generate more varied routes: npm run ml:generate -- --max-samples 100 --delay 2"
        )
        sys.exit(1)

    small_classes = class_counts[class_counts < MIN_PER_CLASS]
    if len(small_classes) > 0:
        print(
            f"Each class needs at least {MIN_PER_CLASS} samples. Under-represented: {small_classes.to_dict()}\n"
            f"Generate more routes: npm run ml:generate -- --max-samples 1000 --delay 1"
        )
        sys.exit(1)

    X = df[DELAY_FEATURE_COLUMNS].fillna(0).astype(float)
    y = df["delay_risk"].astype(str)

    stratify = y if y.nunique() > 1 and y.value_counts().min() >= 2 else None
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=stratify
    )

    model = LogisticRegression(max_iter=1000)
    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)

    acc = accuracy_score(y_test, y_pred)
    f1 = f1_score(y_test, y_pred, average="macro", zero_division=0)
    labels = sorted(y.unique())
    cm = confusion_matrix(y_test, y_pred, labels=labels)

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, ARTIFACT_DIR / "delay_risk_model_v1.joblib")
    metadata = {
        "model_name": "delay_risk_classifier_v1",
        "model_version": "v1",
        "feature_columns": DELAY_FEATURE_COLUMNS,
        "accuracy": round(acc, 4),
        "macro_f1": round(f1, 4),
        "confusion_matrix": cm.tolist(),
        "classes": list(model.classes_),
        "train_samples": len(X_train),
        "test_samples": len(X_test),
        "classification_report": classification_report(y_test, y_pred, output_dict=True, zero_division=0),
    }
    (ARTIFACT_DIR / "delay_risk_model_v1_metadata.json").write_text(json.dumps(metadata, indent=2))
    print(f"Delay model saved. accuracy={acc:.3f} macro_f1={f1:.3f}")


if __name__ == "__main__":
    main()
