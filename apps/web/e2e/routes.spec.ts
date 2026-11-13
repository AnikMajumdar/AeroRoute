import { test, expect } from "@playwright/test";

test.describe("Landing page", () => {
  test("shows the AeroRoute brand, hero and safety disclaimer", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Plan smarter routes");
    // The brand text also appears in headings, copy and the footer, so pick the first exact match.
    await expect(page.getByText("AeroRoute", { exact: true }).first()).toBeVisible();
    await expect(page.getByText(/educational tool/i).first()).toBeVisible();
    await expect(page.getByText(/not certified flight-planning/i).first()).toBeVisible();
  });
});

test.describe("Route form", () => {
  // The planning form needs a Clerk session, which E2E mode does not provide: signed-out visitors go home.
  test("new route page sends signed-out visitors back to the landing page", async ({ page }) => {
    await page.goto("/routes/new");
    await expect(page).toHaveURL("/");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Plan smarter routes");
  });
});
