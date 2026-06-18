"""Shared planning constraints for forecast and airport eligibility."""

FORECAST_HORIZON_DAYS = 7

# US ICAO stations with routine METAR/TAF (medium & large fields in OurAirports).
WEATHER_ELIGIBLE_TYPES = ("medium_airport", "large_airport")


def is_weather_eligible_airport(row: dict) -> bool:
    icao = (row.get("icao_code") or "").strip().upper()
    if len(icao) != 4 or not icao.startswith("K"):
        return False
    return row.get("airport_type") in WEATHER_ELIGIBLE_TYPES
