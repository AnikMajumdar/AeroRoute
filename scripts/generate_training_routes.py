#!/usr/bin/env python3
"""
Generate route calculations for ML training data.

Respects API rate limits with delays and uses dry-run mode to skip external calls.
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from dotenv import load_dotenv

load_dotenv(ROOT / "apps" / "api" / ".env")

TRAINING_AIRPORTS = [
    "KSNA", "KLAX", "KLGB", "KBUR", "KONT", "KLAS", "KPHX", "KSAN", "KSFO", "KSJC",
    "KOAK", "KSMF", "KRNO", "KFAT", "KPDX", "KSEA", "KSLC", "KDEN", "KABQ", "KTUS",
    "KELP", "KDFW", "KIAH", "KORD", "KATL", "KJFK", "KBOS", "KMIA",
]

ROUTE_PREFERENCES = ["balanced", "fastest", "fuel_saver", "weather_cautious"]
FUEL_PRICES = [5.5, 6.0, 6.5, 7.0]


async def _resolve_airports(supabase, icaos: list[str]) -> dict[str, dict]:
    result = {}
    for icao in icaos:
        row = (
            supabase.table("airports")
            .select("*")
            .eq("icao_code", icao)
            .maybe_single()
            .execute()
        )
        if row.data:
            result[icao] = row.data
    return result


async def generate(
    max_samples: int,
    dry_run: bool,
    delay_seconds: float,
    user_id: str,
) -> None:
    from supabase import create_client

    from app.services.route_calculator import route_calculator
    from app.utils.datetime_parse import to_supabase_timestamptz

    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        print("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY")
        sys.exit(1)

    sb = create_client(url, key)
    airports = await _resolve_airports(sb, TRAINING_AIRPORTS)
    if len(airports) < 2:
        print("Import airports first: npm run import:airports")
        sys.exit(1)

    aircraft_rows = sb.table("aircraft_profiles").select("*").eq("is_preset", True).execute().data or []
    if not aircraft_rows:
        print("No aircraft presets found.")
        sys.exit(1)

    pairs = list(itertools.combinations(list(airports.keys()), 2))
    random.shuffle(pairs)
    count = 0

    for dep_icao, dest_icao in pairs:
        if count >= max_samples:
            break
        for aircraft in aircraft_rows:
            if count >= max_samples:
                break
            pref = random.choice(ROUTE_PREFERENCES)
            fuel_price = random.choice(FUEL_PRICES)
            dep_time = datetime.now(timezone.utc) + timedelta(hours=random.randint(1, 48))

            dep = airports[dep_icao]
            dest = airports[dest_icao]

            if dry_run:
                print(f"[dry-run] {dep_icao}->{dest_icao} {aircraft['name']} {pref}")
                count += 1
                continue

            try:
                calc = await route_calculator.calculate(
                    departure=dep,
                    destination=dest,
                    aircraft=aircraft,
                    fuel_price=fuel_price,
                    supabase=sb,
                    departure_time=dep_time,
                    route_preference=pref,
                )
                primary = calc["primary"]
                req_row = (
                    sb.table("route_requests")
                    .insert(
                        {
                            "user_id": user_id,
                            "departure_airport_id": dep["id"],
                            "destination_airport_id": dest["id"],
                            "aircraft_profile_id": aircraft["id"],
                            "departure_time": to_supabase_timestamptz(dep_time),
                            "fuel_price_usd_per_gal": fuel_price,
                            "route_preference": pref,
                            "status": "completed",
                        }
                    )
                    .execute()
                )
                req_id = req_row.data[0]["id"]
                res_row = (
                    sb.table("route_results")
                    .insert(
                        {
                            "route_request_id": req_id,
                            "primary_distance_nm": primary.distance_nm,
                            "primary_ete_minutes": primary.ete_minutes,
                            "primary_fuel_burn_gal": primary.fuel_burn_gal,
                            "primary_fuel_cost_usd": primary.fuel_cost_usd,
                            "primary_score": primary.score,
                            "primary_path": [{"lat": w[0], "lon": w[1]} for w in primary.waypoints],
                            "score_breakdown": primary.score_breakdown,
                            "normalized_score_breakdown": primary.score_breakdown,
                            "fuel_breakdown": primary.fuel_breakdown,
                            "weather_checkpoints": calc.get("weather_checkpoints") or [],
                            "route_candidates": calc.get("candidate_summaries") or [],
                            "wind_data_quality": calc.get("wind_data_quality"),
                            "warnings": calc["warnings"],
                            "departure_weather": calc["departure_weather"],
                            "destination_weather": calc["destination_weather"],
                        }
                    )
                    .execute()
                )
                result_id = res_row.data[0]["id"]
                from app.services.ml_logging import log_training_samples

                log_training_samples(
                    sb,
                    req_id,
                    result_id,
                    req_row.data[0],
                    {**res_row.data[0], "normalized_score_breakdown": primary.score_breakdown},
                    aircraft,
                    primary.segments,
                    calc["diversion_airports"],
                )
                print(
                    f"[{count+1}] {dep_icao}->{dest_icao} score={primary.score:.0f} "
                    f"ete={primary.ete_minutes:.0f}min id={result_id}"
                )
                count += 1
            except Exception as exc:
                print(f"Failed {dep_icao}->{dest_icao}: {exc}")
            await asyncio.sleep(delay_seconds)

    print(f"Done. Generated {count} samples.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate ML training routes")
    parser.add_argument("--max-samples", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--delay", type=float, default=2.0, help="Seconds between API calls")
    parser.add_argument("--user-id", default="ml-training-generator")
    args = parser.parse_args()
    asyncio.run(generate(args.max_samples, args.dry_run, args.delay, args.user_id))


if __name__ == "__main__":
    main()
