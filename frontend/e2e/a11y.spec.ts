import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect, test, type Mocks } from "./support/fixtures";

async function expectNoSeriousViolations(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"])
    .analyze();
  const serious = results.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => ({
      id: v.id,
      impact: v.impact,
      help: v.help,
      targets: v.nodes.map((n) => n.target.join(" ")),
    }));
  expect(serious).toEqual([]);
}

const pages: {
  name: string;
  path: string;
  ready: (page: Page) => Promise<void>;
  setup?: (mocks: Mocks) => Promise<void>;
}[] = [
  {
    name: "home",
    path: "/",
    ready: async (page) => {
      await expect(page.getByRole("button", { name: "Near me" })).toBeEnabled();
    },
  },
  {
    name: "stop",
    path: "/s/mbta/64?route=1&dir=0&cell=wkd-8",
    ready: async (page) => {
      await expect(page.getByTestId("cell-wkd-8")).toBeVisible();
      await expect(page.locator("figure svg").first()).toBeVisible();
      await expect(
        page.getByRole("region", { name: "Right now" }).getByRole("table"),
      ).toBeVisible();
    },
  },
  {
    name: "route",
    path: "/r/mbta/1",
    ready: async (page) => {
      await expect(page.getByRole("tablist")).toBeVisible();
      await expect(
        page
          .getByRole("figure", { name: "Route-level reliability by week" })
          .locator("svg")
          .first(),
      ).toBeVisible();
    },
  },
  {
    name: "commutes",
    path: "/commutes",
    setup: async (mocks) => {
      await mocks.signInDemo();
      mocks.api.seedCommute({
        agency_id: "mbta",
        route_id: "1",
        direction_id: 0,
        stop_id: "64",
        label: "Morning",
        days: ["mon", "tue", "wed", "thu", "fri"],
        window_start: "07:30",
        window_end: "08:30",
      });
    },
    ready: async (page) => {
      await expect(page.getByTestId("commute-summary")).toBeVisible();
      await page.getByRole("button", { name: "Add a commute" }).click();
      await expect(page.getByRole("form", { name: "Add a commute" })).toBeVisible();
    },
  },
  {
    name: "health",
    path: "/health",
    ready: async (page) => {
      await expect(page.getByText("Operational")).toBeVisible();
      await expect(page.locator("figure svg").first()).toBeVisible();
    },
  },
];

for (const p of pages) {
  test(`${p.name} page has no serious or critical axe violations`, async ({ page, mocks }) => {
    if (p.setup) await p.setup(mocks);
    await page.goto(p.path);
    await p.ready(page);
    await expectNoSeriousViolations(page);
  });
}

test("dark mode stays accessible on the stop page", async ({ page, mocks: _mocks }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/s/mbta/place-harsq");
  await expect(page.getByRole("table", { name: /^Reliability of/ })).toBeVisible();
  await expectNoSeriousViolations(page);
});
