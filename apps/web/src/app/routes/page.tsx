import { auth } from "@clerk/nextjs/server";
import Link from "next/link";
import { redirect } from "next/navigation";
import { PageLayout } from "@/components/Layout";
import { api, formatDuration } from "@/lib/api";

export default async function SavedRoutesPage() {
  const { userId } = await auth();
  if (!userId) redirect("/");

  let routes: Awaited<ReturnType<typeof api.listRoutes>> = [];
  try {
    routes = await api.listRoutes(userId);
  } catch {
    // API unavailable
  }

  return (
    <PageLayout title="Saved Routes">
      <div className="mb-6">
        <Link
          href="/routes/new"
          className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-slate-900 hover:bg-accent/90"
        >
          + New Route
        </Link>
      </div>

      {routes.length === 0 ? (
        <p className="text-slate-400">No saved routes yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-sm">
            <thead className="bg-card text-left text-slate-400">
              <tr>
                <th className="px-4 py-3">Route</th>
                <th className="px-4 py-3">Distance</th>
                <th className="px-4 py-3">ETE</th>
                <th className="px-4 py-3">Score</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Date</th>
              </tr>
            </thead>
            <tbody>
              {routes.map((route) => (
                <tr key={route.id} className="border-t border-border hover:bg-card/50">
                  <td className="px-4 py-3">
                    <Link href={`/routes/${route.id}`} className="text-accent hover:underline">
                      {route.departure_airport.icao_code || route.departure_airport.ident} →{" "}
                      {route.destination_airport.icao_code || route.destination_airport.ident}
                    </Link>
                  </td>
                  <td className="px-4 py-3">{route.primary_distance_nm.toFixed(0)} NM</td>
                  <td className="px-4 py-3">{formatDuration(route.primary_ete_minutes)}</td>
                  <td className="px-4 py-3">{route.primary_score.toFixed(1)}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs ${
                        route.status === "completed"
                          ? "bg-green-500/20 text-green-300"
                          : route.status === "failed"
                            ? "bg-red-500/20 text-red-300"
                            : "bg-yellow-500/20 text-yellow-300"
                      }`}
                    >
                      {route.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-400">
                    {new Date(route.created_at).toLocaleDateString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageLayout>
  );
}
