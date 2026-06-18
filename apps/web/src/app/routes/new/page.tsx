"use client";

import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { AirportAutocomplete } from "@/components/AirportAutocomplete";
import { ConusNotice } from "@/components/ConusNotice";
import { PageLayout } from "@/components/Layout";
import {
  api,
  AircraftProfile,
  Airport,
  ROUTE_PREFERENCES,
  RoutePreference,
} from "@/lib/api";
import {
  DEPARTURE_TIME_GRACE_MS,
  FORECAST_HORIZON_DAYS,
  getDepartureTimeBounds,
  toLocalDatetimeInputValue,
} from "@/lib/mapUtils";

const DEMO_ROUTE = {
  departureQuery: "KJFK",
  destinationQuery: "KLAX",
};

export default function NewRoutePage() {
  const { userId, isLoaded } = useAuth();
  const router = useRouter();

  const [departure, setDeparture] = useState<Airport | null>(null);
  const [destination, setDestination] = useState<Airport | null>(null);
  const [aircraft, setAircraft] = useState<AircraftProfile[]>([]);
  const [selectedAircraft, setSelectedAircraft] = useState("");
  const [routePreference, setRoutePreference] = useState<RoutePreference>("balanced");
  const [departureTime, setDepartureTime] = useState("");
  const [fuelPrice, setFuelPrice] = useState("6.50");
  const [loading, setLoading] = useState(false);
  const [aircraftLoading, setAircraftLoading] = useState(true);
  const [aircraftError, setAircraftError] = useState("");
  const [error, setError] = useState("");
  const [demoLoading, setDemoLoading] = useState(false);

  const timeBounds = useMemo(() => getDepartureTimeBounds(), []);
  const selectedAircraftProfile = aircraft.find((a) => a.id === selectedAircraft);

  const loadAircraft = useCallback(async () => {
    setAircraftLoading(true);
    setAircraftError("");
    try {
      const presets = await api.getAircraftPresets();
      setAircraft(presets);
      if (presets.length === 1) {
        setSelectedAircraft(presets[0].id);
      }
    } catch (err) {
      setAircraft([]);
      setAircraftError(
        err instanceof Error
          ? err.message
          : "Could not load aircraft. Is the API running on port 8000?"
      );
    } finally {
      setAircraftLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isLoaded && !userId) router.push("/");
  }, [isLoaded, userId, router]);

  useEffect(() => {
    void loadAircraft();
    setDepartureTime(toLocalDatetimeInputValue(new Date()));
  }, [loadAircraft]);

  async function loadDemoRoute() {
    setDemoLoading(true);
    setError("");
    try {
      const [dep, dest] = await Promise.all([
        api.searchAirports(DEMO_ROUTE.departureQuery),
        api.searchAirports(DEMO_ROUTE.destinationQuery),
      ]);
      const depMatch = dep.find((a) => a.icao_code === "KJFK") || dep[0];
      const destMatch = dest.find((a) => a.icao_code === "KLAX") || dest[0];
      if (!depMatch || !destMatch) {
        setError("Demo airports not found — try manual search.");
        return;
      }
      setDeparture(depMatch);
      setDestination(destMatch);
      if (!selectedAircraft && aircraft[0]) {
        setSelectedAircraft(aircraft[0].id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load demo route");
    } finally {
      setDemoLoading(false);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!userId || !departure || !destination || !selectedAircraft) {
      setError("Please fill in all required fields.");
      return;
    }

    const selected = new Date(departureTime);
    const now = new Date();
    const earliest = new Date(now.getTime() - DEPARTURE_TIME_GRACE_MS);

    if (selected < earliest) {
      setError(
        `Departure must be within the last 5 minutes or up to ${FORECAST_HORIZON_DAYS} days ahead (forecast data limit).`
      );
      return;
    }

    // If the user kept the default "now" time, use current time at submit (minute inputs go stale).
    const effectiveDeparture = selected < now ? now : selected;

    setLoading(true);
    setError("");

    try {
      const result = await api.calculateRoute(
        {
          departure_airport_id: departure.id,
          destination_airport_id: destination.id,
          aircraft_profile_id: selectedAircraft,
          departure_time: effectiveDeparture.toISOString(),
          fuel_price_usd_per_gal: parseFloat(fuelPrice),
          route_preference: routePreference,
        },
        userId
      );
      router.push(`/routes/${result.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Route calculation failed");
    } finally {
      setLoading(false);
    }
  }

  if (!isLoaded) return null;

  return (
    <PageLayout title="Plan New Route">
      <ConusNotice className="mb-6" />

      <div className="mb-6 flex flex-wrap gap-3">
        <button
          type="button"
          onClick={() => void loadDemoRoute()}
          disabled={demoLoading || aircraftLoading}
          className="rounded-lg border border-accent/40 bg-accent/10 px-4 py-2 text-sm text-accent hover:bg-accent/20 disabled:opacity-50"
        >
          {demoLoading ? "Loading demo..." : "Use demo route (KJFK → KLAX)"}
        </button>
      </div>

      <form onSubmit={handleSubmit} className="max-w-3xl space-y-6">
        <AirportAutocomplete label="Departure Airport" value={departure} onChange={setDeparture} />
        <AirportAutocomplete
          label="Destination Airport"
          value={destination}
          onChange={setDestination}
        />

        <div>
          <label className="block text-sm font-medium text-slate-300 mb-2">Aircraft</label>
          {aircraftLoading ? (
            <div className="grid gap-3 sm:grid-cols-2">
              {[1, 2].map((i) => (
                <div key={i} className="h-24 animate-pulse rounded-xl bg-card border border-border" />
              ))}
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              {aircraft.map((a) => (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => setSelectedAircraft(a.id)}
                  className={`rounded-xl border p-4 text-left transition-colors ${
                    selectedAircraft === a.id
                      ? "border-accent bg-accent/10"
                      : "border-border bg-card hover:border-slate-500"
                  }`}
                >
                  <p className="font-semibold">{a.name}</p>
                  <p className="mt-1 text-xs text-slate-400">
                    {a.cruise_speed_kt} kt · {a.fuel_burn_gph} gph
                    {a.cruise_altitude_ft ? ` · ${a.cruise_altitude_ft.toLocaleString()} ft` : ""}
                  </p>
                </button>
              ))}
            </div>
          )}
          {aircraftError && (
            <div className="mt-2 flex items-center gap-3">
              <p className="text-sm text-red-300">{aircraftError}</p>
              <button
                type="button"
                onClick={() => void loadAircraft()}
                className="text-sm text-accent hover:underline"
              >
                Retry
              </button>
            </div>
          )}
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-300 mb-2">Route Preference</label>
          <div className="grid gap-2 sm:grid-cols-2">
            {ROUTE_PREFERENCES.map((pref) => (
              <button
                key={pref.id}
                type="button"
                onClick={() => setRoutePreference(pref.id)}
                className={`rounded-lg border px-4 py-3 text-left text-sm ${
                  routePreference === pref.id
                    ? "border-accent bg-accent/10"
                    : "border-border bg-card hover:border-slate-500"
                }`}
              >
                <span className="font-medium">{pref.label}</span>
                <span className="mt-0.5 block text-xs text-slate-400">{pref.desc}</span>
              </button>
            ))}
          </div>
        </div>

        {selectedAircraftProfile?.cruise_altitude_ft && (
          <p className="text-xs text-slate-500">
            Cruise winds sampled near {selectedAircraftProfile.cruise_altitude_ft.toLocaleString()} ft
            (nearest GFS pressure level).
          </p>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">
              Departure Date & Time
            </label>
            <input
              type="datetime-local"
              value={departureTime}
              min={timeBounds.min}
              max={timeBounds.max}
              onChange={(e) => setDepartureTime(e.target.value)}
              className="w-full rounded-lg border border-border bg-card px-4 py-2.5 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
              required
            />
            <p className="mt-1 text-xs text-slate-500">
              Now through {FORECAST_HORIZON_DAYS} days ahead (forecast limit).
            </p>
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">
              Fuel Price ($/gal)
            </label>
            <input
              type="number"
              step="0.01"
              min="0"
              value={fuelPrice}
              onChange={(e) => setFuelPrice(e.target.value)}
              className="w-full rounded-lg border border-border bg-card px-4 py-2.5 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </div>
        </div>

        {error && (
          <p className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-300">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={loading || aircraftLoading || aircraft.length === 0}
          className="rounded-lg bg-accent px-6 py-3 font-semibold text-slate-900 hover:bg-accent/90 disabled:opacity-50 transition-colors"
        >
          {loading ? "Calculating route..." : "Calculate Route"}
        </button>
      </form>
    </PageLayout>
  );
}
