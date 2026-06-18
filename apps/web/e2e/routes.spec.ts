import { test, expect } from "@playwright/test";

test.describe("Landing page", () => {
  test("shows AeroRoute title and disclaimer", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("AeroRoute")).toBeVisible();
    await expect(page.getByText(/Educational Tool/)).toBeVisible();
    await expect(page.getByText(/not certified flight-planning/i)).toBeVisible();
  });
});

test.describe("Route form", () => {
  test("new route page shows form fields", async ({ page }) => {
    // This test requires auth — skip if redirected to sign-in
    await page.goto("/routes/new");
    const url = page.url();
    if (url.includes("sign-in") || url === "http://localhost:3000/") {
      test.skip();
      return;
    }
    await expect(page.getByText("Plan New Route")).toBeVisible();
    await expect(page.getByText("Departure Airport")).toBeVisible();
    await expect(page.getByText("Destination Airport")).toBeVisible();
    await expect(page.getByText("Calculate Route")).toBeVisible();
  });
});
