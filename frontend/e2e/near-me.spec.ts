import { expect, test } from "./support/fixtures";

// Harvard Square. Distinctive digits so any leak is unambiguous.
const LAT = 42.373611;
const LON = -71.118956;

test.use({ geolocation: { latitude: LAT, longitude: LON }, permissions: ["geolocation"] });

test("near me lists nearby stops without sending the location anywhere", async ({
  page,
  mocks,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Near me" }).click();

  const list = page.getByRole("list", { name: "Nearest stops" });
  await expect(list).toBeVisible();
  await expect(list.getByRole("listitem")).toHaveCount(10);
  await expect(list.getByRole("listitem").first()).toContainText(/Harvard/);
  await expect(list.getByRole("link", { name: /^Harvard\b.*min walk/ }).first()).toBeVisible();

  // Following a result still leaks nothing.
  await list.getByRole("link").first().click();
  await expect(page).toHaveURL(/\/s\/mbta\//);
  await expect(page.getByRole("table", { name: /^Reliability of/ })).toBeVisible();

  const needles = [String(LAT), String(LON), "42.3736", "71.1189", "42.374", "71.119"];
  expect(mocks.requests.length).toBeGreaterThan(3);
  for (const r of mocks.requests) {
    const haystack = [
      r.url,
      decodeURIComponent(r.url),
      r.body ?? "",
      JSON.stringify(r.headers),
    ].join("\n");
    for (const needle of needles) {
      expect(haystack, `request ${r.method} ${r.url} must not contain the location`).not.toContain(
        needle,
      );
    }
  }
});

test("near me explains a denied permission", async ({ page, mocks: _mocks, context }) => {
  await context.clearPermissions();
  await page.goto("/");
  await page.getByRole("button", { name: "Near me" }).click();
  await expect(page.getByText(/Location permission was denied/)).toBeVisible();
});
