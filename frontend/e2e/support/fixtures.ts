import { test as base, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import type { RouteDetail } from "../../src/lib/types";
import {
  createDataResolver,
  ROUTE_DETAIL_FILES,
  routeStopsFrom,
} from "../../src/test/mocks/fixtures";
import { mockPredictions } from "../../src/test/mocks/mbta";
import { MockApi, type MockApiOptions } from "../../src/test/mocks/mockApi";

/**
 * Every test runs against `vite preview` with all network mocked via page.route:
 *   /data/v1/**            → fixture JSON (src/test/fixtures)
 *   /api/v1/**             → an in-memory MockApi that enforces the real header rules
 *   https://api-v3.mbta.com → fake live predictions
 * The fixture also fails the test on any console error or uncaught page error (CSP
 * violations included, since preview serves the production CSP).
 */

const FIXTURE_DIR = new URL("../../src/test/fixtures/", import.meta.url);
const load = (file: string): unknown =>
  JSON.parse(readFileSync(new URL(file, FIXTURE_DIR), "utf8"));
const resolveData = createDataResolver(load);
const routeStops = routeStopsFrom(ROUTE_DETAIL_FILES.map((f) => load(f) as RouteDetail));

export interface Mocks {
  api: MockApi;
  /** Every request the page made (URL, method, headers, body), for privacy assertions. */
  requests: { url: string; method: string; headers: Record<string, string>; body: string | null }[];
  /** Mark the browser as "probably signed in" so the app asks GET /me on load. */
  signInDemo(): Promise<void>;
}

export async function installMocks(
  page: Page,
  options: Partial<MockApiOptions> = {},
): Promise<Mocks> {
  const api = new MockApi({ routeStops, ...options });
  const requests: Mocks["requests"] = [];
  page.on("request", (req) => {
    requests.push({
      url: req.url(),
      method: req.method(),
      headers: req.headers(),
      body: req.postData(),
    });
  });

  await page.route("**/data/v1/**", async (route) => {
    const body = resolveData(new URL(route.request().url()).pathname);
    if (body === undefined) await route.fulfill({ status: 404, body: "" });
    else
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
  });

  await page.route("**/api/v1/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const raw = req.postData();
    const out = api.handle({
      method: req.method(),
      path: url.pathname.replace(/^\/api\/v1/, ""),
      query: url.searchParams,
      headers: await req.allHeaders(),
      body: raw ? (JSON.parse(raw) as unknown) : undefined,
    });
    await route.fulfill({
      status: out.status,
      headers: out.headers ?? {},
      body: out.body === undefined ? "" : JSON.stringify(out.body),
    });
  });

  await page.route("https://api-v3.mbta.com/**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/vnd.api+json",
      headers: { "access-control-allow-origin": "*" },
      body: JSON.stringify(mockPredictions(new URL(route.request().url()))),
    });
  });

  return {
    api,
    requests,
    async signInDemo() {
      api.signInDemo();
      await page.addInitScript(() => window.localStorage.setItem("stopwatch.session-hint", "1"));
    },
  };
}

export const test = base.extend<{ mocks: Mocks }>({
  mocks: async ({ page }, use) => {
    const problems: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") problems.push(`console: ${msg.text()}`);
    });
    page.on("pageerror", (err) => problems.push(`pageerror: ${err.message}`));
    const mocks = await installMocks(page);
    await use(mocks);
    expect(problems, "no console errors or uncaught exceptions").toEqual([]);
  },
});

export { expect };
