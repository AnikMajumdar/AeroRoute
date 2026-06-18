from __future__ import annotations

import re
from datetime import datetime, timezone


def parse_iso_datetime(value: datetime | str | None) -> datetime | None:
    """Parse ISO timestamps from Supabase/Postgres (Python 3.9-safe fractional seconds)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    text = str(value).strip().replace("Z", "+00:00")
    # Python 3.9 fromisoformat requires exactly 0, 3, or 6 fractional digits
    match = re.match(
        r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})(?:\.(\d+))?([+-]\d{2}:\d{2})?$",
        text,
    )
    if match:
        base, frac, tz = match.groups()
        if frac is not None:
            micro = (frac + "000000")[:6]
            text = f"{base}.{micro}{tz or '+00:00'}"
        elif tz is None:
            text = f"{base}+00:00"

    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def to_supabase_timestamptz(dt: datetime) -> str:
    """Serialize datetime for Postgres timestamptz inserts."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
