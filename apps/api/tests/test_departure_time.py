from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.schemas import RouteCalculateRequest


def _base_payload(**overrides):
    data = {
        "departure_airport_id": "00000000-0000-0000-0000-000000000001",
        "destination_airport_id": "00000000-0000-0000-0000-000000000002",
        "aircraft_profile_id": "00000000-0000-0000-0000-000000000003",
        "departure_time": datetime.now(timezone.utc).isoformat(),
        "fuel_price_usd_per_gal": 6.5,
    }
    data.update(overrides)
    return data


class TestDepartureTimeValidation:
    def test_current_time_is_allowed(self):
        req = RouteCalculateRequest(**_base_payload())
        assert req.departure_time.tzinfo is not None

    def test_two_minutes_ago_is_allowed(self):
        past = datetime.now(timezone.utc) - timedelta(minutes=2)
        req = RouteCalculateRequest(**_base_payload(departure_time=past.isoformat()))
        assert req.departure_time == past

    def test_ten_minutes_ago_is_rejected(self):
        past = datetime.now(timezone.utc) - timedelta(minutes=10)
        with pytest.raises(ValidationError, match="past"):
            RouteCalculateRequest(**_base_payload(departure_time=past.isoformat()))
