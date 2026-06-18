import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import { PageLayout } from "@/components/Layout";
import { RouteCopilot } from "@/components/RouteCopilot";
import { RouteMap } from "@/components/RouteMap";
import { LiveRestrictionsCard } from "@/components/LiveRestrictionsCard";
import { HazardsCard } from "@/components/HazardsCard";
import { LiveDataActions } from "@/components/LiveDataActions";
import { SafetyDisclaimer } from "@/components/SafetyDisclaimer";
import { Badge } from "@/components/ui/Badge";
import { Card, CardHeader } from "@/components/ui/Card";
import { StatCard } from "@/components/ui/StatCard";
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
  const { userId, getToken } = await auth();
  const e2eUserId = process.env.E2E_TEST_MODE === "true" ? "e2e-test-user" : null;
  if (!userId && !e2eUserId) redirect("/");

  const activeUserId = userId || e2eUserId!;
  const token = userId ? await getToken() : null;
  const { id } = await params;

  let route: Awaited<ReturnType<typeof api.getRoute>>;
  try {
    route = await api.getRoute(id, activeUserId, token);
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
    <PageLayout title="Route Result" showDisclaimer={false}>
      <Card className="mb-8" padding="p-6">
        <div className="flex flex-wrap items-center gap-4" data-testid="route-result-header">
          <div className="flex items-center gap-3 font-mono text-2xl font-semibold">
            <span className="gradient-text">{dep?.icao_code || dep?.ident}</span>
            <span className="text-muted">→</span>
            <span className="gradient-text">{dest?.icao_code || dest?.ident}</span>
          </div>
          <Badge tone={route.status === "completed" ? "success" : "warning"}>{route.status}</Badge>
          {route.route_preference && (
            <Badge tone="muted" className="capitalize">
              {route.route_preference.replace(/_/g, " ")}
            </Badge>
          )}
        </div>
      </Card>

      {route.warnings.length > 0 && (
        <Card className="mb-8 border-amber-500/25 bg-amber-500/[0.06]" padding="p-5">
          <p className="font-semibold text-amber-200 mb-3">Warnings</p>
          <ul className="list-disc space-y-1.5 pl-5 text-sm leading-relaxed text-amber-100/75">
            {route.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </Card>
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
            icon="📊"
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
        <Card className="mb-8" padding="p-6" data-testid="score-breakdown">
          <CardHeader
            title="Score breakdown"
            subtitle={`Preference: ${scoreBreakdown.preference}`}
          />
          <p className="mb-5 text-sm text-muted">
            Composite:{" "}
            <span className={`font-semibold ${scoreColor(scoreBreakdown.composite_score)}`}>
              {scoreBreakdown.composite_score.toFixed(0)}/100
            </span>
          </p>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
            {Object.entries(scoreBreakdown.component_scores).map(([key, value]) => (
              <ScoreBar key={key} label={key} value={value} />
            ))}
          </div>
        </Card>
      )}

      {fuel && (
        <Card className="mb-8" padding="p-6" data-testid="fuel-breakdown">
          <CardHeader title="Fuel plan" subtitle="Educational estimate — verify with POH and dispatch." />
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
        </Card>
      )}

      {(dep || dest) && (
        <Card className="mb-8" padding="p-6" data-testid="runway-info">
          <CardHeader title="Runway lengths" />
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
        </Card>
      )}

      {route.delay_prediction?.delay_risk && (
        <Card className="mb-8" padding="p-6" data-testid="delay-risk">
          <CardHeader
            title="Delay risk estimate"
            subtitle={`${route.delay_prediction.model_name || "rules_baseline_v1"} — AeroRoute estimate only, not dispatch advice`}
          />
          <div className="flex flex-wrap items-center gap-4">
            <Badge
              tone={
                route.delay_prediction.delay_risk === "high"
                  ? "danger"
                  : route.delay_prediction.delay_risk === "medium"
                    ? "warning"
                    : "success"
              }
              className="capitalize text-sm px-4 py-1.5"
            >
              {route.delay_prediction.delay_risk}
            </Badge>
            {route.delay_prediction.confidence != null && (
              <span className="text-sm text-muted">
                Confidence: {(route.delay_prediction.confidence * 100).toFixed(0)}%
              </span>
            )}
          </div>
        </Card>
      )}

      {route.ete_prediction && (
        <Card className="mb-8" padding="p-6" data-testid="ete-prediction">
          <CardHeader
            title="ETE estimate"
            subtitle={`Engine: ${route.ete_prediction.model_name || "deterministic_engine_v1"}${
              route.ete_prediction.is_surrogate ? " · surrogate model (trained on engine labels)" : ""
            }`}
          />
          <div className="flex flex-wrap gap-8 text-sm">
            <div>
              <span className="text-muted">Deterministic ETE</span>
              <p className="mt-1 text-xl font-mono font-semibold gradient-text">
                {formatDuration(route.ete_prediction.ete_minutes ?? route.primary_ete_minutes)}
              </p>
            </div>
            {route.ete_prediction.ml_adjusted_ete_minutes != null &&
              route.ete_prediction.ml_adjusted_ete_minutes !== route.ete_prediction.ete_minutes && (
                <div>
                  <span className="text-muted">ML-adjusted ETE</span>
                  <p className="mt-1 text-xl font-mono font-semibold">
                    {formatDuration(route.ete_prediction.ml_adjusted_ete_minutes)}
                  </p>
                </div>
              )}
          </div>
          {route.ete_prediction.note && (
            <p className="mt-4 rounded-xl border border-amber-500/20 bg-amber-500/[0.06] p-3 text-xs text-amber-100/80">
              {route.ete_prediction.note}
            </p>
          )}
        </Card>
      )}

      <div className="grid gap-6 md:grid-cols-2 mb-8">
        <WeatherCard title="Departure Weather" data={route.departure_weather} airport={dep} />
        <WeatherCard title="Destination Weather" data={route.destination_weather} airport={dest} />
      </div>

      {route.weather_checkpoints && route.weather_checkpoints.length > 0 && (
        <div className="mb-8">
          <h2 className="section-title mb-5 text-xl">En-route weather checkpoints</h2>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {route.weather_checkpoints.map((cp, i) => (
              <CheckpointCard key={cp.airport_id || i} checkpoint={cp} />
            ))}
          </div>
        </div>
      )}

      {route.diversion_airports && route.diversion_airports.length > 0 && (
        <Card className="mb-8" padding="p-6" data-testid="diversion-table">
          <CardHeader title="Diversion airports" />
          <div className="overflow-x-auto -mx-2">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/10 text-left text-muted">
                  <th className="px-2 pb-3 font-medium">Rank</th>
                  <th className="px-2 pb-3 font-medium">ICAO</th>
                  <th className="px-2 pb-3 font-medium">Name</th>
                  <th className="px-2 pb-3 font-medium">Distance</th>
                  <th className="px-2 pb-3 font-medium">Runway</th>
                </tr>
              </thead>
              <tbody>
                {route.diversion_airports.map((d) => (
                  <tr
                    key={d.airport.id}
                    className="border-b border-white/5 transition-colors hover:bg-white/[0.03]"
                  >
                    <td className="px-2 py-3 text-muted">{d.rank}</td>
                    <td className="px-2 py-3 font-mono font-medium text-sky-300">
                      {d.airport.icao_code || d.airport.ident}
                    </td>
                    <td className="px-2 py-3">{d.airport.name}</td>
                    <td className="px-2 py-3">{d.distance_from_route_nm.toFixed(1)} NM</td>
                    <td className="px-2 py-3">
                      {d.airport.longest_runway_ft
                        ? `${d.airport.longest_runway_ft.toLocaleString()} ft`
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <RouteCopilot routeId={id} />

      <SafetyDisclaimer className="mt-8" />
    </PageLayout>
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
    <Card padding="p-6">
      <CardHeader title={title} />
      <dl className="grid grid-cols-2 gap-3 text-sm">
        <dt className="text-muted">Distance</dt>
        <dd className="font-medium">
          {(isPrimary ? route.primary_distance_nm : route.alternate_distance_nm)!.toFixed(1)} NM
        </dd>
        <dt className="text-muted">ETE</dt>
        <dd className="font-medium">
          {formatDuration(
            (isPrimary ? route.primary_ete_minutes : route.alternate_ete_minutes)!
          )}
        </dd>
        <dt className="text-muted">Fuel burn</dt>
        <dd className="font-medium">
          {(isPrimary ? route.primary_fuel_burn_gal : route.alternate_fuel_burn_gal)!.toFixed(1)}{" "}
          gal
        </dd>
        <dt className="text-muted">Score</dt>
        <dd className="font-semibold gradient-text">
          {(isPrimary ? route.primary_score : route.alternate_score)!.toFixed(0)}/100
        </dd>
      </dl>
    </Card>
  );
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="text-muted capitalize">{label.replace(/_/g, " ")}</span>
        <span className={scoreColor(value)}>{value.toFixed(0)}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-white/5">
        <div
          className="h-full rounded-full bg-gradient-to-r from-sky-400 to-cyan-400 transition-all"
          style={{ width: `${Math.min(100, value)}%` }}
        />
      </div>
    </div>
  );
}

function FuelRow({ label, value, bold }: { label: string; value: string; bold?: boolean }) {
  return (
    <>
      <dt className="text-muted">{label}</dt>
      <dd className={bold ? "font-semibold gradient-text" : "font-medium"}>{value}</dd>
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
    <Card padding="p-6">
      <CardHeader title={title} subtitle={airport?.icao_code || airport?.ident} />
      {metar ? (
        <div className="space-y-3 text-sm">
          <p className="data-mono rounded-xl border border-white/5 bg-black/30 p-3 text-xs leading-relaxed">
            {String(metar.raw || "—")}
          </p>
          <p>
            Category:{" "}
            <span className="font-semibold text-sky-300">
              {String(metar.flight_category || "—")}
            </span>
          </p>
        </div>
      ) : (
        <p className="text-sm text-muted">Weather data unavailable</p>
      )}
      {typeof taf?.raw === "string" && taf.raw.length > 0 && (
        <div className="mt-4">
          <p className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">TAF</p>
          <p className="data-mono rounded-xl border border-white/5 bg-black/30 p-3 text-xs leading-relaxed">
            {taf.raw}
          </p>
        </div>
      )}
    </Card>
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
    <Card padding="p-4" hover>
      <p className="font-mono font-semibold text-sky-300">{checkpoint.icao}</p>
      <p className="truncate text-sm text-muted">{checkpoint.name}</p>
      <p className={`mt-2 text-sm font-semibold ${categoryColor}`}>{category}</p>
      {typeof checkpoint.metar?.raw === "string" && checkpoint.metar.raw.length > 0 && (
        <p className="data-mono mt-2 line-clamp-2 text-xs text-muted">
          {checkpoint.metar.raw}
        </p>
      )}
    </Card>
  );
}
