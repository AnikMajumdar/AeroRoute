import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import { PageLayout } from "@/components/Layout";
import { RouteCopilot } from "@/components/RouteCopilot";
import { RouteMap } from "@/components/RouteMap";
import { LiveRestrictionsCard } from "@/components/LiveRestrictionsCard";
import { HazardsCard } from "@/components/HazardsCard";
import { LiveDataActions } from "@/components/LiveDataActions";
import { SafetyDisclaimer } from "@/components/SafetyDisclaimer";
import { E2E_ROUTE_ID } from "@/lib/e2eMockRoute";
import {
  api,
  formatCurrency,
  formatDuration,
  scoreColor,
  windQualityLabel,
} from "@/lib/api";

export default async function RouteResultPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { userId } = await auth();
  const e2eUserId = process.env.E2E_TEST_MODE === "true" ? "e2e-test-user" : null;
  if (!userId && !e2eUserId) redirect("/");

  const activeUserId = userId || e2eUserId!;
  const { id } = await params;

  let route: Awaited<ReturnType<typeof api.getRoute>>;
  try {
    route = await api.getRoute(id, activeUserId);
  } catch {
    if (process.env.E2E_TEST_MODE === "true" && id === E2E_ROUTE_ID) {
      const { mockRouteResult } = await import("@/lib/e2eMockRoute");
      route = mockRouteResult;
    } else {
      redirect("/routes");
    }
  }

  const dep = route.departure_airport;
  const dest = route.destination_airport;
  const scoreBreakdown = route.normalized_score_breakdown || route.score_breakdown;
  const fuel = route.fuel_breakdown;
  const liveData = route.live_data_snapshot as
    | {
        fetched_at?: string;
        restrictions?: { tfrs?: unknown[]; notam_connected?: boolean };
        weather?: { hazards?: unknown[] };
        confidence?: { level?: string; data_basis?: string[] };
      }
    | undefined;

  return (
    <PageLayout title="Route Result">
      <div className="mb-6 flex flex-wrap items-center gap-4" data-testid="route-result-header">
        <div className="text-2xl font-mono">
          <span className="text-accent">{dep?.icao_code || dep?.ident}</span>
          <span className="mx-3 text-slate-500">→</span>
          <span className="text-accent">{dest?.icao_code || dest?.ident}</span>
        </div>
        <span
          className={`rounded-full px-3 py-1 text-xs font-medium ${
            route.status === "completed"
              ? "bg-green-500/20 text-green-300"
              : "bg-yellow-500/20 text-yellow-300"
          }`}
        >
          {route.status}
        </span>
        {route.route_preference && (
          <span className="rounded-full bg-slate-700/50 px-3 py-1 text-xs capitalize">
            {route.route_preference.replace(/_/g, " ")}
          </span>
        )}
      </div>

      {route.warnings.length > 0 && (
        <div className="mb-6 rounded-lg border border-amber-500/40 bg-amber-500/10 p-4">
          <p className="font-semibold text-amber-300 mb-2">Warnings</p>
          <ul className="list-disc pl-5 text-sm text-amber-200/80 space-y-1">
            {route.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="mb-6">
        <LiveDataActions routeId={route.id} userId={activeUserId} />
      </div>

      <div className="grid gap-8 lg:grid-cols-5 mb-8">
        <div className="lg:col-span-3">
          <RouteMap
            departure={dep}
            destination={dest}
            primaryPath={route.primary_path}
            alternatePath={route.alternate_path}
            diversionAirports={route.diversion_airports?.map((d) => d.airport)}
            weatherCheckpoints={route.weather_checkpoints}
            tfrs={(liveData?.restrictions?.tfrs as { centroid_lat?: number; centroid_lon?: number; notam_number?: string; title?: string; impact?: string }[]) || []}
            hazards={(liveData?.weather?.hazards as { latitude?: number; longitude?: number; hazard_type?: string; summary?: string }[]) || []}
            className="h-[28rem]"
          />
        </div>
        <div className="lg:col-span-2 space-y-4">
          <StatCard
            title="Primary Score"
            value={route.primary_score.toFixed(0)}
            subtitle={`out of 100 · ${windQualityLabel(route.wind_data_quality)}`}
            highlight
          />
          <div className="grid grid-cols-2 gap-3">
            <StatCard title="Distance" value={`${route.primary_distance_nm.toFixed(0)} NM`} />
            <StatCard title="ETE" value={formatDuration(route.primary_ete_minutes)} />
            <StatCard title="Trip Fuel" value={`${route.primary_fuel_burn_gal.toFixed(1)} gal`} />
            <StatCard title="Fuel Cost" value={formatCurrency(route.primary_fuel_cost_usd)} />
          </div>
        </div>
      </div>

      <div className="grid gap-6 md:grid-cols-2 mb-8">
        <LiveRestrictionsCard integrationDisabled />
        <HazardsCard integrationDisabled />
      </div>

      <div className="grid gap-6 md:grid-cols-2 mb-8">
        <RouteComparisonCard title="Primary Route" route={route} variant="primary" />
        {route.alternate_distance_nm && (
          <RouteComparisonCard title="Alternate Route" route={route} variant="alternate" />
        )}
      </div>

      {scoreBreakdown?.component_scores && (
        <div className="rounded-xl border border-border bg-card p-6 mb-8" data-testid="score-breakdown">
          <h2 className="text-lg font-semibold mb-4">Score Breakdown</h2>
          <p className="text-sm text-slate-400 mb-4">
            Composite:{" "}
            <span className={`font-semibold ${scoreColor(scoreBreakdown.composite_score)}`}>
              {scoreBreakdown.composite_score.toFixed(0)}/100
            </span>
            {" · "}
            Preference: {scoreBreakdown.preference}
          </p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {Object.entries(scoreBreakdown.component_scores).map(([key, value]) => (
              <ScoreBar key={key} label={key} value={value} />
            ))}
          </div>
        </div>
      )}

      {fuel && (
        <div className="rounded-xl border border-border bg-card p-6 mb-8" data-testid="fuel-breakdown">
          <h2 className="text-lg font-semibold mb-4">Fuel Plan (Educational)</h2>
          {route.fuel_price_usd_per_gal != null && (
            <p className="text-sm text-slate-400 mb-4">
              Planning fuel price:{" "}
              <span className="text-accent font-medium">
                {formatCurrency(route.fuel_price_usd_per_gal)}/gal
              </span>
              {" · "}
              Trip cost: {formatCurrency(route.primary_fuel_cost_usd)}
            </p>
          )}
          <dl className="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm">
            <FuelRow label="Climb" value={`${fuel.climb_fuel_gal.toFixed(1)} gal`} />
            <FuelRow label="Cruise" value={`${fuel.cruise_fuel_gal.toFixed(1)} gal`} />
            <FuelRow label="Descent" value={`${fuel.descent_fuel_gal.toFixed(1)} gal`} />
            <FuelRow label="Trip fuel" value={`${fuel.trip_fuel_gal.toFixed(1)} gal`} bold />
            <FuelRow label="Reserve" value={`${fuel.reserve_fuel_gal.toFixed(1)} gal`} />
            <FuelRow label="Total required" value={`${fuel.total_required_gal.toFixed(1)} gal`} bold />
          </dl>
          {fuel.warnings?.length > 0 && (
            <ul className="mt-4 text-sm text-amber-300 list-disc pl-5">
              {fuel.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {(dep || dest) && (
        <div className="rounded-xl border border-border bg-card p-6 mb-8" data-testid="runway-info">
          <h2 className="text-lg font-semibold mb-4">Runway Lengths</h2>
          <div className="grid gap-4 sm:grid-cols-2 text-sm">
            {dep && (
              <div>
                <p className="text-slate-400">Departure · {dep.icao_code || dep.ident}</p>
                <p className="font-medium mt-1">
                  {dep.longest_runway_ft
                    ? `${dep.longest_runway_ft.toLocaleString()} ft longest`
                    : "Runway data unavailable"}
                </p>
              </div>
            )}
            {dest && (
              <div>
                <p className="text-slate-400">Destination · {dest.icao_code || dest.ident}</p>
                <p className="font-medium mt-1">
                  {dest.longest_runway_ft
                    ? `${dest.longest_runway_ft.toLocaleString()} ft longest`
                    : "Runway data unavailable"}
                </p>
              </div>
            )}
          </div>
          {route.aircraft_profile?.min_runway_ft && (
            <p className="mt-3 text-xs text-slate-500">
              Aircraft planning minimum: {route.aircraft_profile.min_runway_ft.toLocaleString()} ft
            </p>
          )}
        </div>
      )}

      {route.delay_prediction?.delay_risk && (
        <div className="rounded-xl border border-border bg-card p-6 mb-8" data-testid="delay-risk">
          <h2 className="text-lg font-semibold mb-2">Delay Risk Estimate</h2>
          <p className="text-sm text-slate-400 mb-3">
            {route.delay_prediction.model_name || "rules_baseline_v1"} — AeroRoute estimate only, not dispatch advice
          </p>
          <div className="flex items-center gap-4 flex-wrap">
            <span
              className={`rounded-full px-4 py-1.5 text-sm font-semibold capitalize ${
                route.delay_prediction.delay_risk === "high"
                  ? "bg-red-500/20 text-red-300"
                  : route.delay_prediction.delay_risk === "medium"
                    ? "bg-amber-500/20 text-amber-300"
                    : "bg-green-500/20 text-green-300"
              }`}
            >
              {route.delay_prediction.delay_risk}
            </span>
            {route.delay_prediction.confidence != null && (
              <span className="text-sm text-slate-400">
                Confidence: {(route.delay_prediction.confidence * 100).toFixed(0)}%
              </span>
            )}
          </div>
        </div>
      )}

      {route.ete_prediction && (
        <div className="rounded-xl border border-border bg-card p-6 mb-8" data-testid="ete-prediction">
          <h2 className="text-lg font-semibold mb-2">ETE Estimate</h2>
          <p className="text-sm text-slate-400 mb-3">
            Engine: {route.ete_prediction.model_name || "deterministic_engine_v1"}
            {route.ete_prediction.is_surrogate && " · surrogate model (trained on engine labels)"}
          </p>
          <div className="flex flex-wrap gap-6 text-sm">
            <div>
              <span className="text-slate-500">Deterministic ETE</span>
              <p className="text-lg font-mono text-accent">
                {formatDuration(route.ete_prediction.ete_minutes ?? route.primary_ete_minutes)}
              </p>
            </div>
            {route.ete_prediction.ml_adjusted_ete_minutes != null &&
              route.ete_prediction.ml_adjusted_ete_minutes !== route.ete_prediction.ete_minutes && (
                <div>
                  <span className="text-slate-500">ML-adjusted ETE</span>
                  <p className="text-lg font-mono">
                    {formatDuration(route.ete_prediction.ml_adjusted_ete_minutes)}
                  </p>
                </div>
              )}
          </div>
          {route.ete_prediction.note && (
            <p className="text-xs text-amber-200/70 mt-3">{route.ete_prediction.note}</p>
          )}
        </div>
      )}

      <div className="grid gap-6 md:grid-cols-2 mb-8">
        <WeatherCard title="Departure Weather" data={route.departure_weather} airport={dep} />
        <WeatherCard title="Destination Weather" data={route.destination_weather} airport={dest} />
      </div>

      {route.weather_checkpoints && route.weather_checkpoints.length > 0 && (
        <div className="mb-8">
          <h2 className="text-lg font-semibold mb-4">En-Route Weather Checkpoints</h2>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {route.weather_checkpoints.map((cp, i) => (
              <CheckpointCard key={cp.airport_id || i} checkpoint={cp} />
            ))}
          </div>
        </div>
      )}

      {route.diversion_airports && route.diversion_airports.length > 0 && (
        <div className="rounded-xl border border-border bg-card p-6 mb-8" data-testid="diversion-table">
          <h2 className="text-lg font-semibold mb-4">Diversion Airports</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-slate-400">
                <tr>
                  <th className="pb-2">Rank</th>
                  <th className="pb-2">ICAO</th>
                  <th className="pb-2">Name</th>
                  <th className="pb-2">Distance from Route</th>
                  <th className="pb-2">Runway</th>
                </tr>
              </thead>
              <tbody>
                {route.diversion_airports.map((d) => (
                  <tr key={d.airport.id} className="border-t border-border">
                    <td className="py-2">{d.rank}</td>
                    <td className="py-2 font-mono text-accent">
                      {d.airport.icao_code || d.airport.ident}
                    </td>
                    <td className="py-2">{d.airport.name}</td>
                    <td className="py-2">{d.distance_from_route_nm.toFixed(1)} NM</td>
                    <td className="py-2">
                      {d.airport.longest_runway_ft
                        ? `${d.airport.longest_runway_ft.toLocaleString()} ft`
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <RouteCopilot routeId={id} />

      <SafetyDisclaimer />
    </PageLayout>
  );
}

function StatCard({
  title,
  value,
  subtitle,
  highlight,
}: {
  title: string;
  value: string;
  subtitle?: string;
  highlight?: boolean;
}) {
  return (
    <div
      className={`rounded-xl border p-4 ${
        highlight ? "border-accent/40 bg-accent/5" : "border-border bg-card"
      }`}
    >
      <p className="text-xs text-slate-400">{title}</p>
      <p className={`text-xl font-semibold ${highlight ? "text-accent" : ""}`}>{value}</p>
      {subtitle && <p className="text-xs text-slate-500 mt-1">{subtitle}</p>}
    </div>
  );
}

function RouteComparisonCard({
  title,
  route,
  variant,
}: {
  title: string;
  route: Awaited<ReturnType<typeof api.getRoute>>;
  variant: "primary" | "alternate";
}) {
  const isPrimary = variant === "primary";
  return (
    <div className="rounded-xl border border-border bg-card p-6">
      <h2 className="text-lg font-semibold text-accent mb-4">{title}</h2>
      <dl className="grid grid-cols-2 gap-3 text-sm">
        <dt className="text-slate-400">Distance</dt>
        <dd>
          {(isPrimary ? route.primary_distance_nm : route.alternate_distance_nm)!.toFixed(1)} NM
        </dd>
        <dt className="text-slate-400">ETE</dt>
        <dd>
          {formatDuration(
            (isPrimary ? route.primary_ete_minutes : route.alternate_ete_minutes)!
          )}
        </dd>
        <dt className="text-slate-400">Fuel Burn</dt>
        <dd>
          {(isPrimary ? route.primary_fuel_burn_gal : route.alternate_fuel_burn_gal)!.toFixed(1)}{" "}
          gal
        </dd>
        <dt className="text-slate-400">Score</dt>
        <dd className="font-semibold text-accent">
          {(isPrimary ? route.primary_score : route.alternate_score)!.toFixed(0)}/100
        </dd>
      </dl>
    </div>
  );
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="text-slate-400 capitalize">{label}</span>
        <span className={scoreColor(value)}>{value.toFixed(0)}</span>
      </div>
      <div className="h-2 rounded-full bg-slate-800 overflow-hidden">
        <div
          className="h-full bg-accent rounded-full transition-all"
          style={{ width: `${Math.min(100, value)}%` }}
        />
      </div>
    </div>
  );
}

function FuelRow({ label, value, bold }: { label: string; value: string; bold?: boolean }) {
  return (
    <>
      <dt className="text-slate-400">{label}</dt>
      <dd className={bold ? "font-semibold text-accent" : ""}>{value}</dd>
    </>
  );
}

function WeatherCard({
  title,
  data,
  airport,
}: {
  title: string;
  data?: Record<string, unknown>;
  airport?: { icao_code?: string | null; ident: string };
}) {
  const metar = data?.metar as Record<string, unknown> | undefined;
  const taf = data?.taf as Record<string, unknown> | undefined;

  return (
    <div className="rounded-xl border border-border bg-card p-6">
      <h2 className="text-lg font-semibold mb-2">{title}</h2>
      <p className="text-sm text-slate-400 mb-4">{airport?.icao_code || airport?.ident}</p>
      {metar ? (
        <div className="space-y-2 text-sm">
          <p className="font-mono text-xs bg-slate-800 rounded p-2">{String(metar.raw || "—")}</p>
          <p>
            Category:{" "}
            <span className="text-accent">{String(metar.flight_category || "—")}</span>
          </p>
        </div>
      ) : (
        <p className="text-sm text-slate-500">Weather data unavailable</p>
      )}
      {taf?.raw && (
        <div className="mt-4">
          <p className="text-xs text-slate-400 mb-1">TAF</p>
          <p className="font-mono text-xs bg-slate-800 rounded p-2">{String(taf.raw)}</p>
        </div>
      )}
    </div>
  );
}

function CheckpointCard({
  checkpoint,
}: {
  checkpoint: {
    icao?: string;
    name?: string;
    flight_category?: string;
    metar?: Record<string, unknown>;
  };
}) {
  const category = checkpoint.flight_category || "UNKNOWN";
  const categoryColor =
    category === "VFR"
      ? "text-green-300"
      : category === "MVFR"
        ? "text-blue-300"
        : category === "IFR"
          ? "text-amber-300"
          : "text-red-300";

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <p className="font-mono text-accent">{checkpoint.icao}</p>
      <p className="text-sm text-slate-400 truncate">{checkpoint.name}</p>
      <p className={`mt-2 text-sm font-semibold ${categoryColor}`}>{category}</p>
      {checkpoint.metar?.raw && (
        <p className="mt-2 font-mono text-xs text-slate-500 line-clamp-2">
          {String(checkpoint.metar.raw)}
        </p>
      )}
    </div>
  );
}
