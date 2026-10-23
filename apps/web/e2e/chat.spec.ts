import { expect, type Page, test } from "@playwright/test";

// The main flow through the web app's /v1 proxy: sign in, send a message, and get a streamed
// reply. Works against the stub agent (CI) and the real journey agent (a deploy candidate).
// A demo with an access code needs it in E2E_ACCESS_CODE.

async function openLogin(page: Page) {
  await page.goto("/login");
  const code = process.env.E2E_ACCESS_CODE;
  if (code) await page.getByLabel("Access code").fill(code);
}

test("a demo user gets a streamed reply", async ({ page }) => {
  await openLogin(page);
  await page.getByRole("button", { name: /Alex Kim/ }).click();
  await expect(page).toHaveURL(/\/chat/);

  await page.getByLabel("Message").fill("My dishwasher won't start");
  await page.getByRole("button", { name: "Send" }).click();

  // Feedback buttons appear once the reply's `message.completed` event has arrived.
  await expect(page.getByRole("button", { name: "Helpful" }).first()).toBeVisible();
  await expect(page).toHaveURL(/\/chat\/conv_/);
});

test("a guest can chat without a demo profile", async ({ page }) => {
  await openLogin(page);
  await page.getByRole("button", { name: "Continue as a guest" }).click();
  await expect(page).toHaveURL(/\/chat/);

  await page.getByLabel("Message").fill("How do I clean my dryer's lint filter?");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByRole("button", { name: "Helpful" }).first()).toBeVisible();
});
