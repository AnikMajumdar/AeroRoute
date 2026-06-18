#!/usr/bin/env python3
"""Export ete_prediction training samples to parquet."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from dotenv import load_dotenv

load_dotenv(ROOT / "apps" / "api" / ".env")

from app.services.ml_features import ETE_FEATURE_COLUMNS  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "ml" / "ete_training_v1.parquet")
    parser.add_argument("--dataset-version", default="v1")
    args = parser.parse_args()

    from supabase import create_client

    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        print("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY")
        sys.exit(1)

    sb = create_client(url, key)
    rows = (
        sb.table("model_training_samples")
        .select("*")
        .eq("model_target", "ete_prediction")
        .eq("dataset_version", args.dataset_version)
        .execute()
    ).data or []

    if not rows:
        print("No ete_prediction training samples found.")
        sys.exit(1)

    import pandas as pd

    records = []
    for row in rows:
        feat = row.get("features") or {}
        label = row.get("labels") or {}
        rec = {col: feat.get(col, 0) for col in ETE_FEATURE_COLUMNS}
        rec["ete_minutes"] = label.get("ete_minutes", 0)
        rec["route_result_id"] = row.get("route_result_id")
        records.append(rec)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(records).to_parquet(args.output, index=False)
    print(f"Exported {len(records)} rows to {args.output}")


if __name__ == "__main__":
    main()
