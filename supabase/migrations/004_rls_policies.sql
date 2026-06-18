-- Row Level Security: users access only their own route data (service role bypasses RLS)

ALTER TABLE route_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE route_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE route_briefs ENABLE ROW LEVEL SECURITY;

CREATE POLICY route_requests_user_isolation ON route_requests
    FOR ALL
    USING (user_id = current_setting('request.jwt.claims', true)::json->>'sub')
    WITH CHECK (user_id = current_setting('request.jwt.claims', true)::json->>'sub');

CREATE POLICY route_results_via_request ON route_results
    FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM route_requests rr
            WHERE rr.id = route_results.route_request_id
              AND rr.user_id = current_setting('request.jwt.claims', true)::json->>'sub'
        )
    );

CREATE POLICY route_briefs_via_result ON route_briefs
    FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM route_results res
            JOIN route_requests rr ON rr.id = res.route_request_id
            WHERE res.id = route_briefs.route_result_id
              AND rr.user_id = current_setting('request.jwt.claims', true)::json->>'sub'
        )
    );

-- Note: FastAPI uses service_role key and enforces user_id in application code.
-- These policies apply when using Supabase client-side with user JWTs.
