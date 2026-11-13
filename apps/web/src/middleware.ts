import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

const isProtectedRoute = createRouteMatcher([
  "/dashboard(.*)",
  "/routes(.*)",
]);

// Local Playwright runs only: ignored when NODE_ENV is "production" (every Vercel deployment), so a stray
// E2E_TEST_MODE variable can never switch authentication off.
const isE2ETestMode = process.env.E2E_TEST_MODE === "true" && process.env.NODE_ENV !== "production";

export default clerkMiddleware(async (auth, req) => {
  if (isE2ETestMode) {
    return;
  }
  if (isProtectedRoute(req)) {
    await auth.protect();
  }
});

export const config = {
  matcher: [
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
    "/__clerk/:path*",
  ],
};
