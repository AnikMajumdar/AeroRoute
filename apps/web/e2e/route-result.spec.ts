import { test, expect } from "@playwright/test";
import { E2E_ROUTE_ID } from "../src/lib/e2eMockRoute";

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
});
