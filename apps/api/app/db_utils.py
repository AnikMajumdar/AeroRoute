"""Helpers around the supabase-py / postgrest query builders."""

from __future__ import annotations

from typing import Any


def fetch_one(query: Any) -> dict[str, Any] | None:
    """Run a select query and return its first row, or None when nothing matches.

    postgrest's ``maybe_single().execute()`` returns ``None`` (not a response object) when no row matches,
    which made callers crash on ``.data``; selecting with ``limit(1)`` avoids that quirk entirely.
    """
    rows = query.limit(1).execute().data or []
    return rows[0] if rows else None
