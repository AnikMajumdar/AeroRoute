"use client";

import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { AirportAutocomplete } from "@/components/AirportAutocomplete";
import { ConusNotice } from "@/components/ConusNotice";
import { PageLayout } from "@/components/Layout";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input, Label } from "@/components/ui/Input";
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
  const { userId, isLoaded, getToken } = useAuth();
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
      const token = await getToken();
      const result = await api.calculateRoute(
        {
          departure_airport_id: departure.id,
          destination_airport_id: destination.id,
          aircraft_profile_id: selectedAircraft,
          departure_time: effectiveDeparture.toISOString(),
          fuel_price_usd_per_gal: parseFloat(fuelPrice),
          route_preference: routePreference,
        },
        userId,
        token
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
    <PageLayout
      title="Plan New Route"
      subtitle="Select airports, aircraft, and preferences — then calculate your educational route plan."
      showDisclaimer={false}
    >
      <ConusNotice className="mb-8" />

      <div className="mb-8">
        <Button
          type="button"
          variant="outline"
          onClick={() => void loadDemoRoute()}
          disabled={demoLoading || aircraftLoading}
        >
          {demoLoading ? "Loading demo…" : "Use demo route (KJFK → KLAX)"}
        </Button>
      </div>

      <form onSubmit={handleSubmit} className="max-w-3xl space-y-8">
        <Card padding="p-6" className="space-y-6">
          <AirportAutocomplete label="Departure Airport" value={departure} onChange={setDeparture} />
          <AirportAutocomplete
            label="Destination Airport"
            value={destination}
            onChange={setDestination}
          />
        </Card>

        <Card padding="p-6">
          <Label>Aircraft</Label>
          {aircraftLoading ? (
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              {[1, 2].map((i) => (
                <div key={i} className="h-24 animate-pulse rounded-xl bg-white/5" />
              ))}
            </div>
          ) : (
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              {aircraft.map((a) => (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => setSelectedAircraft(a.id)}
                  className={`rounded-xl border p-4 text-left transition-all duration-200 ${
                    selectedAircraft === a.id
                      ? "border-sky-400/50 bg-sky-500/10 ring-2 ring-sky-400/20"
                      : "border-white/10 bg-white/[0.02] hover:border-white/20 hover:bg-white/[0.04]"
                  }`}
                >
                  <p className="font-semibold">{a.name}</p>
                  <p className="mt-1 text-xs text-muted">
                    {a.cruise_speed_kt} kt · {a.fuel_burn_gph} gph
                    {a.cruise_altitude_ft ? ` · ${a.cruise_altitude_ft.toLocaleString()} ft` : ""}
                  </p>
                </button>
              ))}
            </div>
          )}
          {aircraftError && (
            <div className="mt-3 flex items-center gap-3">
              <p className="text-sm text-red-300">{aircraftError}</p>
              <button
                type="button"
                onClick={() => void loadAircraft()}
                className="text-sm text-sky-400 hover:underline"
              >
                Retry
              </button>
            </div>
          )}
        </Card>

        <Card padding="p-6">
          <Label>Route preference</Label>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {ROUTE_PREFERENCES.map((pref) => (
              <button
                key={pref.id}
                type="button"
                onClick={() => setRoutePreference(pref.id)}
                className={`rounded-xl border px-4 py-3 text-left text-sm transition-all ${
                  routePreference === pref.id
                    ? "border-sky-400/50 bg-sky-500/10 ring-2 ring-sky-400/20"
                    : "border-white/10 bg-white/[0.02] hover:border-white/20"
                }`}
              >
                <span className="font-medium">{pref.label}</span>
                <span className="mt-0.5 block text-xs text-muted">{pref.desc}</span>
              </button>
            ))}
          </div>
        </Card>

        {selectedAircraftProfile?.cruise_altitude_ft && (
          <p className="text-xs text-muted">
            Cruise winds sampled near {selectedAircraftProfile.cruise_altitude_ft.toLocaleString()} ft.
          </p>
        )}

        <Card padding="p-6">
          <div className="grid gap-5 sm:grid-cols-2">
            <div>
              <Label>Departure date & time</Label>
              <Input
                type="datetime-local"
                value={departureTime}
                min={timeBounds.min}
                max={timeBounds.max}
                onChange={(e) => setDepartureTime(e.target.value)}
                required
              />
              <p className="mt-2 text-xs text-muted">
                Now through {FORECAST_HORIZON_DAYS} days ahead (forecast limit).
              </p>
            </div>
            <div>
              <Label>Fuel price ($/gal)</Label>
              <Input
                type="number"
                step="0.01"
                min="0"
                value={fuelPrice}
                onChange={(e) => setFuelPrice(e.target.value)}
              />
            </div>
          </div>
        </Card>

        {error && (
          <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
            {error}
          </div>
        )}

        <Button type="submit" size="lg" disabled={loading || aircraftLoading || aircraft.length === 0}>
          {loading ? "Calculating route…" : "Calculate Route"}
        </Button>
      </form>
    </PageLayout>
  );
}
