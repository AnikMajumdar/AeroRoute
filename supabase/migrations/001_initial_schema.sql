-- AeroRoute initial schema
-- Enable PostGIS for geospatial queries (diversion airport search)
CREATE EXTENSION IF NOT EXISTS postgis;

-- Airports (from OurAirports)
CREATE TABLE IF NOT EXISTS airports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ident TEXT NOT NULL UNIQUE,
    icao_code TEXT,
    iata_code TEXT,
    local_code TEXT,
    name TEXT NOT NULL,
    municipality TEXT,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    elevation_ft INTEGER,
    airport_type TEXT NOT NULL,
    longest_runway_ft INTEGER,
  geom GEOGRAPHY(POINT, 4326),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_airports_icao ON airports (icao_code);
CREATE INDEX IF NOT EXISTS idx_airports_iata ON airports (iata_code);
CREATE INDEX IF NOT EXISTS idx_airports_ident ON airports (ident);
CREATE INDEX IF NOT EXISTS idx_airports_type ON airports (airport_type);
CREATE INDEX IF NOT EXISTS idx_airports_geom ON airports USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_airports_search ON airports USING GIN (
    to_tsvector('english', coalesce(name, '') || ' ' || coalesce(municipality, '') || ' ' || coalesce(icao_code, '') || ' ' || coalesce(iata_code, ''))
);

-- Aircraft profiles (presets + user-created)
CREATE TABLE IF NOT EXISTS aircraft_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT,
    name TEXT NOT NULL,
    cruise_speed_kt INTEGER NOT NULL,
    fuel_burn_gph NUMERIC(8, 2) NOT NULL,
    is_preset BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_aircraft_profiles_user ON aircraft_profiles (user_id);

-- Route requests
CREATE TYPE route_job_status AS ENUM ('pending', 'processing', 'completed', 'failed');

CREATE TABLE IF NOT EXISTS route_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    departure_airport_id UUID NOT NULL REFERENCES airports (id),
    destination_airport_id UUID NOT NULL REFERENCES airports (id),
    aircraft_profile_id UUID NOT NULL REFERENCES aircraft_profiles (id),
    departure_time TIMESTAMPTZ NOT NULL,
    fuel_price_usd_per_gal NUMERIC(8, 2) NOT NULL,
    status route_job_status NOT NULL DEFAULT 'pending',
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_route_requests_user ON route_requests (user_id);
CREATE INDEX IF NOT EXISTS idx_route_requests_status ON route_requests (status);

-- Route results
CREATE TABLE IF NOT EXISTS route_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    route_request_id UUID NOT NULL UNIQUE REFERENCES route_requests (id) ON DELETE CASCADE,
    primary_distance_nm NUMERIC(10, 2) NOT NULL,
    primary_ete_minutes NUMERIC(10, 2) NOT NULL,
    primary_fuel_burn_gal NUMERIC(10, 2) NOT NULL,
    primary_fuel_cost_usd NUMERIC(10, 2) NOT NULL,
    primary_score NUMERIC(10, 2) NOT NULL,
    primary_path JSONB NOT NULL,
    alternate_distance_nm NUMERIC(10, 2),
    alternate_ete_minutes NUMERIC(10, 2),
    alternate_fuel_burn_gal NUMERIC(10, 2),
    alternate_fuel_cost_usd NUMERIC(10, 2),
    alternate_score NUMERIC(10, 2),
    alternate_path JSONB,
    score_breakdown JSONB,
    warnings JSONB DEFAULT '[]'::jsonb,
    departure_weather JSONB,
    destination_weather JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Route segments (wind-adjusted leg details)
CREATE TABLE IF NOT EXISTS route_segments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    route_result_id UUID NOT NULL REFERENCES route_results (id) ON DELETE CASCADE,
    route_variant TEXT NOT NULL CHECK (route_variant IN ('primary', 'alternate')),
    segment_index INTEGER NOT NULL,
    start_lat DOUBLE PRECISION NOT NULL,
    start_lon DOUBLE PRECISION NOT NULL,
    end_lat DOUBLE PRECISION NOT NULL,
    end_lon DOUBLE PRECISION NOT NULL,
    distance_nm NUMERIC(10, 2) NOT NULL,
    bearing_deg NUMERIC(8, 2) NOT NULL,
    wind_speed_kt NUMERIC(8, 2),
    wind_direction_deg NUMERIC(8, 2),
    headwind_component_kt NUMERIC(8, 2),
    groundspeed_kt NUMERIC(8, 2),
    ete_minutes NUMERIC(10, 2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_route_segments_result ON route_segments (route_result_id);

-- Diversion airports along route corridor
CREATE TABLE IF NOT EXISTS diversion_airports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    route_result_id UUID NOT NULL REFERENCES route_results (id) ON DELETE CASCADE,
    airport_id UUID NOT NULL REFERENCES airports (id),
    distance_from_route_nm NUMERIC(10, 2) NOT NULL,
    rank INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_diversion_airports_result ON diversion_airports (route_result_id);

-- External API response cache
CREATE TABLE IF NOT EXISTS api_cache (
    cache_key TEXT PRIMARY KEY,
    cache_value JSONB NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_cache_expires ON api_cache (expires_at);

-- Seed preset aircraft profiles (idempotent via name check)
INSERT INTO aircraft_profiles (name, cruise_speed_kt, fuel_burn_gph, is_preset, user_id)
SELECT * FROM (VALUES
    ('Cessna 172', 122, 8.5, TRUE, NULL::TEXT),
    ('Piper PA-28', 128, 9.5, TRUE, NULL::TEXT),
    ('Beechcraft Baron', 200, 26.0, TRUE, NULL::TEXT),
    ('Cirrus SR22', 183, 17.2, TRUE, NULL::TEXT),
    ('King Air 350', 312, 90.0, TRUE, NULL::TEXT)
) AS v(name, cruise_speed_kt, fuel_burn_gph, is_preset, user_id)
WHERE NOT EXISTS (
    SELECT 1 FROM aircraft_profiles WHERE is_preset = TRUE AND aircraft_profiles.name = v.name
);
