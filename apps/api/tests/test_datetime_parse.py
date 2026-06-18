from datetime import datetime, timezone

from app.utils.datetime_parse import parse_iso_datetime, to_supabase_timestamptz


def test_parse_supabase_fractional_seconds():
    dt = parse_iso_datetime("2026-06-18T12:53:42.66051+00:00")
    assert dt is not None
    assert dt.year == 2026
    assert dt.microsecond == 660510


def test_to_supabase_timestamptz_six_digits():
    dt = datetime(2026, 6, 18, 12, 53, 42, 660510, tzinfo=timezone.utc)
    assert to_supabase_timestamptz(dt).endswith(".660510Z")
