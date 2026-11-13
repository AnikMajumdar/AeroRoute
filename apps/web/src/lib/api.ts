/** Browser calls Modal directly when NEXT_PUBLIC_API_URL is set (avoids Vercel proxy timeout). */
function resolvePublicApiUrl(): string | null {
  const url = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "");
  if (!url) return null;
  return url;
}

function apiBaseUrl(): string {
  if (typeof window !== "undefined") {
    // Copilot Gemini calls can take 30–45s; Vercel's /api/backend proxy times out ~10s on Hobby.
    const direct = resolvePublicApiUrl();
    if (direct) return direct;
    return "/api/backend";
  }
  const url = process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  return url.replace(/\/$/, "");
}

function formatApiError(error: unknown, status?: number): string {
  if (!error || typeof error !== "object") {
    return status ? `Request failed (HTTP ${status})` : "Request failed";
  }
  const record = error as Record<string, unknown>;
  const detail = record.detail;
  if (typeof detail === "string") return detail;
  if (typeof record.message === "string") return record.message;
  if (Array.isArray(detail)) {
    return detail
      .map((item) =>
        item && typeof item === "object" && "msg" in item
          ? String((item as { msg: string }).msg)
          : JSON.stringify(item)
      )
      .join("; ");
  }
  return status ? `Request failed (HTTP ${status})` : "Request failed";
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

async function getRouteMaybeMock(
  id: string,
  userId: string,
  token?: string | null
): Promise<RouteResult> {
  // Local Playwright runs only; the condition is inlined so production builds drop the fixture chunk.
  if (
    (process.env.E2E_TEST_MODE === "true" || process.env.NEXT_PUBLIC_E2E_TEST_MODE === "true") &&
    process.env.NODE_ENV !== "production"
  ) {
    const { E2E_ROUTE_ID, mockRouteResult } = await import("@/lib/e2eMockRoute");
    if (id === E2E_ROUTE_ID) {
      return mockRouteResult;
    }
  }
  return apiFetch<RouteResult>(`/routes/${id}`, { userId, token });
}

type ApiAuth = { userId?: string; token?: string | null };

async function apiFetch<T>(
  path: string,
  options: RequestInit & ApiAuth = {}
): Promise<T> {
  const { userId, token, ...fetchOptions } = options;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(fetchOptions.headers as Record<string, string>),
  };
  if (userId) {
    headers["X-User-Id"] = userId;
  }
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl()}${path}`, {
      ...fetchOptions,
      headers,
    });
  } catch {
    const hint =
      typeof window !== "undefined"
        ? "Check that NEXT_PUBLIC_API_URL is set on Vercel and the Modal API is deployed."
        : "Start the API with: npm run dev (or npm run dev:api)";
    throw new Error(`Cannot reach the API. ${hint}`);
  }

  const bodyText = await response.text();

  if (!response.ok) {
    let error: unknown = null;
    try {
      error = bodyText ? JSON.parse(bodyText) : null;
    } catch {
      error = bodyText ? { detail: bodyText.slice(0, 300) } : null;
    }
    throw new Error(formatApiError(error, response.status) || `API error: ${response.status}`);
  }

  if (!bodyText) {
    return undefined as T;
  }
  return JSON.parse(bodyText) as T;
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
    userId: string,
    token?: string | null
  ) =>
    apiFetch<RouteResult>("/routes/calculate", {
      method: "POST",
      body: JSON.stringify(data),
      userId,
      token,
    }),

  getRoute: (id: string, userId: string, token?: string | null) =>
    getRouteMaybeMock(id, userId, token),

  refreshLiveData: (routeId: string, userId: string, token?: string | null) =>
    apiFetch<{ live_data_snapshot: Record<string, unknown> }>(`/routes/${routeId}/live-data/refresh`, {
      method: "POST",
      userId,
      token,
    }),

  listRoutes: (userId: string, token?: string | null) =>
    apiFetch<RouteListItem[]>("/routes", { userId, token }),

  getCopilotStatus: () => apiFetch<CopilotStatus>("/copilot/status"),

  getCopilotSuggestions: (routeId: string, userId: string, token?: string | null) =>
    apiFetch<CopilotStatus>(`/routes/${routeId}/copilot/suggestions`, { userId, token }),

  copilotChat: (routeId: string, question: string, userId: string, token?: string | null) =>
    apiFetch<CopilotChatResponse>(`/routes/${routeId}/copilot/chat`, {
      method: "POST",
      body: JSON.stringify({ question }),
      userId,
      token,
    }),

  draftBrief: (routeId: string, userId: string, token?: string | null) =>
    apiFetch<{ content: Record<string, unknown> }>(`/routes/${routeId}/brief/draft`, {
      method: "POST",
      userId,
      token,
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
