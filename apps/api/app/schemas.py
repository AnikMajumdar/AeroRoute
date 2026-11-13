from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.planning_constraints import FORECAST_HORIZON_DAYS

RoutePreference = Literal["balanced", "fastest", "fuel_saver", "weather_cautious"]

UUID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


class AirportSummary(BaseModel):
    id: str
    ident: str
    icao_code: str | None = None
    iata_code: str | None = None
    name: str
    municipality: str | None = None
    latitude: float
    longitude: float
    airport_type: str
    longest_runway_ft: int | None = None


class AircraftProfile(BaseModel):
    id: str
    name: str
    cruise_speed_kt: int
    fuel_burn_gph: float
    cruise_altitude_ft: int | None = None
    climb_fuel_gal: float | None = None
    climb_time_min: float | None = None
    descent_time_min: float | None = None
    reserve_fuel_min: float | None = None
    min_runway_ft: int | None = None
    is_preset: bool = False
    user_id: str | None = None


class AircraftCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    cruise_speed_kt: int = Field(gt=0, le=600)
    fuel_burn_gph: float = Field(gt=0, le=500)


class RouteCalculateRequest(BaseModel):
    departure_airport_id: str = Field(pattern=UUID_PATTERN)
    destination_airport_id: str = Field(pattern=UUID_PATTERN)
    aircraft_profile_id: str = Field(pattern=UUID_PATTERN)
    departure_time: datetime
    fuel_price_usd_per_gal: float = Field(gt=0, le=50)
    route_preference: RoutePreference = "balanced"

    @field_validator("departure_time")
    @classmethod
    def normalize_departure_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_departure_window(self) -> "RouteCalculateRequest":
        now = datetime.now(timezone.utc)
        if self.departure_time < now - timedelta(minutes=5):
            raise ValueError("Departure time cannot be in the past")
        latest = now + timedelta(days=FORECAST_HORIZON_DAYS)
        if self.departure_time > latest:
            raise ValueError(
                f"Departure must be within {FORECAST_HORIZON_DAYS} days (forecast data limit)"
            )
        return self


class RouteSegmentDetail(BaseModel):
    segment_index: int
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    distance_nm: float
    bearing_deg: float
    wind_speed_kt: float | None = None
    wind_direction_deg: float | None = None
    headwind_component_kt: float | None = None
    tailwind_component_kt: float | None = None
    wind_altitude_ft: int | None = None
    wind_pressure_level_hpa: int | None = None
    wind_source: str | None = None
    groundspeed_kt: float | None = None
    ete_minutes: float | None = None


class DiversionAirportDetail(BaseModel):
    airport: AirportSummary
    distance_from_route_nm: float
    rank: int


class FuelBreakdownDetail(BaseModel):
    climb_fuel_gal: float
    cruise_fuel_gal: float
    descent_fuel_gal: float
    trip_fuel_gal: float
    reserve_fuel_gal: float
    total_required_gal: float
    usable_capacity_gal: float | None = None
    fuel_remaining_gal: float | None = None
    fuel_margin_gal: float | None = None
    warnings: list[str] = []


class NormalizedScoreBreakdown(BaseModel):
    preference: str
    composite_score: float
    component_scores: dict[str, float]
    weights: dict[str, float]
    legacy: dict[str, float] | None = None
    total: float | None = None


class WeatherCheckpointDetail(BaseModel):
    airport_id: str | None = None
    icao: str | None = None
    name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    flight_category: str | None = None
    metar: dict[str, Any] | None = None
    weather_penalty: float | None = None


class RouteCandidateSummary(BaseModel):
    name: str
    distance_nm: float
    ete_minutes: float
    fuel_burn_gal: float
    score: float
    selected: bool = False


class RouteResultDetail(BaseModel):
    id: str
    route_request_id: str
    status: str
    primary_distance_nm: float
    primary_ete_minutes: float
    primary_fuel_burn_gal: float
    primary_fuel_cost_usd: float
    primary_score: float
    primary_path: list[dict[str, float]]
    alternate_distance_nm: float | None = None
    alternate_ete_minutes: float | None = None
    alternate_fuel_burn_gal: float | None = None
    alternate_fuel_cost_usd: float | None = None
    alternate_score: float | None = None
    alternate_path: list[dict[str, float]] | None = None
    score_breakdown: NormalizedScoreBreakdown | dict[str, Any] | None = None
    normalized_score_breakdown: NormalizedScoreBreakdown | dict[str, Any] | None = None
    fuel_breakdown: FuelBreakdownDetail | dict[str, Any] | None = None
    weather_checkpoints: list[WeatherCheckpointDetail] = []
    route_candidates: list[RouteCandidateSummary] = []
    wind_data_quality: str | None = None
    route_preference: str | None = None
    fuel_price_usd_per_gal: float | None = None
    delay_prediction: dict[str, Any] | None = None
    ete_prediction: dict[str, Any] | None = None
    warnings: list[str] = []
    departure_weather: dict[str, Any] | None = None
    destination_weather: dict[str, Any] | None = None
    departure_status: dict[str, Any] | None = None
    destination_status: dict[str, Any] | None = None
    segments: list[RouteSegmentDetail] = []
    diversion_airports: list[DiversionAirportDetail] = []
    departure_airport: AirportSummary | None = None
    destination_airport: AirportSummary | None = None
    aircraft_profile: AircraftProfile | None = None
    created_at: datetime | None = None
    live_data_snapshot: dict[str, Any] | None = None
    performance: dict[str, Any] | None = None


class RouteListItem(BaseModel):
    id: str
    route_request_id: str
    status: str
    departure_airport: AirportSummary
    destination_airport: AirportSummary
    primary_distance_nm: float
    primary_ete_minutes: float
    primary_score: float
    created_at: datetime


class RouteBriefResponse(BaseModel):
    route_result_id: str
    brief_type: str
    content: dict[str, Any]
    created_at: datetime | None = None


class CopilotChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class CopilotChatResponse(BaseModel):
    answer: str
    sources_used: list[str]
    safety_note: str
    intent: str | None = None


class CopilotStatusResponse(BaseModel):
    enabled: bool
    model: str | None = None
    suggested_questions: list[str] = []


class HealthResponse(BaseModel):
    status: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
