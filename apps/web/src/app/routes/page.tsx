import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import { PageLayout } from "@/components/Layout";
import { SavedRoutesTable } from "@/components/SavedRoutesTable";
import { ButtonLink } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { api } from "@/lib/api";

export default async function SavedRoutesPage() {
  const { userId, getToken } = await auth();
  if (!userId) redirect("/");

  const token = await getToken();
  let routes: Awaited<ReturnType<typeof api.listRoutes>> = [];
  let loadError = "";
  try {
    routes = await api.listRoutes(userId, token);
  } catch (err) {
    loadError = err instanceof Error ? err.message : "Could not load routes";
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

      {loadError && (
        <Card className="mb-6 border-amber-500/25 bg-amber-500/[0.06]" padding="p-4">
          <p className="text-sm text-amber-100/80">{loadError}</p>
        </Card>
      )}

      {routes.length === 0 ? (
        <Card className="text-center" padding="p-12">
          <p className="text-muted">No saved routes yet.</p>
          <ButtonLink href="/routes/new" className="mt-4">
            Plan a route
          </ButtonLink>
        </Card>
      ) : (
        <SavedRoutesTable routes={routes} />
      )}
    </PageLayout>
  );
}
