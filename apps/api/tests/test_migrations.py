"""SQL migrations must be valid PostgreSQL and follow the numbering convention."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pglast = pytest.importorskip("pglast", reason="pglast is a dev dependency (requirements-dev.txt)")

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "supabase" / "migrations"
MIGRATION_FILES = sorted(MIGRATIONS_DIR.glob("*.sql"))


def test_migrations_exist():
    assert MIGRATION_FILES, f"no migrations found in {MIGRATIONS_DIR}"


@pytest.mark.parametrize("path", MIGRATION_FILES, ids=lambda p: p.name)
def test_migration_is_valid_postgresql(path: Path):
    sql = path.read_text()
    pglast.parse_sql(sql)
    if re.search(r"LANGUAGE\s+plpgsql", sql, re.IGNORECASE):
        pglast.parse_plpgsql(sql)


def test_migration_numbers_are_unique_and_contiguous():
    numbers = []
    for path in MIGRATION_FILES:
        match = re.fullmatch(r"(\d{3})_[a-z0-9_]+\.sql", path.name)
        assert match, f"migration name must look like 009_description.sql: {path.name}"
        numbers.append(int(match.group(1)))
    assert numbers == list(range(1, len(numbers) + 1)), f"migration numbers are not contiguous: {numbers}"
