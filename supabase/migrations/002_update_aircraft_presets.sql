-- Refresh preset aircraft with typical cruise planning values
UPDATE aircraft_profiles SET cruise_speed_kt = 122, fuel_burn_gph = 8.5 WHERE name = 'Cessna 172' AND is_preset = TRUE;
UPDATE aircraft_profiles SET cruise_speed_kt = 128, fuel_burn_gph = 9.5 WHERE name = 'Piper PA-28' AND is_preset = TRUE;
UPDATE aircraft_profiles SET cruise_speed_kt = 200, fuel_burn_gph = 26.0 WHERE name = 'Beechcraft Baron' AND is_preset = TRUE;
UPDATE aircraft_profiles SET cruise_speed_kt = 183, fuel_burn_gph = 17.2 WHERE name = 'Cirrus SR22' AND is_preset = TRUE;
UPDATE aircraft_profiles SET cruise_speed_kt = 312, fuel_burn_gph = 90.0 WHERE name = 'King Air 350' AND is_preset = TRUE;
