from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.services.faa_nas import INTEGRATION_DISABLED_MESSAGE, faa_nas_client
from app.services.live_data.types import DataSourceMeta, ProviderResult

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FaaStatusProvider:
    """Wraps disabled FAA NAS stub with unified provider metadata."""

    source_name = "FAA NAS Status (disabled)"

    async def get_airport_status(self, icao: str, supabase: Any | None = None) -> ProviderResult:
        fetched_at = _now_iso()
        data = await faa_nas_client.get_airport_status(icao, supabase=supabase)
        return ProviderResult(
            data=data,
            meta=DataSourceMeta(
                source_name=self.source_name,
                source_url=None,
                fetched_at=fetched_at,
                available=False,
                error=INTEGRATION_DISABLED_MESSAGE,
            ),
        )


faa_status_provider = FaaStatusProvider()
