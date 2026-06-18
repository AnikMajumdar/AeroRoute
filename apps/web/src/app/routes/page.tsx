import { auth } from "@clerk/nextjs/server";
import Link from "next/link";
import { redirect } from "next/navigation";
import { PageLayout } from "@/components/Layout";
import { Badge } from "@/components/ui/Badge";
import { ButtonLink } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { api, formatDuration } from "@/lib/api";

export default async function SavedRoutesPage() {
  const { userId, getToken } = await auth();
  if (!userId) redirect("/");

  const token = await getToken();
  let routes: Awaited<ReturnType<typeof api.listRoutes>> = [];
  try {
    routes = await api.listRoutes(userId, token);
  } catch {
    // API unavailable
  }

  return (
    <PageLayout
      title="Saved Routes"
      subtitle="Browse and reopen your calculated route plans."
      showDisclaimer={false}
    >
      <div className="mb-8">
        <ButtonLink href="/routes/new">+ New Route</ButtonLink>
      </div>

      {routes.length === 0 ? (
        <Card className="text-center" padding="p-12">
          <p className="text-muted">No saved routes yet.</p>
          <ButtonLink href="/routes/new" className="mt-4">
            Plan a route
          </ButtonLink>
        </Card>
      ) : (
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
                    className="border-b border-white/5 transition-colors last:border-0 hover:bg-white/[0.03]"
                  >
                    <td className="px-5 py-4">
                      <Link
                        href={`/routes/${route.id}`}
                        className="font-mono font-medium text-sky-300 hover:text-sky-200"
                      >
                        {route.departure_airport.icao_code || route.departure_airport.ident} →{" "}
                        {route.destination_airport.icao_code || route.destination_airport.ident}
                      </Link>
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
      )}
    </PageLayout>
  );
}
