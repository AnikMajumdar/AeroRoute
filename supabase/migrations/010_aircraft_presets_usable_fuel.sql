-- Preset aircraft: usable fuel capacity plus the canonical planning values.
--
-- Capacity lets the planner reject flights an aircraft cannot fly non-stop. The other columns repeat
-- apps/api/app/data/aircraft_presets.py: the presets endpoint is read-only and only seeds an empty table, so
-- databases created from migrations 001-003 otherwise keep the column defaults (10,000 ft cruise, 45 min
-- reserve, 3,000 ft runway, ...). tests/test_migrations.py keeps this file and the Python data identical.
-- Custom aircraft keep usable_fuel_gal NULL (range is then not checked).

ALTER TABLE aircraft_profiles
    ADD COLUMN IF NOT EXISTS usable_fuel_gal NUMERIC(8, 2) CHECK (usable_fuel_gal IS NULL OR usable_fuel_gal > 0);

UPDATE aircraft_profiles
SET cruise_speed_kt = 122, fuel_burn_gph = 8.5, cruise_altitude_ft = 8500, climb_fuel_gal = 1.5, climb_time_min = 12, descent_time_min = 8, reserve_fuel_min = 45, min_runway_ft = 2500, usable_fuel_gal = 53.0
WHERE name = 'Cessna 172' AND is_preset = TRUE;

UPDATE aircraft_profiles
SET cruise_speed_kt = 128, fuel_burn_gph = 9.5, cruise_altitude_ft = 8500, climb_fuel_gal = 1.8, climb_time_min = 14, descent_time_min = 9, reserve_fuel_min = 50, min_runway_ft = 2500, usable_fuel_gal = 48.0
WHERE name = 'Piper PA-28' AND is_preset = TRUE;

UPDATE aircraft_profiles
SET cruise_speed_kt = 200, fuel_burn_gph = 26.0, cruise_altitude_ft = 18000, climb_fuel_gal = 8.0, climb_time_min = 18, descent_time_min = 12, reserve_fuel_min = 60, min_runway_ft = 4000, usable_fuel_gal = 166.0
WHERE name = 'Beechcraft Baron' AND is_preset = TRUE;

UPDATE aircraft_profiles
SET cruise_speed_kt = 183, fuel_burn_gph = 17.2, cruise_altitude_ft = 12000, climb_fuel_gal = 4.0, climb_time_min = 15, descent_time_min = 10, reserve_fuel_min = 55, min_runway_ft = 3000, usable_fuel_gal = 81.0
WHERE name = 'Cirrus SR22' AND is_preset = TRUE;

UPDATE aircraft_profiles
SET cruise_speed_kt = 312, fuel_burn_gph = 90.0, cruise_altitude_ft = 28000, climb_fuel_gal = 25.0, climb_time_min = 22, descent_time_min = 15, reserve_fuel_min = 90, min_runway_ft = 5000, usable_fuel_gal = 539.0
WHERE name = 'King Air 350' AND is_preset = TRUE;
