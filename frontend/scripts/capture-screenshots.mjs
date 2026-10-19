// Capture the README screenshots from a running Stopwatch (real data, not fixtures).
//
//   npm run screenshots                                   # local stack at http://localhost:5173
//   SCREENSHOT_BASE_URL=https://<your-site> npm run screenshots
//
// Writes PNGs to ../docs/images/. Creates one temporary demo account to show a saved commute.
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const BASE = process.env.SCREENSHOT_BASE_URL ?? "http://localhost:5173";
const STOP = process.env.SCREENSHOT_STOP ?? "place-harsq"; // Harvard
const ROUTE = process.env.SCREENSHOT_ROUTE ?? "Red";
const OUT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../docs/images");

async function settle(page) {
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(500); // let charts finish their first paint
}

async function shoot(target, name) {
  const file = path.join(OUT, name);
  await target.screenshot({ path: file });
  console.log(`saved docs/images/${name}`);
}

await mkdir(OUT, { recursive: true });
const browser = await chromium.launch();
try {
  const desktop = await browser.newContext({
    viewport: { width: 1280, height: 900 },
    deviceScaleFactor: 2,
    colorScheme: "light",
  });
  const page = await desktop.newPage();

  // 1. Home: stop search over ~7,400 stops, computed in the browser.
  await page.goto(`${BASE}/`);
  await settle(page);
  await page.getByRole("combobox").first().fill("Harvard");
  await page.getByRole("listbox", { name: "Matching stops" }).waitFor();
  await shoot(page, "home-search.png");

  // 2. Stop page: day x hour heatmap, the selected cell's details and the live panel.
  await page.goto(`${BASE}/s/mbta/${STOP}`);
  await settle(page);
  const reliability = page.locator("section", { has: page.locator("table") }).first();
  await reliability.scrollIntoViewIfNeeded();
  await page.waitForTimeout(1500); // live predictions load from the MBTA API
  await shoot(reliability, "stop-reliability.png");

  // 3. Route page: per-stop reliability along the line.
  await page.goto(`${BASE}/r/mbta/${ROUTE}`);
  await settle(page);
  await shoot(page, "route-page.png");

  // 4. Saved commute with a personal summary (temporary demo account).
  await page.goto(`${BASE}/signin`);
  await settle(page);
  await page.getByRole("button", { name: "Try a demo account" }).click();
  await page.waitForURL("**/commutes");
  await page.getByRole("button", { name: "Add a commute" }).first().click();
  await page.getByLabel("Route").selectOption(ROUTE);
  const direction = page.getByLabel("Direction");
  await direction.selectOption({ index: 1 });
  await page.getByLabel("Stop").selectOption({ label: "Harvard" });
  await page.getByRole("button", { name: "Every day" }).click();
  await page.getByLabel("From", { exact: true }).fill("16:00");
  await page.getByLabel("To", { exact: true }).fill("20:00");
  await page.getByLabel("Name (optional)").fill("Evening Red Line");
  await page.getByRole("button", { name: "Save commute" }).click();
  await page.getByText("Commute saved").waitFor();
  await settle(page);
  await shoot(page, "commute-summary.png");

  // 5. Public data-health page: freshness, gaps and coverage.
  await page.goto(`${BASE}/health`);
  await settle(page);
  await shoot(page, "data-health.png");

  // 6. Mobile stop page.
  const mobile = await browser.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 3,
    isMobile: true,
    hasTouch: true,
    colorScheme: "light",
  });
  const phone = await mobile.newPage();
  await phone.goto(`${BASE}/s/mbta/${STOP}`);
  await settle(phone);
  await shoot(phone, "mobile-stop.png");
} finally {
  await browser.close();
}
