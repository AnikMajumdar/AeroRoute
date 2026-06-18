"""Continental United States (lower 48) bounding box for airport filtering."""

# Approximate CONUS bounds (excludes Alaska, Hawaii, and US territories).
CONUS_MIN_LAT = 24.396308
CONUS_MAX_LAT = 49.384358
CONUS_MIN_LON = -124.848974
CONUS_MAX_LON = -66.885444


def is_in_conus(latitude: float, longitude: float) -> bool:
    return (
        CONUS_MIN_LAT <= latitude <= CONUS_MAX_LAT
        and CONUS_MIN_LON <= longitude <= CONUS_MAX_LON
    )
