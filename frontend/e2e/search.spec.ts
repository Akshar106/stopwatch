import { expect, test } from "./support/fixtures";

test("search → stop page → heatmap and cell details", async ({ page, mocks }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { level: 1, name: "How reliable is your stop?" }),
  ).toBeVisible();

  const search = page.getByRole("combobox", { name: "Find a stop" });
  await search.fill("newbury");
  const option = page.getByRole("option", { name: /Massachusetts Ave @ Newbury St/ });
  await expect(option).toBeVisible();
  await search.press("ArrowDown");
  await search.press("Enter");

  await expect(page).toHaveURL(/\/s\/mbta\/64$/);
  await expect(
    page.getByRole("heading", { level: 1, name: "Massachusetts Ave @ Newbury St" }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "Route 1 toward Harvard Square" })).toBeVisible();

  // Heatmap: a real table with day-type columns, values printed in cells.
  const grid = page.getByRole("table", { name: /Reliability of Route 1 toward Harvard Square/ });
  await expect(grid).toBeVisible();
  await expect(grid.getByRole("columnheader", { name: "Weekday" })).toBeVisible();
  const cell = page.getByTestId("cell-wkd-8");
  await expect(cell).toHaveText(/^[+−]\d/);

  await cell.click();
  await expect(page).toHaveURL(/cell=wkd-8/);
  const detail = page.getByRole("region", { name: "Weekdays, 8 AM–9 AM" });
  await expect(detail.getByText("Typical delay (p50)")).toBeVisible();
  await expect(detail.getByText("Excess wait time", { exact: true })).toBeVisible();
  // The delay histogram (lazy Observable Plot chunk) renders an SVG.
  await expect(detail.locator("figure svg").first()).toBeVisible();

  // Thin-data cells say so.
  await page.getByTestId("cell-sun-7").click();
  await expect(page.getByTestId("not-enough-data")).toContainText("Not enough data");

  // Toggle the metric.
  await page.getByText("% on time", { exact: true }).click();
  await expect(page.getByTestId("cell-wkd-8")).toHaveText(/\d+%/);

  // Live panel: browser → MBTA directly (mocked), never Stopwatch servers.
  const live = page.getByRole("region", { name: "Right now" });
  await expect(live.getByRole("cell", { name: "Canceled" })).toBeVisible();
  // Anonymous browsing makes no calls to the Stopwatch API at all.
  expect(mocks.requests.filter((r) => new URL(r.url).pathname.startsWith("/api/"))).toEqual([]);
});

test("station search groups platforms and the route page compares stops", async ({
  page,
  mocks,
}) => {
  await page.goto("/");
  await page.getByRole("combobox", { name: "Find a stop" }).fill("park");
  await page.getByRole("option", { name: /Park Street/ }).click();
  await expect(page).toHaveURL(/\/s\/mbta\/place-pktrm$/);
  await expect(page.getByText("Station", { exact: true })).toBeVisible();

  await page.getByRole("radio", { name: "Toward Alewife" }).check();
  await expect(page.getByRole("heading", { name: "Red Line toward Alewife" })).toBeVisible();
  await page.getByRole("link", { name: "Compare stops on this route" }).click();

  await expect(page).toHaveURL(/\/r\/mbta\/Red\?dir=1&stop=70076/);
  await expect(page.getByRole("heading", { level: 1, name: "Red Line" })).toBeVisible();
  const tabs = page.getByRole("tablist", { name: "Direction" });
  await expect(tabs.getByRole("tab", { name: "Toward Alewife" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(page.getByRole("button", { name: /Park Street/, pressed: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "At Park Street" })).toBeVisible();
  await expect(
    page.getByRole("figure", { name: "Route-level reliability by week" }).locator("svg").first(),
  ).toBeVisible();
  await expect(page.getByRole("img", { name: /of scheduled trips observed/ })).toBeVisible();

  // Live predictions were requested from the MBTA, not from Stopwatch.
  expect(mocks.requests.some((r) => r.url.startsWith("https://api-v3.mbta.com/predictions"))).toBe(
    true,
  );
  expect(mocks.requests.some((r) => new URL(r.url).pathname.startsWith("/api/"))).toBe(false);
});
