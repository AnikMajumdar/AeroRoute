export const FORECAST_HORIZON_DAYS = 7;

/** Match API grace: departure may be up to 5 minutes in the past. */
export const DEPARTURE_TIME_GRACE_MS = 5 * 60 * 1000;

export interface LatLon {
  lat: number;
  lon: number;
}

/** Interpolate points along each leg for a smoother map polyline. */
export function densifyPath(path: LatLon[], pointsPerLeg = 12): LatLon[] {
  if (path.length < 2) return path;

  const dense: LatLon[] = [{ lat: path[0].lat, lon: path[0].lon }];

  for (let i = 0; i < path.length - 1; i++) {
    const start = path[i];
    const end = path[i + 1];
    for (let step = 1; step <= pointsPerLeg; step++) {
      const t = step / (pointsPerLeg + 1);
      dense.push({
        lat: start.lat + (end.lat - start.lat) * t,
        lon: start.lon + (end.lon - start.lon) * t,
      });
    }
    dense.push({ lat: end.lat, lon: end.lon });
  }

  return dense;
}

/** Vertices between departure and destination (route shaping waypoints). */
export function routeWaypoints(path: LatLon[]): LatLon[] {
  if (path.length <= 2) return [];
  return path.slice(1, -1);
}

export function toLocalDatetimeInputValue(date: Date): string {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

export function getDepartureTimeBounds(): { min: string; max: string } {
  const now = new Date();
  const earliest = new Date(now.getTime() - DEPARTURE_TIME_GRACE_MS);
  const max = new Date(now.getTime() + FORECAST_HORIZON_DAYS * 24 * 60 * 60 * 1000);
  return {
    min: toLocalDatetimeInputValue(earliest),
    max: toLocalDatetimeInputValue(max),
  };
}

export function isDepartureTimeAllowed(value: string): boolean {
  if (!value) return false;
  const selected = new Date(value);
  const now = new Date();
  const earliest = new Date(now.getTime() - DEPARTURE_TIME_GRACE_MS);
  const max = new Date(now.getTime() + FORECAST_HORIZON_DAYS * 24 * 60 * 60 * 1000);
  return selected >= earliest && selected <= max;
}

const EARTH_RADIUS_NM = 3440.065;

function haversineNm(a: LatLon, b: LatLon): number {
  const lat1 = (a.lat * Math.PI) / 180;
  const lat2 = (b.lat * Math.PI) / 180;
  const dLat = lat2 - lat1;
  const dLon = ((b.lon - a.lon) * Math.PI) / 180;
  const x =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_NM * Math.asin(Math.sqrt(x));
}

function crossTrackNm(routeStart: LatLon, routeEnd: LatLon, point: LatLon): number {
  const dist13 = haversineNm(routeStart, point) / EARTH_RADIUS_NM;
  if (dist13 === 0) return 0;
  const bearing = (deg: number) => (deg * Math.PI) / 180;
  const brng13 = initialBearingDeg(routeStart, point);
  const brng12 = initialBearingDeg(routeStart, routeEnd);
  const ct = Math.asin(Math.sin(dist13) * Math.sin(bearing(brng13) - bearing(brng12)));
  return Math.abs(ct * EARTH_RADIUS_NM);
}

function initialBearingDeg(a: LatLon, b: LatLon): number {
  const lat1 = (a.lat * Math.PI) / 180;
  const lat2 = (b.lat * Math.PI) / 180;
  const dLon = ((b.lon - a.lon) * Math.PI) / 180;
  const y = Math.sin(dLon) * Math.cos(lat2);
  const x =
    Math.cos(lat1) * Math.sin(lat2) -
    Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLon);
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}

function alongTrackNm(routeStart: LatLon, routeEnd: LatLon, point: LatLon): number {
  return haversineNm(routeStart, point);
}

/** True when a point lies along the great-circle between dep and dest (not past either end). */
export function isOnRouteBetween(
  dep: LatLon,
  dest: LatLon,
  point: LatLon,
  marginFromEndsNm = 25,
  maxCrossTrackNm = 75,
  segmentSlackNm = 20
): boolean {
  const total = haversineNm(dep, dest);
  if (total <= marginFromEndsNm * 2) return false;

  const distFromDep = haversineNm(dep, point);
  const distToDest = haversineNm(point, dest);

  if (distFromDep < marginFromEndsNm || distToDest < marginFromEndsNm) return false;
  if (distFromDep >= total - marginFromEndsNm) return false;
  if (distFromDep + distToDest > total + segmentSlackNm) return false;

  return crossTrackNm(dep, dest, point) <= maxCrossTrackNm;
}
