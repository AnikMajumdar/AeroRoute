const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function formatApiError(error: unknown): string {
  if (!error || typeof error !== "object") return "Request failed";
  const detail = (error as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) =>
        item && typeof item === "object" && "msg" in item
          ? String((item as { msg: string }).msg)
          : JSON.stringify(item)
      )
      .join("; ");
  }
  return "Request failed";
}

export type RoutePreference = "balanced" | "fastest" | "fuel_saver" | "weather_cautious";

export interface Airport {
  id: string;
  ident: string;
  icao_code: string | null;
  iata_code: string | null;
  name: string;
  municipality: string | null;
  latitude: number;
  longitude: number;
  airport_type: string;
  longest_runway_ft: number | null;
}

export interface AircraftProfile {
  id: string;
  name: string;
  cruise_speed_kt: number;
  fuel_burn_gph: number;
  cruise_altitude_ft?: number;
  climb_fuel_gal?: number;
  climb_time_min?: number;
  descent_time_min?: number;
  reserve_fuel_min?: number;
  min_runway_ft?: number;
  is_preset: boolean;
}

export interface NormalizedScoreBreakdown {
  preference: string;
  composite_score: number;
  component_scores: Record<string, number>;
  weights: Record<string, number>;
  legacy?: Record<string, number>;
}

export interface FuelBreakdown {
  climb_fuel_gal: number;
  cruise_fuel_gal: number;
  descent_fuel_gal: number;
  trip_fuel_gal: number;
  reserve_fuel_gal: number;
  total_required_gal: number;
  fuel_remaining_gal?: number | null;
  fuel_margin_gal?: number | null;
  warnings: string[];
}

export interface WeatherCheckpoint {
  airport_id?: string;
  icao?: string;
  name?: string;
  latitude?: number;
  longitude?: number;
  flight_category?: string;
  metar?: Record<string, unknown>;
  weather_penalty?: number;
}

export interface RouteCandidate {
  name: string;
  distance_nm: number;
  ete_minutes: number;
  fuel_burn_gal: number;
  score: number;
  selected: boolean;
}

export interface RouteResult {
  id: string;
  route_request_id: string;
  status: string;
  primary_distance_nm: number;
  primary_ete_minutes: number;
  primary_fuel_burn_gal: number;
  primary_fuel_cost_usd: number;
  primary_score: number;
  primary_path: { lat: number; lon: number }[];
  alternate_distance_nm?: number;
  alternate_ete_minutes?: number;
  alternate_fuel_burn_gal?: number;
  alternate_fuel_cost_usd?: number;
  alternate_score?: number;
  alternate_path?: { lat: number; lon: number }[];
  score_breakdown?: NormalizedScoreBreakdown;
  normalized_score_breakdown?: NormalizedScoreBreakdown;
  fuel_breakdown?: FuelBreakdown;
  weather_checkpoints?: WeatherCheckpoint[];
  route_candidates?: RouteCandidate[];
  wind_data_quality?: string;
  route_preference?: string;
  fuel_price_usd_per_gal?: number;
  delay_prediction?: {
    delay_risk?: string;
    confidence?: number;
    model_name?: string;
  };
  ete_prediction?: {
    ete_minutes?: number;
    ml_adjusted_ete_minutes?: number;
    adjustment_minutes?: number;
    model_name?: string;
    is_surrogate?: boolean;
    note?: string;
  };
  warnings: string[];
  departure_weather?: Record<string, unknown>;
  destination_weather?: Record<string, unknown>;
  departure_status?: Record<string, unknown>;
  destination_status?: Record<string, unknown>;
  diversion_airports?: {
    airport: Airport;
    distance_from_route_nm: number;
    rank: number;
  }[];
  departure_airport?: Airport;
  destination_airport?: Airport;
  aircraft_profile?: AircraftProfile;
  created_at?: string;
  live_data_snapshot?: Record<string, unknown>;
  performance?: { provider_timings?: Record<string, number> };
}

export interface RouteListItem {
  id: string;
  route_request_id: string;
  status: string;
  departure_airport: Airport;
  destination_airport: Airport;
  primary_distance_nm: number;
  primary_ete_minutes: number;
  primary_score: number;
  created_at: string;
}

export interface CopilotChatResponse {
  answer: string;
  sources_used: string[];
  safety_note: string;
}

export interface CopilotStatus {
  enabled: boolean;
  model?: string;
  suggested_questions?: string[];
}

const IS_E2E = process.env.E2E_TEST_MODE === "true" || process.env.NEXT_PUBLIC_E2E_TEST_MODE === "true";

async function getRouteMaybeMock(id: string, userId: string): Promise<RouteResult> {
  if (IS_E2E) {
    const { E2E_ROUTE_ID, mockRouteResult } = await import("@/lib/e2eMockRoute");
    if (id === E2E_ROUTE_ID) {
      return mockRouteResult;
    }
  }
  return apiFetch<RouteResult>(`/routes/${id}`, { userId });
}

async function apiFetch<T>(
  path: string,
  options: RequestInit & { userId?: string } = {}
): Promise<T> {
  const { userId, ...fetchOptions } = options;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(fetchOptions.headers as Record<string, string>),
  };
  if (userId) {
    headers["X-User-Id"] = userId;
  }

  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...fetchOptions,
      headers,
    });
  } catch {
    throw new Error(
      `Cannot reach the API at ${API_URL}. Start it with: npm run dev (or npm run dev:api)`
    );
  }

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(formatApiError(error) || `API error: ${response.status}`);
  }

  return response.json();
}

export const ROUTE_PREFERENCES: { id: RoutePreference; label: string; desc: string }[] = [
  { id: "balanced", label: "Balanced", desc: "Equal weight on time, fuel, weather, delays" },
  { id: "fastest", label: "Fastest", desc: "Prioritize shortest ETE" },
  { id: "fuel_saver", label: "Fuel Saver", desc: "Prioritize lower fuel burn" },
  { id: "weather_cautious", label: "Weather Cautious", desc: "Penalize MVFR/IFR more heavily" },
];

export const api = {
  health: () => apiFetch<{ status: string }>("/health"),

  searchAirports: (q: string) =>
    apiFetch<Airport[]>(`/airports/search?q=${encodeURIComponent(q)}`),

  getAircraftPresets: () => apiFetch<AircraftProfile[]>("/aircraft/presets"),

  calculateRoute: (
    data: {
      departure_airport_id: string;
      destination_airport_id: string;
      aircraft_profile_id: string;
      departure_time: string;
      fuel_price_usd_per_gal: number;
      route_preference?: RoutePreference;
    },
    userId: string
  ) =>
    apiFetch<RouteResult>("/routes/calculate", {
      method: "POST",
      body: JSON.stringify(data),
      userId,
    }),

  getRoute: (id: string, userId: string) => getRouteMaybeMock(id, userId),

  refreshLiveData: (routeId: string, userId: string) =>
    apiFetch<{ live_data_snapshot: Record<string, unknown> }>(`/routes/${routeId}/live-data/refresh`, {
      method: "POST",
      userId,
    }),

  listRoutes: (userId: string) => apiFetch<RouteListItem[]>("/routes", { userId }),

  getCopilotStatus: () => apiFetch<CopilotStatus>("/copilot/status"),

  getCopilotSuggestions: (routeId: string, userId: string) =>
    apiFetch<CopilotStatus>(`/routes/${routeId}/copilot/suggestions`, { userId }),

  copilotChat: (routeId: string, question: string, userId: string) =>
    apiFetch<CopilotChatResponse>(`/routes/${routeId}/copilot/chat`, {
      method: "POST",
      body: JSON.stringify({ question }),
      userId,
    }),

  draftBrief: (routeId: string, userId: string) =>
    apiFetch<{ content: Record<string, unknown> }>(`/routes/${routeId}/brief/draft`, {
      method: "POST",
      userId,
    }),
};

export function formatDuration(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

export function formatCurrency(amount: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(amount);
}

export function scoreColor(score: number): string {
  if (score >= 75) return "text-green-300";
  if (score >= 50) return "text-amber-300";
  return "text-red-300";
}

export function windQualityLabel(quality?: string): string {
  switch (quality) {
    case "pressure_level":
      return "Cruise-altitude GFS winds";
    case "surface_fallback":
      return "Surface wind fallback";
    case "mixed":
      return "Mixed cruise/surface winds";
    default:
      return "Wind data unavailable";
  }
}
