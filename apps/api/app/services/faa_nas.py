from __future__ import annotations

import logging
from typing import Any

from app.services.faa_nas_parser import parse_faa_airport_status

logger = logging.getLogger(__name__)

# FAA NAS / TFR / NOTAM integrations are disabled in this build (no external API calls).
INTEGRATION_DISABLED_MESSAGE = (
    "FAA live data integration is not connected. "
    "Verify delays, closures, TFRs, and NOTAMs through official FAA sources."
)


class FAANasStatusClient:
    """Stub client — FAA NAS status fetching disabled."""

    async def get_airport_status(self, icao: str, supabase: Any | None = None) -> dict[str, Any]:
        if not icao:
            return parse_faa_airport_status("", None).to_dict()
        result = parse_faa_airport_status(icao.upper(), None).to_dict()
        result["integration_disabled"] = True
        result["warnings"] = [INTEGRATION_DISABLED_MESSAGE]
        logger.debug("FAA NAS status disabled for %s", icao)
        return result


faa_nas_client = FAANasStatusClient()
