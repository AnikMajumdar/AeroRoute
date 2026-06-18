import { auth } from "@clerk/nextjs/server";
import Link from "next/link";
import { redirect } from "next/navigation";
import { PageLayout } from "@/components/Layout";
import { api, formatDuration } from "@/lib/api";

export default async function DashboardPage() {
  const { userId } = await auth();
  if (!userId) redirect("/");

  let routes: Awaited<ReturnType<typeof api.listRoutes>> = [];
  try {
    routes = await api.listRoutes(userId);
  } catch {
    // API may be unavailable during local dev
  }

  return (
    <PageLayout title="Dashboard">
      <div className="grid gap-6 md:grid-cols-3 mb-8">
        <div className="rounded-xl border border-border bg-card p-6">
          <p className="text-sm text-slate-400">Saved Routes</p>
          <p className="mt-1 text-3xl font-bold text-accent">{routes.length}</p>
        </div>
        <div className="rounded-xl border border-border bg-card p-6 md:col-span-2">
          <p className="text-sm text-slate-400">Quick Actions</p>
          <div className="mt-3 flex gap-3">
            <Link
              href="/routes/new"
              className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-slate-900 hover:bg-accent/90"
            >
              Plan New Route
            </Link>
            <Link
              href="/routes"
              className="rounded-lg border border-border px-4 py-2 text-sm font-medium hover:bg-slate-800"
            >
              View All Routes
            </Link>
          </div>
        </div>
      </div>

      <h2 className="text-xl font-semibold mb-4">Recent Routes</h2>
      {routes.length === 0 ? (
        <p className="text-slate-400">
          No routes yet.{" "}
          <Link href="/routes/new" className="text-accent hover:underline">
            Plan your first route
          </Link>
        </p>
      ) : (
        <div className="space-y-3">
          {routes.slice(0, 5).map((route) => (
            <Link
              key={route.id}
              href={`/routes/${route.id}`}
              className="block rounded-xl border border-border bg-card p-4 hover:border-accent/50 transition-colors"
            >
              <div className="flex items-center justify-between">
                <div>
                  <span className="font-mono text-accent">
                    {route.departure_airport.icao_code || route.departure_airport.ident}
                  </span>
                  <span className="mx-2 text-slate-500">→</span>
                  <span className="font-mono text-accent">
                    {route.destination_airport.icao_code || route.destination_airport.ident}
                  </span>
                </div>
                <span className="text-sm text-slate-400">
                  {route.primary_distance_nm.toFixed(0)} NM · {formatDuration(route.primary_ete_minutes)}
                </span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </PageLayout>
  );
}
