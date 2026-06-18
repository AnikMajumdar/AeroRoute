-- Phase 2+: accuracy, fuel model, scoring, briefings, ML foundation

-- Aircraft performance fields
ALTER TABLE aircraft_profiles ADD COLUMN IF NOT EXISTS cruise_altitude_ft INTEGER DEFAULT 10000;
ALTER TABLE aircraft_profiles ADD COLUMN IF NOT EXISTS climb_fuel_gal NUMERIC(8, 2);
ALTER TABLE aircraft_profiles ADD COLUMN IF NOT EXISTS climb_time_min NUMERIC(8, 2);
ALTER TABLE aircraft_profiles ADD COLUMN IF NOT EXISTS descent_time_min NUMERIC(8, 2);
ALTER TABLE aircraft_profiles ADD COLUMN IF NOT EXISTS reserve_fuel_min NUMERIC(8, 2);
ALTER TABLE aircraft_profiles ADD COLUMN IF NOT EXISTS min_runway_ft INTEGER;

-- Route request preference
ALTER TABLE route_requests ADD COLUMN IF NOT EXISTS route_preference TEXT NOT NULL DEFAULT 'balanced';

-- Route segment wind detail
ALTER TABLE route_segments ADD COLUMN IF NOT EXISTS wind_altitude_ft INTEGER;
ALTER TABLE route_segments ADD COLUMN IF NOT EXISTS wind_pressure_level_hpa INTEGER;
ALTER TABLE route_segments ADD COLUMN IF NOT EXISTS tailwind_component_kt NUMERIC(8, 2);
ALTER TABLE route_segments ADD COLUMN IF NOT EXISTS wind_source TEXT DEFAULT 'surface';

-- Route result enrichments
ALTER TABLE route_results ADD COLUMN IF NOT EXISTS fuel_breakdown JSONB;
ALTER TABLE route_results ADD COLUMN IF NOT EXISTS normalized_score_breakdown JSONB;
ALTER TABLE route_results ADD COLUMN IF NOT EXISTS weather_checkpoints JSONB DEFAULT '[]'::jsonb;
ALTER TABLE route_results ADD COLUMN IF NOT EXISTS route_candidates JSONB DEFAULT '[]'::jsonb;
ALTER TABLE route_results ADD COLUMN IF NOT EXISTS wind_data_quality TEXT DEFAULT 'surface';

-- Auto-populate airport geom from lat/lon
CREATE OR REPLACE FUNCTION airports_set_geom()
RETURNS TRIGGER AS $$
BEGIN
  NEW.geom := ST_SetSRID(ST_MakePoint(NEW.longitude, NEW.latitude), 4326)::geography;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_airports_set_geom ON airports;
CREATE TRIGGER trg_airports_set_geom
  BEFORE INSERT OR UPDATE OF latitude, longitude ON airports
  FOR EACH ROW EXECUTE FUNCTION airports_set_geom();

UPDATE airports
SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography
WHERE geom IS NULL;

-- FAA airport status snapshots
CREATE TABLE IF NOT EXISTS airport_status_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    icao TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'unknown',
    delay_minutes INTEGER NOT NULL DEFAULT 0,
    is_closed BOOLEAN NOT NULL DEFAULT FALSE,
    ground_stop BOOLEAN NOT NULL DEFAULT FALSE,
    raw_payload JSONB,
    parsed_payload JSONB,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_airport_status_icao_fetched ON airport_status_snapshots (icao, fetched_at DESC);

-- Deterministic / future LLM route briefs
CREATE TABLE IF NOT EXISTS route_briefs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    route_result_id UUID NOT NULL REFERENCES route_results (id) ON DELETE CASCADE,
    brief_type TEXT NOT NULL DEFAULT 'deterministic',
    content JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_route_briefs_result ON route_briefs (route_result_id);

-- ML foundation
CREATE TABLE IF NOT EXISTS model_training_samples (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    route_result_id UUID REFERENCES route_results (id) ON DELETE SET NULL,
    features JSONB NOT NULL,
    labels JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS model_predictions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    route_result_id UUID REFERENCES route_results (id) ON DELETE SET NULL,
    model_name TEXT NOT NULL,
    prediction JSONB NOT NULL,
    confidence NUMERIC(5, 4),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- PostGIS corridor diversion search (distance args in meters)
CREATE OR REPLACE FUNCTION find_diversion_airports_in_corridor(
    dep_lon DOUBLE PRECISION,
    dep_lat DOUBLE PRECISION,
    dest_lon DOUBLE PRECISION,
    dest_lat DOUBLE PRECISION,
    min_dist_m DOUBLE PRECISION,
    max_dist_m DOUBLE PRECISION,
    min_runway_ft INTEGER,
    exclude_dep_id UUID,
    exclude_dest_id UUID,
    result_limit INTEGER DEFAULT 10
)
RETURNS TABLE (
    airport_id UUID,
    ident TEXT,
    icao_code TEXT,
    iata_code TEXT,
    name TEXT,
    municipality TEXT,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    airport_type TEXT,
    longest_runway_ft INTEGER,
    distance_from_route_m DOUBLE PRECISION
) AS $$
DECLARE
    route_line geography;
BEGIN
    route_line := ST_MakeLine(
        ST_SetSRID(ST_MakePoint(dep_lon, dep_lat), 4326)::geography,
        ST_SetSRID(ST_MakePoint(dest_lon, dest_lat), 4326)::geography
    );

    RETURN QUERY
    SELECT
        a.id,
        a.ident,
        a.icao_code,
        a.iata_code,
        a.name,
        a.municipality,
        a.latitude,
        a.longitude,
        a.airport_type,
        a.longest_runway_ft,
        ST_Distance(a.geom, route_line) AS distance_from_route_m
    FROM airports a
    WHERE a.geom IS NOT NULL
      AND a.id NOT IN (exclude_dep_id, exclude_dest_id)
      AND a.airport_type IN ('small_airport', 'medium_airport', 'large_airport')
      AND COALESCE(a.longest_runway_ft, 0) >= min_runway_ft
      AND ST_DWithin(a.geom, route_line, max_dist_m)
      AND NOT ST_DWithin(a.geom, route_line, min_dist_m)
    ORDER BY distance_from_route_m ASC
    LIMIT result_limit;
END;
$$ LANGUAGE plpgsql STABLE;

UPDATE aircraft_profiles SET
    cruise_altitude_ft = 8500, climb_fuel_gal = 1.5, climb_time_min = 12, descent_time_min = 8,
    reserve_fuel_min = 45, min_runway_ft = 2500, cruise_speed_kt = 122, fuel_burn_gph = 8.5
WHERE name = 'Cessna 172' AND is_preset = TRUE;

UPDATE aircraft_profiles SET
    cruise_altitude_ft = 8500, climb_fuel_gal = 1.8, climb_time_min = 14, descent_time_min = 9,
    reserve_fuel_min = 50, min_runway_ft = 2500, cruise_speed_kt = 128, fuel_burn_gph = 9.5
WHERE name = 'Piper PA-28' AND is_preset = TRUE;

UPDATE aircraft_profiles SET
    cruise_altitude_ft = 18000, climb_fuel_gal = 8.0, climb_time_min = 18, descent_time_min = 12,
    reserve_fuel_min = 60, min_runway_ft = 4000, cruise_speed_kt = 200, fuel_burn_gph = 26.0
WHERE name = 'Beechcraft Baron' AND is_preset = TRUE;

UPDATE aircraft_profiles SET
    cruise_altitude_ft = 12000, climb_fuel_gal = 4.0, climb_time_min = 15, descent_time_min = 10,
    reserve_fuel_min = 55, min_runway_ft = 3000, cruise_speed_kt = 183, fuel_burn_gph = 17.2
WHERE name = 'Cirrus SR22' AND is_preset = TRUE;

UPDATE aircraft_profiles SET
    cruise_altitude_ft = 28000, climb_fuel_gal = 25.0, climb_time_min = 22, descent_time_min = 15,
    reserve_fuel_min = 90, min_runway_ft = 5000, cruise_speed_kt = 312, fuel_burn_gph = 90.0
WHERE name = 'King Air 350' AND is_preset = TRUE;
