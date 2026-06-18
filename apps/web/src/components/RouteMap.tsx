"use client";

import { useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import type { DivIcon } from "leaflet";
import { Airport, WeatherCheckpoint } from "@/lib/api";
import { densifyPath, isOnRouteBetween, routeWaypoints, type LatLon } from "@/lib/mapUtils";
import { MapFitBounds } from "@/components/MapFitBounds";

const MapContainer = dynamic(
  () => import("react-leaflet").then((m) => m.MapContainer),
  { ssr: false }
);
const TileLayer = dynamic(
  () => import("react-leaflet").then((m) => m.TileLayer),
  { ssr: false }
);
const Polyline = dynamic(
  () => import("react-leaflet").then((m) => m.Polyline),
  { ssr: false }
);
const CircleMarker = dynamic(
  () => import("react-leaflet").then((m) => m.CircleMarker),
  { ssr: false }
);
const Marker = dynamic(
  () => import("react-leaflet").then((m) => m.Marker),
  { ssr: false }
);
const Popup = dynamic(
  () => import("react-leaflet").then((m) => m.Popup),
  { ssr: false }
);

interface RouteMapProps {
  departure?: Airport;
  destination?: Airport;
  primaryPath?: LatLon[];
  alternatePath?: LatLon[];
  diversionAirports?: Airport[];
  weatherCheckpoints?: WeatherCheckpoint[];
  tfrs?: { centroid_lat?: number; centroid_lon?: number; notam_number?: string; title?: string; impact?: string }[];
  hazards?: { latitude?: number; longitude?: number; hazard_type?: string; summary?: string }[];
  className?: string;
}

export function RouteMap({
  departure,
  destination,
  primaryPath = [],
  alternatePath = [],
  diversionAirports = [],
  weatherCheckpoints = [],
  tfrs = [],
  hazards = [],
  className = "h-96",
}: RouteMapProps) {
  const [showRoute, setShowRoute] = useState(true);
  const [showDiversions, setShowDiversions] = useState(true);
  const [showCheckpoints, setShowCheckpoints] = useState(true);
  const [showTfrs, setShowTfrs] = useState(true);
  const [showHazards, setShowHazards] = useState(true);
  const [ready, setReady] = useState(false);
  const [icons, setIcons] = useState<{
    dep: DivIcon;
    dest: DivIcon;
    diversion: DivIcon;
    checkpoint: DivIcon;
  } | null>(null);

  useEffect(() => {
    import("leaflet").then((L) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      delete (L.Icon.Default.prototype as any)._getIconUrl;
      L.Icon.Default.mergeOptions({
        iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
        iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
        shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
      });
      setIcons({
        dep: L.divIcon({
          className: "aeroroute-map-icon",
          html: '<div class="map-pin map-pin-dep">DEP</div>',
          iconSize: [44, 44],
          iconAnchor: [22, 22],
        }),
        dest: L.divIcon({
          className: "aeroroute-map-icon",
          html: '<div class="map-pin map-pin-dest">DEST</div>',
          iconSize: [44, 44],
          iconAnchor: [22, 22],
        }),
        diversion: L.divIcon({
          className: "aeroroute-map-icon",
          html: '<div class="map-pin map-pin-diversion">ALT</div>',
          iconSize: [36, 36],
          iconAnchor: [18, 18],
        }),
        checkpoint: L.divIcon({
          className: "aeroroute-map-icon",
          html: '<div class="map-pin map-pin-checkpoint">WX</div>',
          iconSize: [32, 32],
          iconAnchor: [16, 16],
        }),
      });
      setReady(true);
    });
  }, []);

  const densePrimary = useMemo(() => densifyPath(primaryPath), [primaryPath]);
  const denseAlternate = useMemo(() => densifyPath(alternatePath), [alternatePath]);
  const primaryWaypoints = useMemo(() => routeWaypoints(primaryPath), [primaryPath]);

  const relevantCheckpoints = useMemo(() => {
    if (!departure || !destination) return weatherCheckpoints;
    const dep = { lat: departure.latitude, lon: departure.longitude };
    const dest = { lat: destination.latitude, lon: destination.longitude };
    return weatherCheckpoints.filter((cp) => {
      if (cp.latitude == null || cp.longitude == null) return false;
      return isOnRouteBetween(dep, dest, { lat: cp.latitude, lon: cp.longitude });
    });
  }, [weatherCheckpoints, departure, destination]);

  const fitPositions = useMemo(() => {
    const points: [number, number][] = [];
    if (departure) points.push([departure.latitude, departure.longitude]);
    if (destination) points.push([destination.latitude, destination.longitude]);
    densePrimary.forEach((p) => points.push([p.lat, p.lon]));
    denseAlternate.forEach((p) => points.push([p.lat, p.lon]));
    diversionAirports.forEach((a) => points.push([a.latitude, a.longitude]));
    relevantCheckpoints.forEach((c) => {
      if (c.latitude != null && c.longitude != null) {
        points.push([c.latitude, c.longitude]);
      }
    });
    return points;
  }, [departure, destination, densePrimary, denseAlternate, diversionAirports, relevantCheckpoints]);

  const defaultCenter: [number, number] =
    departure && destination
      ? [
          (departure.latitude + destination.latitude) / 2,
          (departure.longitude + destination.longitude) / 2,
        ]
      : [39.8, -98.5];

  if (!ready || !icons) {
    return (
      <div
        className={`${className} flex items-center justify-center rounded-xl bg-card border border-border`}
      >
        <span className="text-slate-400">Loading map...</span>
      </div>
    );
  }

  return (
    <div className={`${className} relative rounded-xl overflow-hidden border border-border`}>
      <MapContainer
        center={defaultCenter}
        zoom={4}
        className="h-full w-full"
        scrollWheelZoom
        style={{ minHeight: "100%" }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <MapFitBounds positions={fitPositions} />

        {showRoute && densePrimary.length > 1 && (
          <Polyline
            positions={densePrimary.map((p) => [p.lat, p.lon] as [number, number])}
            pathOptions={{ color: "#38bdf8", weight: 4, opacity: 0.95 }}
          />
        )}
        {showRoute && denseAlternate.length > 1 && (
          <Polyline
            positions={denseAlternate.map((p) => [p.lat, p.lon] as [number, number])}
            pathOptions={{ color: "#94a3b8", weight: 3, opacity: 0.85, dashArray: "8 8" }}
          />
        )}

        {primaryWaypoints.map((wp, index) => (
          <CircleMarker
            key={`wp-${index}-${wp.lat}-${wp.lon}`}
            center={[wp.lat, wp.lon]}
            radius={6}
            pathOptions={{
              color: "#7dd3fc",
              fillColor: "#0ea5e9",
              fillOpacity: 0.9,
              weight: 2,
            }}
          >
            <Popup>
              <strong>Route waypoint {index + 1}</strong>
              <br />
              {wp.lat.toFixed(3)}, {wp.lon.toFixed(3)}
            </Popup>
          </CircleMarker>
        ))}

        {departure && (
          <Marker
            position={[departure.latitude, departure.longitude]}
            icon={icons.dep}
            zIndexOffset={1000}
          >
            <Popup>
              <strong>Departure</strong>
              <br />
              {departure.icao_code || departure.ident} — {departure.name}
            </Popup>
          </Marker>
        )}
        {destination && (
          <Marker
            position={[destination.latitude, destination.longitude]}
            icon={icons.dest}
            zIndexOffset={1000}
          >
            <Popup>
              <strong>Destination</strong>
              <br />
              {destination.icao_code || destination.ident} — {destination.name}
            </Popup>
          </Marker>
        )}
        {showDiversions &&
          diversionAirports.map((apt) => (
          <Marker
            key={apt.id}
            position={[apt.latitude, apt.longitude]}
            icon={icons.diversion}
            zIndexOffset={500}
          >
            <Popup>
              <strong>Diversion airport</strong>
              <br />
              {apt.icao_code || apt.ident} — {apt.name}
            </Popup>
          </Marker>
        ))}
        {showCheckpoints &&
          relevantCheckpoints.map((cp, i) =>
          cp.latitude != null && cp.longitude != null ? (
            <Marker
              key={cp.airport_id || `wx-${i}`}
              position={[cp.latitude, cp.longitude]}
              icon={icons.checkpoint}
              zIndexOffset={400}
            >
              <Popup>
                <strong>Weather checkpoint</strong>
                <br />
                {cp.icao} — {cp.flight_category || "UNKNOWN"}
              </Popup>
            </Marker>
          ) : null
        )}
        {showTfrs &&
          tfrs.map((tfr) =>
            tfr.centroid_lat != null && tfr.centroid_lon != null ? (
              <CircleMarker
                key={`tfr-${tfr.notam_number}`}
                center={[tfr.centroid_lat, tfr.centroid_lon]}
                radius={10}
                pathOptions={{
                  color: tfr.impact === "intersects" ? "#f87171" : "#fbbf24",
                  fillColor: tfr.impact === "intersects" ? "#ef4444" : "#f59e0b",
                  fillOpacity: 0.7,
                  weight: 2,
                }}
              >
                <Popup>
                  <strong>TFR {tfr.notam_number}</strong>
                  <br />
                  {tfr.title}
                  <br />
                  <em>{tfr.impact === "intersects" ? "Intersects route corridor" : "Nearby"}</em>
                </Popup>
              </CircleMarker>
            ) : null
          )}
        {showHazards &&
          hazards.map((h, i) =>
            h.latitude != null && h.longitude != null ? (
              <CircleMarker
                key={`hz-${i}`}
                center={[h.latitude, h.longitude]}
                radius={6}
                pathOptions={{
                  color: "#a78bfa",
                  fillColor: "#8b5cf6",
                  fillOpacity: 0.8,
                  weight: 2,
                }}
              >
                <Popup>
                  <strong>{h.hazard_type}</strong>
                  <br />
                  {h.summary}
                </Popup>
              </CircleMarker>
            ) : null
          )}
      </MapContainer>

      <div className="pointer-events-auto absolute top-3 right-3 z-[1000] flex flex-col gap-1 rounded-lg border border-border/80 bg-card/95 p-2 text-xs text-slate-300 shadow-lg backdrop-blur-sm">
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={showRoute} onChange={(e) => setShowRoute(e.target.checked)} />
          Route
        </label>
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={showDiversions} onChange={(e) => setShowDiversions(e.target.checked)} />
          Diversions
        </label>
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={showCheckpoints} onChange={(e) => setShowCheckpoints(e.target.checked)} />
          Weather checkpoints
        </label>
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={showTfrs} onChange={(e) => setShowTfrs(e.target.checked)} />
          TFRs
        </label>
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={showHazards} onChange={(e) => setShowHazards(e.target.checked)} />
          Weather hazards
        </label>
      </div>

      <div className="pointer-events-none absolute bottom-3 left-3 z-[1000] rounded-lg border border-border/80 bg-card/90 px-3 py-2 text-xs text-slate-300 shadow-lg backdrop-blur-sm">
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          <span>
            <span className="inline-block h-0.5 w-4 bg-sky-400 align-middle mr-1" />
            Primary
          </span>
          <span>
            <span className="inline-block h-0.5 w-4 border-t-2 border-dashed border-slate-400 align-middle mr-1" />
            Alternate
          </span>
          <span>
            <span className="inline-block h-2 w-2 rounded-full bg-sky-500 align-middle mr-1" />
            Waypoint
          </span>
          <span>
            <span className="text-amber-300 font-semibold mr-1">ALT</span>
            Diversion
          </span>
          <span>
            <span className="text-emerald-300 font-semibold mr-1">WX</span>
            Checkpoint
          </span>
        </div>
      </div>
    </div>
  );
}
