import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import { RouteResultPageClient } from "@/components/RouteResultPageClient";

export default async function RouteResultPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { userId } = await auth();
  // Local Playwright runs only; never honoured in production builds.
  const e2eUserId =
    process.env.E2E_TEST_MODE === "true" && process.env.NODE_ENV !== "production" ? "e2e-test-user" : null;
  if (!userId && !e2eUserId) redirect("/");

  const { id } = await params;
  return <RouteResultPageClient routeId={id} />;
}
