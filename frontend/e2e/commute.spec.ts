import { expect, test } from "./support/fixtures";

test("demo sign-in → create a commute → personal summary → delete", async ({ page, mocks }) => {
  await page.goto("/signin?next=%2Fcommutes");
  await page.getByRole("button", { name: "Try a demo account" }).click();

  await expect(page).toHaveURL(/\/commutes$/);
  await expect(page.getByRole("heading", { level: 1, name: "Your commutes" })).toBeVisible();
  await expect(page.getByText("0 of 3 commutes used (demo account)")).toBeVisible();

  await page.getByRole("button", { name: "Add a commute" }).click();
  const form = page.getByRole("form", { name: "Add a commute" });
  await form.getByLabel("Route", { exact: true }).selectOption("1");
  await form
    .getByLabel("Direction", { exact: true })
    .selectOption({ label: "Toward Harvard Square" });
  await form
    .getByLabel("Stop", { exact: true })
    .selectOption({ label: "Massachusetts Ave @ Newbury St" });
  await expect(form.getByRole("checkbox", { name: "Mon" })).toBeChecked();
  await expect(form.getByRole("checkbox", { name: "Sat" })).not.toBeChecked();
  await form.getByLabel("From", { exact: true }).fill("07:30");
  await form.getByLabel("To", { exact: true }).fill("08:30");
  await form.getByLabel("Name (optional)", { exact: true }).fill("Morning to work");
  await form.getByRole("button", { name: "Save commute" }).click();

  await expect(page.getByRole("status").filter({ hasText: "Commute saved." })).toBeVisible();
  const card = page.getByRole("article", { name: "Morning to work" });
  await expect(card).toBeVisible();
  await expect(card.getByText("Mon–Fri · 7:30 AM–8:30 AM")).toBeVisible();
  const summary = card.getByTestId("commute-summary");
  await expect(summary.getByText("Typical delay")).toBeVisible();
  await expect(summary.getByText(/^≈ [+−]\d/).first()).toBeVisible();
  await expect(summary.getByText("Route-level")).toBeVisible();
  await expect(page.getByText("1 of 3 commutes used (demo account)")).toBeVisible();

  // The create carried the CSRF token, X-Requested-With and an Idempotency-Key.
  const create = mocks.requests.find(
    (r) => r.method === "POST" && r.url.endsWith("/api/v1/commutes"),
  );
  expect(create?.headers["x-requested-with"]).toBe("stopwatch");
  expect(create?.headers["x-csrf-token"]).toBeTruthy();
  expect(create?.headers["idempotency-key"]).toMatch(/[0-9a-f-]{20,}/);

  // The home page shows the same commute.
  await page.getByRole("link", { name: "Stopwatch" }).click();
  await expect(page.getByRole("heading", { name: "Your commutes" })).toBeVisible();
  await expect(page.getByRole("article", { name: "Morning to work" })).toBeVisible();

  await page.getByRole("link", { name: "Commutes", exact: true }).click();
  await page.getByRole("button", { name: "Delete Morning to work" }).click();
  const dialog = page.getByRole("dialog", { name: "Delete this commute?" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Cancel" })).toBeFocused();
  await dialog.getByRole("button", { name: "Delete commute" }).click();

  await expect(dialog).toBeHidden();
  await expect(page.getByRole("status").filter({ hasText: "Commute deleted." })).toBeVisible();
  await expect(page.getByRole("article", { name: "Morning to work" })).toHaveCount(0);
  await expect(page.getByText("No commutes yet")).toBeVisible();
});

test("commute form explains validation and the demo limit", async ({ page, mocks }) => {
  await mocks.signInDemo();
  await page.goto("/commutes");
  for (let i = 0; i < 3; i++) {
    await page.getByRole("button", { name: "Add a commute" }).click();
    const form = page.getByRole("form", { name: "Add a commute" });
    if (i === 0) {
      await form.getByRole("button", { name: "Save commute" }).click();
      await expect(form.getByText("Choose a route.")).toBeVisible();
      await expect(form.getByLabel("Route", { exact: true })).toBeFocused();
    }
    await form.getByLabel("Route", { exact: true }).selectOption("Red");
    await form.getByLabel("Direction", { exact: true }).selectOption({ index: 1 });
    await form.getByLabel("Stop", { exact: true }).selectOption({ index: i + 1 });
    await form.getByRole("button", { name: "Save commute" }).click();
    await expect(page.getByText(`${i + 1} of 3 commutes used`)).toBeVisible();
  }
  await expect(page.getByRole("button", { name: "Add a commute" })).toBeDisabled();
  await expect(page.getByText(/reached the limit of 3 for demo accounts/)).toBeVisible();
});
