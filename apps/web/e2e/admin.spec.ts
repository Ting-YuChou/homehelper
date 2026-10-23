import { expect, test } from "@playwright/test";

// Admin sign-in exchanges the token for the httpOnly `hh_admin` cookie through the proxy.
const token = process.env.E2E_ADMIN_TOKEN;

test("an admin signs in and sees the review list", async ({ page }) => {
  test.skip(!token, "set E2E_ADMIN_TOKEN to the API's ADMIN_TOKEN");
  await page.goto("/admin/review");
  await page.getByLabel("Admin token").fill(token!);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Review conversations" })).toBeVisible();
});
