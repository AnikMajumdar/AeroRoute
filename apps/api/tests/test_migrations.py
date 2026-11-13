"""SQL migrations must be valid PostgreSQL, follow the numbering convention and keep RLS on every table."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pglast = pytest.importorskip("pglast", reason="pglast is a dev dependency (requirements-dev.txt)")
from pglast import ast, enums  # noqa: E402  (needs the importorskip above)

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "supabase" / "migrations"
MIGRATION_FILES = sorted(MIGRATIONS_DIR.glob("*.sql"))


def _statements():
    for path in MIGRATION_FILES:
        for raw in pglast.parse_sql(path.read_text()):
            yield path, raw.stmt


def _is_constant_true(expr) -> bool:
    return isinstance(expr, ast.A_Const) and isinstance(expr.val, ast.Boolean) and expr.val.boolval is True


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
        assert match, f"migration name must look like NNN_description.sql: {path.name}"
        numbers.append(int(match.group(1)))
    assert numbers == list(range(1, len(numbers) + 1)), f"migration numbers are not contiguous: {numbers}"


def test_every_table_has_row_level_security_enabled():
    """Tables without RLS are readable and writable through PostgREST with just the public anon key."""
    created: set[str] = set()
    rls_enabled: set[str] = set()
    for _path, node in _statements():
        if isinstance(node, ast.CreateStmt):
            created.add(node.relation.relname)
        elif isinstance(node, ast.AlterTableStmt) and any(
            cmd.subtype == enums.AlterTableType.AT_EnableRowSecurity for cmd in node.cmds
        ):
            rls_enabled.add(node.relation.relname)
    assert created, "no CREATE TABLE statements found"
    missing = sorted(created - rls_enabled)
    assert not missing, f"tables without ENABLE ROW LEVEL SECURITY: {missing}"


def test_only_select_policies_may_allow_everyone():
    """A constant-true policy is fine for public reference data (SELECT) but never for writes."""
    offenders = [
        f"{path.name}: {node.policy_name}"
        for path, node in _statements()
        if isinstance(node, ast.CreatePolicyStmt)
        and node.cmd_name != "select"
        and (_is_constant_true(node.qual) or _is_constant_true(node.with_check))
    ]
    assert not offenders, f"world-writable policies: {offenders}"


def test_user_owned_tables_are_never_readable_by_everyone():
    """Tables holding per-user rows must never get a constant-true policy."""
    user_tables = {"aircraft_profiles", "route_requests", "route_results", "route_briefs", "route_segments", "diversion_airports"}
    constant_true_on = {
        node.table.relname
        for _path, node in _statements()
        if isinstance(node, ast.CreatePolicyStmt) and _is_constant_true(node.qual)
    }
    assert not (user_tables & constant_true_on), f"user data exposed to everyone: {sorted(user_tables & constant_true_on)}"
