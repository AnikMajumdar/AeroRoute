-- Row Level Security for every remaining table in the public schema.
--
-- Migrations 004 and 008 enabled RLS on route_requests, route_results, route_briefs and the live
-- data tables only. Every other table was readable and writable through the Supabase REST API
-- (PostgREST) with nothing but the project's public anon key: user aircraft profiles could be read
-- or overwritten, route geometry read, and the caches / ML tables poisoned.
--
-- The FastAPI service connects with the service_role key, which bypasses RLS, so enabling RLS does
-- not change how the API behaves. These policies only restrict direct PostgREST access.
-- The user id is the Clerk subject (JWT "sub"), the same expression migration 004 uses.
-- Policies are dropped before they are created so the migration can be re-run.

-- Reference data: readable by everyone, writable only by the service role.
ALTER TABLE airports ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS airports_public_read ON airports;
CREATE POLICY airports_public_read ON airports
    FOR SELECT
    USING (true);

-- Aircraft profiles: presets are visible to everyone and immutable; users manage only their own.
ALTER TABLE aircraft_profiles ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS aircraft_profiles_read ON aircraft_profiles;
CREATE POLICY aircraft_profiles_read ON aircraft_profiles
    FOR SELECT
    USING (
        is_preset
        OR user_id = current_setting('request.jwt.claims', true)::json->>'sub'
    );

DROP POLICY IF EXISTS aircraft_profiles_insert_own ON aircraft_profiles;
CREATE POLICY aircraft_profiles_insert_own ON aircraft_profiles
    FOR INSERT
    WITH CHECK (
        NOT is_preset
        AND user_id = current_setting('request.jwt.claims', true)::json->>'sub'
    );

DROP POLICY IF EXISTS aircraft_profiles_update_own ON aircraft_profiles;
CREATE POLICY aircraft_profiles_update_own ON aircraft_profiles
    FOR UPDATE
    USING (
        NOT is_preset
        AND user_id = current_setting('request.jwt.claims', true)::json->>'sub'
    )
    WITH CHECK (
        NOT is_preset
        AND user_id = current_setting('request.jwt.claims', true)::json->>'sub'
    );

DROP POLICY IF EXISTS aircraft_profiles_delete_own ON aircraft_profiles;
CREATE POLICY aircraft_profiles_delete_own ON aircraft_profiles
    FOR DELETE
    USING (
        NOT is_preset
        AND user_id = current_setting('request.jwt.claims', true)::json->>'sub'
    );

-- Per-route detail rows: readable by the owner of the route request, written only by the service role.
ALTER TABLE route_segments ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS route_segments_via_result ON route_segments;
CREATE POLICY route_segments_via_result ON route_segments
    FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM route_results res
            JOIN route_requests rr ON rr.id = res.route_request_id
            WHERE res.id = route_segments.route_result_id
              AND rr.user_id = current_setting('request.jwt.claims', true)::json->>'sub'
        )
    );

ALTER TABLE diversion_airports ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS diversion_airports_via_result ON diversion_airports;
CREATE POLICY diversion_airports_via_result ON diversion_airports
    FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM route_results res
            JOIN route_requests rr ON rr.id = res.route_request_id
            WHERE res.id = diversion_airports.route_result_id
              AND rr.user_id = current_setting('request.jwt.claims', true)::json->>'sub'
        )
    );

-- Internal tables: service role only (same pattern as migration 008).
ALTER TABLE api_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE airport_status_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE model_training_samples ENABLE ROW LEVEL SECURITY;
ALTER TABLE model_predictions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS service_role_api_cache ON api_cache;
CREATE POLICY service_role_api_cache ON api_cache
    FOR ALL USING (auth.role() = 'service_role');

DROP POLICY IF EXISTS service_role_airport_status_snapshots ON airport_status_snapshots;
CREATE POLICY service_role_airport_status_snapshots ON airport_status_snapshots
    FOR ALL USING (auth.role() = 'service_role');

DROP POLICY IF EXISTS service_role_model_training_samples ON model_training_samples;
CREATE POLICY service_role_model_training_samples ON model_training_samples
    FOR ALL USING (auth.role() = 'service_role');

DROP POLICY IF EXISTS service_role_model_predictions ON model_predictions;
CREATE POLICY service_role_model_predictions ON model_predictions
    FOR ALL USING (auth.role() = 'service_role');
