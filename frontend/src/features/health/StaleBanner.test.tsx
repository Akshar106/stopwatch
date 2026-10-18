import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import type { Health } from "../../lib/types";
import { agency, fixtures } from "../../test/fixtures";
import { StaleBanner } from "./StaleBanner";

function renderWithHealth(health: Health) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  client.setQueryData(["manifest"], fixtures.manifest);
  client.setQueryData(["health", agency.paths.health], health);
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <StaleBanner />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("StaleBanner", () => {
  it("is hidden while collection is healthy", () => {
    const now = new Date().toISOString();
    renderWithHealth({ ...fixtures.health, generated_at: now, last_success_at: now });
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("appears site-wide when the agency's data is stale", () => {
    const now = new Date().toISOString();
    const old = new Date(Date.now() - 40 * 60_000).toISOString();
    renderWithHealth({
      ...fixtures.health,
      status: "stale",
      generated_at: now,
      last_success_at: old,
    });
    const banner = screen.getByRole("status");
    expect(banner).toHaveTextContent("MBTA data is stale.");
    expect(banner).toHaveTextContent("40 min ago");
    expect(screen.getByRole("link", { name: "Data health" })).toHaveAttribute("href", "/health");
  });

  it("treats a health file that stopped updating as stale even if it says ok", () => {
    const old = new Date(Date.now() - 60 * 60_000).toISOString();
    renderWithHealth({ ...fixtures.health, status: "ok", generated_at: old, last_success_at: old });
    expect(screen.getByRole("status")).toHaveTextContent("MBTA data is stale.");
  });
});
