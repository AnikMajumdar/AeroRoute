"use client";

import { useRouter } from "next/navigation";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { RouteListItem, formatDuration } from "@/lib/api";

export function SavedRoutesTable({ routes }: { routes: RouteListItem[] }) {
  const router = useRouter();

  return (
    <Card padding="p-0" className="overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-white/10 bg-white/[0.02] text-left text-muted">
              <th className="px-5 py-4 font-medium">Route</th>
              <th className="px-5 py-4 font-medium">Distance</th>
              <th className="px-5 py-4 font-medium">ETE</th>
              <th className="px-5 py-4 font-medium">Score</th>
              <th className="px-5 py-4 font-medium">Status</th>
              <th className="px-5 py-4 font-medium">Date</th>
            </tr>
          </thead>
          <tbody>
            {routes.map((route) => (
              <tr
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
                className="cursor-pointer border-b border-white/5 transition-colors last:border-0 hover:bg-white/[0.06] focus-visible:bg-white/[0.06] focus-visible:outline-none"
              >
                <td className="px-5 py-4 font-mono font-medium text-sky-300">
                  {route.departure_airport.icao_code || route.departure_airport.ident} →{" "}
                  {route.destination_airport.icao_code || route.destination_airport.ident}
                </td>
                <td className="px-5 py-4 text-muted">{route.primary_distance_nm.toFixed(0)} NM</td>
                <td className="px-5 py-4 text-muted">
                  {formatDuration(route.primary_ete_minutes)}
                </td>
                <td className="px-5 py-4 font-medium">{route.primary_score.toFixed(1)}</td>
                <td className="px-5 py-4">
                  <Badge
                    tone={
                      route.status === "completed"
                        ? "success"
                        : route.status === "failed"
                          ? "danger"
                          : "warning"
                    }
                  >
                    {route.status}
                  </Badge>
                </td>
                <td className="px-5 py-4 text-muted">
                  {new Date(route.created_at).toLocaleDateString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
