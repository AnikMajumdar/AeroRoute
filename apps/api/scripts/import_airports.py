"""
Import OurAirports airports.csv and runways.csv into Supabase.

Usage:
    cd apps/api && python -m scripts.import_airports

Expects CSV files at:
    data/raw/airports.csv
    data/raw/runways.csv

Download from: https://ourairports.com/data/
"""

from __future__ import annotations

import csv
import logging
import sys
from collections import defaultdict
from pathlib import Path

# Add apps/api to path
API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.config import settings  # noqa: E402
from app.db import get_supabase  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data" / "raw"
AIRPORTS_CSV = DATA_DIR / "airports.csv"
RUNWAYS_CSV = DATA_DIR / "runways.csv"

ALLOWED_TYPES = {"small_airport", "medium_airport", "large_airport"}
BATCH_SIZE = 500


def load_longest_runways() -> dict[str, int]:
    """Map airport ident -> longest runway length in feet."""
    longest: dict[str, int] = defaultdict(int)
    if not RUNWAYS_CSV.exists():
        logger.warning("runways.csv not found at %s", RUNWAYS_CSV)
        return longest

    with RUNWAYS_CSV.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ident = row.get("airport_ident", "").strip()
            try:
                length = int(float(row.get("length_ft") or 0))
            except ValueError:
                length = 0
            if ident and length > longest[ident]:
                longest[ident] = length
    logger.info("Loaded runway data for %d airports", len(longest))
    return longest


def parse_airport_row(row: dict[str, str], longest_runways: dict[str, int]) -> dict | None:
    airport_type = row.get("type", "").strip()
    if airport_type not in ALLOWED_TYPES:
        return None

    ident = row.get("ident", "").strip()
    if not ident:
        return None

    try:
        lat = float(row.get("latitude_deg", 0))
        lon = float(row.get("longitude_deg", 0))
    except ValueError:
        return None

    if lat == 0 and lon == 0:
        return None

    elevation = row.get("elevation_ft", "").strip()
    try:
        elevation_ft = int(float(elevation)) if elevation else None
    except ValueError:
        elevation_ft = None

    return {
        "ident": ident,
        "icao_code": row.get("icao_code", "").strip() or None,
        "iata_code": row.get("iata_code", "").strip() or None,
        "local_code": row.get("local_code", "").strip() or None,
        "name": row.get("name", ident).strip(),
        "municipality": row.get("municipality", "").strip() or None,
        "latitude": lat,
        "longitude": lon,
        "elevation_ft": elevation_ft,
        "airport_type": airport_type,
        "longest_runway_ft": longest_runways.get(ident) or None,
    }


def import_airports() -> None:
    if not settings.supabase_url or not settings.supabase_service_role_key:
        logger.error("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in apps/api/.env")
        sys.exit(1)

    if "your-project" in settings.supabase_url or "your-service-role" in settings.supabase_service_role_key:
        logger.error(
            "apps/api/.env still has placeholder values. "
            "Copy your real Project URL and service_role key from Supabase → Project Settings → API"
        )
        sys.exit(1)

    if not settings.supabase_url.startswith("https://") or not settings.supabase_url.endswith(".supabase.co"):
        logger.error("SUPABASE_URL must look like https://xxxxxxxx.supabase.co (got: %s)", settings.supabase_url)
        sys.exit(1)

    logger.info("Connecting to Supabase at %s", settings.supabase_url)

    if not AIRPORTS_CSV.exists():
        logger.error(
            "airports.csv not found. Download from https://ourairports.com/data/ "
            "and place at %s",
            AIRPORTS_CSV,
        )
        sys.exit(1)

    longest_runways = load_longest_runways()
    supabase = get_supabase()

    airports: list[dict] = []
    with AIRPORTS_CSV.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            parsed = parse_airport_row(row, longest_runways)
            if parsed:
                airports.append(parsed)

    logger.info("Importing %d airports", len(airports))

    for i in range(0, len(airports), BATCH_SIZE):
        batch = airports[i : i + BATCH_SIZE]
        supabase.table("airports").upsert(batch, on_conflict="ident").execute()
        logger.info("Imported batch %d-%d", i + 1, min(i + BATCH_SIZE, len(airports)))

    logger.info("Import complete: %d airports", len(airports))


if __name__ == "__main__":
    import_airports()
