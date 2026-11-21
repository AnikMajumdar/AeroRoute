-- Diversion airports along the planned route.
--
-- find_diversion_airports_in_corridor measured the distance to the route *segment*, so
--   * an airport behind the departure or beyond the destination counted as "near the route" whenever it was
--     within the search distance of the end point it was measured to, and
--   * together with the caller's first search tier (min_dist_m = 25 NM) the airports closest to the route were
--     skipped and the first airport listed was one 25-50 NM off the track.
--
-- It now only returns airports abeam the route: the point of the route closest to the airport must not be one of
-- the two ends (equivalently, the airport lies between the departure and the destination). min_dist_m is kept for
-- compatibility; callers pass 0 to get every airport from the track outward.

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
    dep_point geography;
    dest_point geography;
    route_line geography;
BEGIN
    dep_point := ST_SetSRID(ST_MakePoint(dep_lon, dep_lat), 4326)::geography;
    dest_point := ST_SetSRID(ST_MakePoint(dest_lon, dest_lat), 4326)::geography;
    route_line := ST_MakeLine(
        ARRAY[
            ST_SetSRID(ST_MakePoint(dep_lon, dep_lat), 4326),
            ST_SetSRID(ST_MakePoint(dest_lon, dest_lat), 4326)
        ]
    )::geography;

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
      AND (COALESCE(min_dist_m, 0) <= 0 OR NOT ST_DWithin(a.geom, route_line, min_dist_m))
      -- abeam the route: closer to the route than to either end (1 m tolerance for the numerics)
      AND ST_Distance(a.geom, route_line)
          < LEAST(ST_Distance(a.geom, dep_point), ST_Distance(a.geom, dest_point)) - 1.0
    ORDER BY distance_from_route_m ASC
    LIMIT result_limit;
END;
$$ LANGUAGE plpgsql STABLE;
