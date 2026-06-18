from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings
from app.db import get_supabase
from app.utils.datetime_parse import parse_iso_datetime, to_supabase_timestamptz

logger = logging.getLogger(__name__)


class CacheService:
    """Simple Supabase-backed cache for external API responses."""

    def get(self, key: str) -> Any | None:
        try:
            supabase = get_supabase()
            result = (
                supabase.table("api_cache")
                .select("cache_value, expires_at")
                .eq("cache_key", key)
                .maybe_single()
                .execute()
            )
            if result is None or not result.data:
                return None
            expires_at = parse_iso_datetime(result.data["expires_at"])
            if expires_at is None:
                return None
            if expires_at < datetime.now(timezone.utc):
                self.delete(key)
                return None
            return result.data["cache_value"]
        except Exception as exc:
            logger.warning("Cache get failed for %s: %s", key, exc)
            return None

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        try:
            supabase = get_supabase()
            expires_dt = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
            supabase.table("api_cache").upsert(
                {
                    "cache_key": key,
                    "cache_value": value,
                    "expires_at": to_supabase_timestamptz(expires_dt),
                }
            ).execute()
        except Exception as exc:
            logger.warning("Cache set failed for %s: %s", key, exc)

    def delete(self, key: str) -> None:
        try:
            get_supabase().table("api_cache").delete().eq("cache_key", key).execute()
        except Exception as exc:
            logger.warning("Cache delete failed for %s: %s", key, exc)


cache_service = CacheService()
