-- PostGIS fix: ST_MakeLine requires geometry arguments, not geography.

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
      AND NOT ST_DWithin(a.geom, route_line, min_dist_m)
    ORDER BY distance_from_route_m ASC
    LIMIT result_limit;
END;
$$ LANGUAGE plpgsql STABLE;
