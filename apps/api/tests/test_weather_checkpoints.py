import pytest

from app.services.weather_checkpoints import (
    fetch_checkpoint_weather,
    normalize_flight_category,
)


class TestNormalizeFlightCategory:
    def test_none_becomes_unknown(self):
        assert normalize_flight_category(None) == "UNKNOWN"

    def test_null_string_becomes_unknown(self):
        assert normalize_flight_category("") == "UNKNOWN"

    def test_uppercases_vfr(self):
        assert normalize_flight_category("vfr") == "VFR"


@pytest.mark.asyncio
async def test_fetch_checkpoint_weather_handles_null_category(monkeypatch):
    async def fake_metar(_icao):
        return {"flight_category": None, "raw": "TEST"}

    monkeypatch.setattr(
        "app.services.weather_checkpoints.aviation_weather_client.get_metar",
        fake_metar,
    )
    checkpoints = [
        {
            "id": "1",
            "icao_code": "KORD",
            "name": "O'Hare",
            "latitude": 41.9,
            "longitude": -87.9,
        }
    ]
    results = await fetch_checkpoint_weather(checkpoints)
    assert results[0]["flight_category"] == "UNKNOWN"
    assert results[0]["weather_penalty"] == 10
