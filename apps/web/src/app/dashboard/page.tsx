import { auth } from "@clerk/nextjs/server";
import Link from "next/link";
import { redirect } from "next/navigation";
import { DashboardRouteList } from "@/components/DashboardRouteList";
import { PageLayout } from "@/components/Layout";
import { ButtonLink } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { StatCard } from "@/components/ui/StatCard";
import { api } from "@/lib/api";

export default async function DashboardPage() {
  const { userId, getToken } = await auth();
  if (!userId) redirect("/");

  const token = await getToken();
  let routes: Awaited<ReturnType<typeof api.listRoutes>> = [];
  try {
    routes = await api.listRoutes(userId, token);
  } catch {
    // API may be unavailable
  }

  return (
    <PageLayout
      title="Dashboard"
      subtitle="Your saved routes and quick actions in one place."
      showDisclaimer={false}
    >
      <div className="mb-10 grid gap-5 md:grid-cols-3">
        <StatCard
          title="Saved Routes"
          value={String(routes.length)}
          icon="📁"
          highlight
        />
        <Card className="md:col-span-2" padding="p-6">
          <p className="text-xs font-medium uppercase tracking-wider text-muted">Quick actions</p>
          <div className="mt-4 flex flex-wrap gap-3">
            <ButtonLink href="/routes/new">Plan New Route</ButtonLink>
            <ButtonLink href="/routes" variant="outline">
              View All Routes
            </ButtonLink>
          </div>
        </Card>
      </div>

      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-xl font-semibold tracking-tight">Recent routes</h2>
        {routes.length > 0 && (
          <Link href="/routes" className="text-sm text-sky-400 hover:text-sky-300">
            View all →
          </Link>
        )}
      </div>

      {routes.length === 0 ? (
        <Card className="text-center" padding="p-12">
          <p className="text-muted">No routes yet.</p>
          <ButtonLink href="/routes/new" className="mt-4">
            Plan your first route
          </ButtonLink>
        </Card>
      ) : (
        <DashboardRouteList routes={routes} />
      )}
    </PageLayout>
  );
}
