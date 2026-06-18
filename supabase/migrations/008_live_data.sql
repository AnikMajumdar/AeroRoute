-- Live aviation data snapshots and hazard storage (Phase 1)

CREATE TABLE IF NOT EXISTS live_data_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    route_result_id UUID REFERENCES route_results(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    snapshot JSONB NOT NULL DEFAULT '{}',
    source_health JSONB NOT NULL DEFAULT '{}',
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_live_data_snapshots_route ON live_data_snapshots(route_result_id);
CREATE INDEX IF NOT EXISTS idx_live_data_snapshots_user ON live_data_snapshots(user_id);

CREATE TABLE IF NOT EXISTS tfr_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    notam_number TEXT,
    title TEXT,
    raw_payload JSONB NOT NULL DEFAULT '{}',
    geometry GEOMETRY(Geometry, 4326),
    effective_start TIMESTAMPTZ,
    effective_end TIMESTAMPTZ,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tfr_snapshots_notam ON tfr_snapshots(notam_number);
CREATE INDEX IF NOT EXISTS idx_tfr_snapshots_fetched ON tfr_snapshots(fetched_at DESC);

CREATE TABLE IF NOT EXISTS notam_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    airport_icao TEXT,
    notam_id TEXT,
    raw_text TEXT,
    parsed JSONB NOT NULL DEFAULT '{}',
    source TEXT,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    effective_start TIMESTAMPTZ,
    effective_end TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_notam_snapshots_airport ON notam_snapshots(airport_icao);
CREATE INDEX IF NOT EXISTS idx_notam_snapshots_fetched ON notam_snapshots(fetched_at DESC);

CREATE TABLE IF NOT EXISTS aviation_weather_hazards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hazard_type TEXT NOT NULL,
    severity TEXT,
    summary TEXT,
    raw_text TEXT,
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    geometry JSONB,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_aviation_weather_hazards_type ON aviation_weather_hazards(hazard_type);
CREATE INDEX IF NOT EXISTS idx_aviation_weather_hazards_fetched ON aviation_weather_hazards(fetched_at DESC);

-- RLS: service role only for snapshot tables (API uses service role)
ALTER TABLE live_data_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE tfr_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE notam_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE aviation_weather_hazards ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_live_data_snapshots" ON live_data_snapshots
    FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "service_role_tfr_snapshots" ON tfr_snapshots
    FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "service_role_notam_snapshots" ON notam_snapshots
    FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "service_role_aviation_weather_hazards" ON aviation_weather_hazards
    FOR ALL USING (auth.role() = 'service_role');
