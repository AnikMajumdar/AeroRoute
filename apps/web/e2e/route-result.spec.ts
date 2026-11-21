import { test, expect } from "@playwright/test";
import { E2E_ROUTE_ID, mockRouteResult } from "../src/lib/e2eMockRoute";

test.describe("Route result page", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("**/copilot/status", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          enabled: false,
          model: null,
          suggested_questions: ["Why was this route selected?"],
        }),
      });
    });
  });

  test("renders route header and primary stats", async ({ page }) => {
    await page.goto(`/routes/${E2E_ROUTE_ID}`);

    await expect(page.getByTestId("route-result-header")).toBeVisible();
    await expect(page.getByTestId("route-result-header").getByText("KJFK")).toBeVisible();
    await expect(page.getByTestId("route-result-header").getByText("KLAX")).toBeVisible();
    await expect(page.getByText("Primary Score")).toBeVisible();
    await expect(page.getByText("2145 NM")).toBeVisible();
    await expect(page.getByText(/Cruise-altitude GFS winds/i)).toBeVisible();
  });

  test("shows score breakdown with component bars", async ({ page }) => {
    await page.goto(`/routes/${E2E_ROUTE_ID}`);

    const breakdown = page.getByTestId("score-breakdown");
    await expect(breakdown).toBeVisible();
    await expect(breakdown.getByText(/82\/100/)).toBeVisible();
    await expect(breakdown.getByText("time", { exact: false })).toBeVisible();
    await expect(breakdown.getByText("fuel", { exact: false })).toBeVisible();
  });

  test("shows fuel plan breakdown", async ({ page }) => {
    await page.goto(`/routes/${E2E_ROUTE_ID}`);

    const fuel = page.getByTestId("fuel-breakdown");
    await expect(fuel).toBeVisible();
    await expect(fuel.getByText("Trip fuel")).toBeVisible();
    await expect(fuel.getByText("Reserve")).toBeVisible();
    await expect(fuel.getByText("211.3 gal")).toBeVisible();
  });

  test("shows primary vs alternate comparison", async ({ page }) => {
    await page.goto(`/routes/${E2E_ROUTE_ID}`);

    await expect(page.getByText("Primary Route")).toBeVisible();
    await expect(page.getByText("Alternate Route")).toBeVisible();
    await expect(page.getByText("76/100")).toBeVisible();
  });

  test("shows en-route weather checkpoints", async ({ page }) => {
    await page.goto(`/routes/${E2E_ROUTE_ID}`);

    await expect(page.getByText("En-Route Weather Checkpoints")).toBeVisible();
    await expect(page.getByText("MVFR").first()).toBeVisible();
    await expect(page.getByText("Chicago O'Hare")).toBeVisible();
  });

  test("shows diversion airport table", async ({ page }) => {
    await page.goto(`/routes/${E2E_ROUTE_ID}`);

    const table = page.getByTestId("diversion-table");
    await expect(table).toBeVisible();
    await expect(table.getByText("KPHX")).toBeVisible();
    await expect(table.getByText("35.2 NM")).toBeVisible();
    await expect(table.getByText("1,612 NM")).toBeVisible();
    await expect(table.getByText("11,489 ft")).toBeVisible();
  });

  test("shows copilot section with offline state when API disabled", async ({ page }) => {
    await page.goto(`/routes/${E2E_ROUTE_ID}`);

    const copilot = page.getByTestId("route-copilot");
    await expect(copilot).toBeVisible();
    await expect(copilot.getByText("AeroRoute Copilot")).toBeVisible();
    await expect(copilot.getByText("Offline")).toBeVisible();
    await expect(copilot.getByText(/GEMINI_API_KEY/)).toBeVisible();
  });

  test("shows safety disclaimer", async ({ page }) => {
    await page.goto(`/routes/${E2E_ROUTE_ID}`);
    await expect(page.getByText(/not certified flight-planning/i).first()).toBeVisible();
  });

  test("Ask Copilot about hazards brings an offline copilot into view without errors", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (err) => pageErrors.push(err.message));

    await page.goto(`/routes/${E2E_ROUTE_ID}`);
    await page.getByTestId("ask-copilot-hazards").click();

    await expect(page.getByTestId("route-copilot")).toBeInViewport();
    await expect(page.getByTestId("copilot-input")).toHaveCount(0);
    expect(pageErrors).toEqual([]);
  });
});

test.describe("Route result copilot (enabled mock)", () => {
  test("submits a question and shows response", async ({ page }) => {
    await page.route("**/copilot/status", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ enabled: true, model: "gpt-4o-mini" }),
      });
    });

    await page.route(`**/routes/${E2E_ROUTE_ID}/copilot/chat`, async (route) => {
      if (route.request().method() !== "POST") {
        await route.continue();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          answer:
            "The primary route scored 82/100 with balanced preference, favoring direct path and VFR conditions.",
          sources_used: ["route_results", "score_breakdown"],
          safety_note:
            "Educational tool only — not certified flight-planning software.",
        }),
      });
    });

    await page.goto(`/routes/${E2E_ROUTE_ID}`);

    await expect(page.getByTestId("route-copilot").getByText("Online")).toBeVisible();

    await page.getByTestId("copilot-input").fill("Why was this route selected?");
    await page.getByTestId("copilot-submit").click();

    const response = page.getByTestId("copilot-response");
    await expect(response).toBeVisible();
    await expect(response.getByText(/82\/100/)).toBeVisible();
    await expect(response.getByText(/not certified flight-planning/i)).toBeVisible();
  });

  test("Ask Copilot about hazards sends the hazards question automatically", async ({ page }) => {
    let askedQuestion = "";

    await page.route("**/copilot/status", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ enabled: true, model: "gpt-4o-mini" }),
      });
    });

    await page.route(`**/routes/${E2E_ROUTE_ID}/copilot/chat`, async (route) => {
      if (route.request().method() !== "POST") {
        await route.continue();
        return;
      }
      askedQuestion = route.request().postDataJSON().question;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          answer: "No live weather or restriction data is connected for this route.",
          sources_used: ["route_results"],
          safety_note: "Educational tool only — not certified flight-planning software.",
        }),
      });
    });

    await page.goto(`/routes/${E2E_ROUTE_ID}`);
    await expect(page.getByTestId("route-copilot").getByText("Online")).toBeVisible();

    await page.getByTestId("ask-copilot-hazards").click();

    await expect(page.getByTestId("copilot-response")).toBeVisible();
    expect(askedQuestion).toContain("What hazards does this route face");
    await expect(page.getByTestId("copilot-input")).toHaveValue("");
  });

  test("Ask Copilot about hazards sends one request per click", async ({ page }) => {
    let requestCount = 0;

    await page.route("**/copilot/status", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ enabled: true, model: "gpt-4o-mini" }),
      });
    });

    await page.route(`**/routes/${E2E_ROUTE_ID}/copilot/chat`, async (route) => {
      if (route.request().method() !== "POST") {
        await route.continue();
        return;
      }
      requestCount += 1;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          answer: "Hazard summary.",
          sources_used: ["route_results"],
          safety_note: "Educational tool only — not certified flight-planning software.",
        }),
      });
    });

    await page.goto(`/routes/${E2E_ROUTE_ID}`);
    await expect(page.getByTestId("route-copilot").getByText("Online")).toBeVisible();

    await page.getByTestId("ask-copilot-hazards").click();
    await expect(page.getByTestId("copilot-response")).toBeVisible();
    await page.getByTestId("ask-copilot-hazards").click();
    await expect.poll(() => requestCount).toBe(2);
  });
});

test.describe("Route result without weather or delay data", () => {
  const NO_DATA_ROUTE_ID = "e2e-route-no-weather-data";

  test.beforeEach(async ({ page }) => {
    await page.route("**/copilot/status", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ enabled: false, model: null, suggested_questions: [] }),
      });
    });
    // Serve the stored route for the API call only: the page itself is also at .../routes/<id>, and the API is
    // reached directly (NEXT_PUBLIC_API_URL) or through the /api/backend proxy depending on the environment.
    await page.route(`**/routes/${NO_DATA_ROUTE_ID}`, async (route) => {
      const request = route.request();
      const cors = {
        "access-control-allow-origin": "*",
        "access-control-allow-headers": "*",
        "access-control-allow-methods": "GET, OPTIONS",
      };
      if (request.method() === "OPTIONS") {
        await route.fulfill({ status: 204, headers: cors });
        return;
      }
      if (request.method() !== "GET" || request.resourceType() !== "fetch") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: cors,
        body: JSON.stringify({
          ...mockRouteResult,
          id: NO_DATA_ROUTE_ID,
          normalized_score_breakdown: {
            preference: "balanced",
            composite_score: 87.5,
            component_scores: { time: 100, fuel: 100, weather: null, delay: null, diversion: 50 },
            weights: { time: 0.25, fuel: 0.2, weather: 0.2, delay: 0.2, diversion: 0.15 },
            effective_weights: { time: 0.4167, fuel: 0.3333, diversion: 0.25 },
            unavailable_components: ["weather", "delay"],
          },
        }),
      });
    });
  });

  test("shows n/a for components without data and says the composite leaves them out", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (err) => pageErrors.push(err.message));

    await page.goto(`/routes/${NO_DATA_ROUTE_ID}`);

    const breakdown = page.getByTestId("score-breakdown");
    await expect(breakdown).toBeVisible();
    await expect(breakdown.getByText(/88\/100/)).toBeVisible();
    await expect(breakdown.getByText("n/a")).toHaveCount(2);
    await expect(breakdown.getByTestId("score-unavailable-note")).toContainText("No data for weather and delay");
    // components with data are still drawn as numbers
    await expect(breakdown.getByText("50", { exact: true })).toBeVisible();
    expect(pageErrors).toEqual([]);
  });

  test("a route with complete data has no n/a and no note", async ({ page }) => {
    await page.goto(`/routes/${E2E_ROUTE_ID}`);

    const breakdown = page.getByTestId("score-breakdown");
    await expect(breakdown).toBeVisible();
    await expect(breakdown.getByText("n/a")).toHaveCount(0);
    await expect(breakdown.getByTestId("score-unavailable-note")).toHaveCount(0);
  });
});
