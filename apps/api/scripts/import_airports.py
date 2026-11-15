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
import re
import sys
from pathlib import Path
from typing import Iterable

# Add apps/api to path
API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.config import settings  # noqa: E402
from app.db import get_supabase  # noqa: E402

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data" / "raw"
AIRPORTS_CSV = DATA_DIR / "airports.csv"
RUNWAYS_CSV = DATA_DIR / "runways.csv"

ALLOWED_TYPES = {"small_airport", "medium_airport", "large_airport"}
BATCH_SIZE = 500

# The runway surface in the OurAirports data is free text with hundreds of spellings ("ASP", "ASPH-G",
# "Concrete", "PER", "TURF-F", "WATER", ...). A runway counts as paved only when one of its tokens is a known
# pavement spelling and none is an unpaved/water one (so "ASPH-TURF" is not paved). Unknown surfaces are not
# counted: the longest runway is used to decide whether an airport is suitable, so doubt must not inflate it.
HARD_SURFACE_TOKENS = frozenset(
    {
        "ASP", "ASPH", "ASPHALT", "ASPHAULT", "ASHPHALT", "ASHPALT",
        "CON", "CONC", "CONCRETE",
        "PEM", "PER", "PAV", "PAVED", "PAVING", "PAVEMENT",
        "BIT", "BITUM", "BITUMEN", "BITUMINOUS",
        "TAR", "TARMAC", "TARRED", "MAC", "MACADAM",
    }
)
SOFT_SURFACE_TOKENS = frozenset(
    {
        "TURF", "GRASS", "GRS", "SOD", "GRVL", "GRAVEL", "GVL", "GRV", "DIRT", "EARTH", "GRE", "SOIL", "MUD",
        "CLAY", "SAND", "ROCK", "CORAL", "COR", "SNOW", "ICE", "WATER", "WAT",
    }
)


def is_hard_surface(surface: str | None) -> bool:
    """True when a runway surface is positively identified as paved."""
    tokens = {token for token in re.split(r"[^A-Z0-9]+", (surface or "").upper()) if token}
    return bool(tokens & HARD_SURFACE_TOKENS) and not (tokens & SOFT_SURFACE_TOKENS)


def _is_closed(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes"}


def longest_runways_from_rows(rows: Iterable[dict[str, str]]) -> dict[str, int]:
    """Map airport ident -> length (ft) of its longest open, paved runway.

    Closed runways, water lanes and turf/gravel/dirt strips are ignored; airports without any such runway are
    absent from the result (their ``longest_runway_ft`` is stored as NULL).
    """
    longest: dict[str, int] = {}
    for row in rows:
        ident = (row.get("airport_ident") or "").strip()
        if not ident or _is_closed(row.get("closed")) or not is_hard_surface(row.get("surface")):
            continue
        try:
            length = int(float(row.get("length_ft") or 0))
        except (ValueError, OverflowError):
            length = 0
        if length > longest.get(ident, 0):
            longest[ident] = length
    return longest


def load_longest_runways(path: Path | None = None) -> dict[str, int]:
    """Map airport ident -> longest open, paved runway length in feet, read from runways.csv."""
    path = path or RUNWAYS_CSV
    if not path.exists():
        logger.warning("runways.csv not found at %s", path)
        return {}

    with path.open(newline="", encoding="utf-8") as f:
        longest = longest_runways_from_rows(csv.DictReader(f))
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
    logging.basicConfig(level=logging.INFO)
    import_airports()
