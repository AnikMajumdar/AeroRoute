"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { RouteListItem, formatDuration } from "@/lib/api";

export function DashboardRouteList({ routes }: { routes: RouteListItem[] }) {
  const router = useRouter();

  return (
    <div className="space-y-3">
      {routes.slice(0, 5).map((route) => (
        <div
          key={route.id}
          role="link"
          tabIndex={0}
          onClick={() => router.push(`/routes/${route.id}`)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              router.push(`/routes/${route.id}`);
            }
          }}
          className="cursor-pointer"
        >
          <Card hover padding="p-5" className="group">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <span className="font-mono text-lg font-semibold text-sky-300">
                {route.departure_airport.icao_code || route.departure_airport.ident}
              </span>
              <span className="text-muted">→</span>
              <span className="font-mono text-lg font-semibold text-sky-300">
                {route.destination_airport.icao_code || route.destination_airport.ident}
              </span>
              <Badge tone={route.status === "completed" ? "success" : "warning"}>
                {route.status}
              </Badge>
            </div>
            <span className="text-sm text-muted">
              {route.primary_distance_nm.toFixed(0)} NM · {formatDuration(route.primary_ete_minutes)} ·
              Score {route.primary_score.toFixed(0)}
            </span>
          </div>
          </Card>
        </div>
      ))}
      {routes.length > 5 && (
        <Link href="/routes" className="inline-block text-sm text-sky-400 hover:text-sky-300">
          View all →
        </Link>
      )}
    </div>
  );
}
