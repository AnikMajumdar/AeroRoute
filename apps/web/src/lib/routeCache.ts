import type { RouteResult } from "@/lib/api";

const PREFIX = "aeroroute:route:";

export function cacheRouteResult(route: RouteResult): void {
  if (typeof sessionStorage === "undefined") return;
  try {
    sessionStorage.setItem(`${PREFIX}${route.id}`, JSON.stringify(route));
  } catch {
    // ignore quota / private mode errors
  }
}

export function readCachedRouteResult(id: string): RouteResult | null {
  if (typeof sessionStorage === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(`${PREFIX}${id}`);
    if (!raw) return null;
    return JSON.parse(raw) as RouteResult;
  } catch {
    return null;
  }
}
