"""Lifecycle bookkeeping for ``route_requests`` rows: a calculation must always leave the 'processing' state."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# The API container is killed after 120 s on Modal, so a request that has been 'processing' for much longer
# than that can never complete (the process died before it could record a failure).
STALE_PROCESSING_AFTER = timedelta(minutes=10)
STALE_MESSAGE = "Calculation did not finish (the server stopped before it completed)"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def mark_request_failed(supabase: Any, route_request_id: str, message: str) -> None:
    """Record a failed calculation and drop its partially written result.

    Never raises: the caller is already handling an error and must be able to report it.
    """
    try:
        supabase.table("route_requests").update(
            {"status": "failed", "error_message": message, "updated_at": _now_iso()}
        ).eq("id", route_request_id).execute()
    except Exception:
        logger.exception("Could not mark route request %s as failed", route_request_id)

    try:
        # Segments, diversions and briefs cascade with the result row.
        supabase.table("route_results").delete().eq("route_request_id", route_request_id).execute()
    except Exception:
        logger.exception("Could not remove the partial result of route request %s", route_request_id)


def expire_stale_requests(supabase: Any, user_id: str, now: datetime | None = None) -> None:
    """Fail the user's calculations that have been 'processing' for too long (e.g. the container was killed)."""
    cutoff = ((now or datetime.now(timezone.utc)) - STALE_PROCESSING_AFTER).isoformat()
    try:
        stale = (
            supabase.table("route_requests")
            .select("id")
            .eq("user_id", user_id)
            .eq("status", "processing")
            .lte("created_at", cutoff)
            .execute()
        ).data or []
    except Exception:
        logger.warning("Could not look up stale route requests for %s", user_id, exc_info=True)
        return

    for row in stale:
        mark_request_failed(supabase, row["id"], STALE_MESSAGE)
