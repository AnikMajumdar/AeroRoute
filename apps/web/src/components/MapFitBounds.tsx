"use client";

import { useEffect } from "react";
import { useMap } from "react-leaflet";
import type { LatLngBoundsExpression } from "leaflet";

export function MapFitBounds({
  positions,
}: {
  positions: [number, number][];
}) {
  const map = useMap();

  useEffect(() => {
    if (positions.length === 0) return;

    if (positions.length === 1) {
      map.setView(positions[0], 9, { animate: false });
      return;
    }

    const bounds: LatLngBoundsExpression = positions;
    map.fitBounds(bounds, {
      padding: [56, 56],
      maxZoom: 8,
      animate: false,
    });
  }, [map, positions]);

  return null;
}
