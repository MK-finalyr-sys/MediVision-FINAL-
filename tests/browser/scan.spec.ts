import { test, expect } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";

test.use({ channel: process.env.TEST_BROWSER_CHANNEL || "msedge", viewport: { width: 1280, height: 900 }, serviceWorkers: "block" });
test.setTimeout(180000);
let identity: Record<string, unknown>;
const ocr = "nitine Hydrochloride Tablets I.P. 10 mg\nA-TRIP-10";

test.beforeAll(async ({ request }) => {
  const response = await request.post("/api/ai/identify", { data: { ocrText: ocr }, timeout: 125000 });
  expect(response.ok()).toBeTruthy();
  identity = await response.json();
  expect(identity.salt).toBe("Amitriptyline Hydrochloride");
  expect(identity.verificationStatus).toBe("candidate-needs-confirmation");
  mkdirSync("test-results", { recursive: true });
  writeFileSync("test-results/actual-identification.json", JSON.stringify(identity, null, 2));
});

async function scan(page: import("@playwright/test").Page, text = ocr) {
  await page.goto("/");
  await page.getByRole("link", { name: "Smart scan", exact: true }).first().click();
  await page.getByText("Enter or correct package text", { exact: true }).click();
  await page.getByLabel("Text read from the medicine package").fill(text);
  await page.getByRole("button", { name: "Identify package text", exact: true }).click();
}
async function mock(page: import("@playwright/test").Page, body: unknown, status = 200) {
  await page.route("**/api/ai/identify", route => route.fulfill({ status, json: body }));
  await page.route("**/api/ai/candidates", route => route.fulfill({ json: { found: true, candidates: [{ salt: "Amitriptyline", probability: 0.95, basis: "indian-brand-index" }] } }));
}

test("real backend OCR fixture opens an unconfirmed identity and confirmation enables profile and assistant", async ({ page }) => {
  await scan(page);
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible({ timeout: 130000 });
  await expect(dialog).toContainText("Amitriptyline Hydrochloride");
  await expect(dialog).toContainText("10 mg");
  await expect(dialog).toContainText("Tablet");
  await expect(dialog).toContainText("Confirm proposed medicine");
  await expect(dialog).toContainText("Online product verification is unavailable");
  await expect(dialog.getByRole("button", { name: "Save to Cabinet", exact: true })).toBeDisabled();
  await expect(dialog.getByRole("button", { name: "Continue with AI Assistant" })).toHaveCount(0);
  await page.screenshot({ path: "test-results/scan-unconfirmed.png", fullPage: true });
  await dialog.getByRole("button", { name: "I confirm the name" }).click();
  await expect(dialog).toContainText("Package identity confirmed by you");
  await dialog.getByRole("button", { name: "Save to Cabinet", exact: true }).click();
  await dialog.getByRole("button", { name: "Continue with AI Assistant" }).first().click();
  await expect(page.locator("main")).toContainText("A-TRIP-10");
  await page.getByRole("link", { name: /^My medicines/ }).first().click();
  await expect(page.locator("main")).toContainText("A-TRIP-10");
  await page.getByRole("button", { name: "View medicine information" }).click();
  await expect(page.getByRole("dialog")).toContainText("Package identity confirmed by you");
});

test("conflict preserves observed formulation and blocks confirmation", async ({ page }) => {
  await mock(page, { ...identity, strength: "25 mg", form: "Injection", verificationStatus: "conflicting-identification", requiresManualReview: true, conflicts: [
    { field: "strength", observed: "25 mg", proposed: "10 mg" }, { field: "form", observed: "Injection", proposed: "Tablet" },
  ] });
  await scan(page, "A-TRIP-10 25 mg Injection");
  await expect(page.locator("main").getByRole("alert")).toContainText("Manual review required");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.locator(".scan-ai-identified-card")).toContainText("25 mg");
  await expect(page.locator(".scan-ai-identified-card")).toContainText("Injection");
  await page.getByRole("button", { name: "View Medicine Details" }).click();
  await expect(page.getByRole("dialog")).toContainText("catalog proposes 10 mg");
  await expect(page.getByRole("button", { name: "I confirm the name" })).toHaveCount(0);
});

test("no match is shown without catalog substitution", async ({ page }) => {
  await mock(page, { found: false, salt: null, strength: null, form: null, verificationStatus: "none", note: "NO_MATCH" });
  await scan(page, "unknown medicine");
  await expect(page.locator("main").getByRole("alert")).toContainText("No medicine match found");
  await expect(page.locator(".scan-ai-identified-card")).toHaveCount(0);
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

for (const [label, body, status] of [
  ["timeout", { error: { code: "timeout" } }, 504],
  ["unavailable", {}, 503],
  ["parse", { ...{ found: true }, salt: 42 }, 200],
] as const) {
  test(label + " produces a visible error without marking Matching complete", async ({ page }) => {
    await mock(page, body, status);
    await scan(page);
    await expect(page.locator("main").getByRole("alert")).toContainText("[" + label + "]");
    await expect(page.locator(".pipeline-stages .done")).toHaveCount(0);
    await expect(page.getByRole("dialog")).toHaveCount(0);
  });
}

test("disagreeing candidates never auto-open an identification", async ({ page }) => {
  await mock(page, identity);
  await page.route("**/api/ai/candidates", route => route.fulfill({ json: { found: true, candidates: [{ salt: "Paracetamol", probability: 0.99, basis: "salt-fuzzy" }] } }));
  await scan(page);
  await expect(page.locator(".scan-ai-identified-card")).toContainText("Amitriptyline Hydrochloride");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});



for (const photo of [{ id: "pan-40", salt: /pantoprazole/i, strength: "40 mg" }, { id: "dolo-650", salt: /paracetamol/i, strength: "650 mg" }]) {
test(`real ${photo.id} photograph reaches OCR, backend and an unconfirmed medicine popup`, async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Smart scan", exact: true }).first().click();
  const identificationResponse = page.waitForResponse(response => response.url().endsWith("/api/ai/identify"), { timeout: 150000 });
  await page.getByTestId("gallery-input").setInputFiles(`tests/fixtures/${photo.id}.jpg`);
  const response = await identificationResponse;
  expect(response.ok()).toBeTruthy();
  const body = await response.json();
  writeFileSync(`test-results/${photo.id}-identification.json`, JSON.stringify(body, null, 2));
  expect(body.found).toBe(true);
  expect(body.salt).toMatch(photo.salt);
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible({ timeout: 130000 });
  await expect(dialog).toContainText(photo.salt);
  await expect(dialog).toContainText(photo.strength);
  await expect(dialog).toContainText("Tablet");
  await expect(dialog).toContainText("Confirm proposed medicine");
  await expect(dialog.getByRole("button", { name: "Save to Cabinet", exact: true })).toBeDisabled();
  await page.screenshot({ path: `test-results/${photo.id}-confirmation.png`, fullPage: true });
});
}
