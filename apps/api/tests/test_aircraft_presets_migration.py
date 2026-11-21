"""Migration 010 must keep the preset rows identical to the canonical Python data (the presets endpoint is read-only)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.data.aircraft_presets import AIRCRAFT_PRESETS

MIGRATION = Path(__file__).resolve().parents[3] / "supabase" / "migrations" / "010_aircraft_presets_usable_fuel.sql"
UPDATE = re.compile(
    r"UPDATE aircraft_profiles\s+SET\s+(?P<assignments>.*?)\s+WHERE name = '(?P<name>[^']+)' AND is_preset = TRUE;",
    re.DOTALL,
)


def _synced_rows() -> dict[str, dict[str, float]]:
    rows: dict[str, dict[str, float]] = {}
    for match in UPDATE.finditer(MIGRATION.read_text()):
        assert match["name"] not in rows, f"{match['name']} is updated twice"
        values = {}
        for assignment in match["assignments"].split(","):
            column, value = (part.strip() for part in assignment.split("="))
            values[column] = float(value)
        rows[match["name"]] = values
    return rows


def test_every_preset_is_synced_exactly_once():
    assert sorted(_synced_rows()) == sorted(spec["name"] for spec in AIRCRAFT_PRESETS)


@pytest.mark.parametrize("spec", AIRCRAFT_PRESETS, ids=lambda s: s["name"])
def test_synced_values_match_the_python_data(spec):
    synced = _synced_rows()[spec["name"]]
    expected = {key: value for key, value in spec.items() if key not in ("name", "notes")}
    assert set(synced) == set(expected), "every preset column must be synced"
    for column, value in synced.items():
        assert value == pytest.approx(expected[column]), column


def test_capacity_column_is_added_idempotently_with_a_positive_check():
    sql = MIGRATION.read_text()
    assert "ADD COLUMN IF NOT EXISTS usable_fuel_gal" in sql
    assert "usable_fuel_gal IS NULL OR usable_fuel_gal > 0" in sql
