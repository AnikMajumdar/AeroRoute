"""Airport autocomplete helpers: safe construction of the PostgREST text-search filter."""

from __future__ import annotations

import re

AIRPORT_SEARCH_COLUMNS = ("icao_code", "iata_code", "ident", "name")
MAX_SEARCH_TERM_LENGTH = 50

# Letters, digits, space and the punctuation found in airport names (St. Louis, O'Hare, Wilkes-Barre).
# Everything else - including PostgREST filter syntax (, ( ) " \ * and the LIKE wildcards % _ - is dropped.
_DISALLOWED = re.compile(r"[^A-Za-z0-9 .'\-]")


def sanitize_search_term(raw: str) -> str:
    """Normalise user input to a safe, upper-cased search term (possibly empty)."""
    cleaned = _DISALLOWED.sub("", raw)
    return " ".join(cleaned.split()).upper()[:MAX_SEARCH_TERM_LENGTH]


def build_search_filter(term: str) -> str:
    """Build the value of PostgREST's ``or`` filter for an already sanitised, non-empty term.

    Values are double-quoted so '.' inside names cannot be mistaken for the column.operator.value separators.
    """
    pattern = f'"%{term}%"'
    return ",".join(f"{column}.ilike.{pattern}" for column in AIRPORT_SEARCH_COLUMNS)
