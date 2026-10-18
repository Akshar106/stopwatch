import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { buildSearchIndex, type Place } from "../../lib/search";
import { fixtures } from "../../test/fixtures";
import { StopSearch } from "./StopSearch";

const index = buildSearchIndex(fixtures.stops.stops);
const routesById = new Map(fixtures.routes.routes.map((r) => [r.id, r]));

function setup(onSelect?: (p: Place) => void) {
  const router = createMemoryRouter(
    [
      {
        path: "/",
        element: (
          <StopSearch agencyId="mbta" index={index} routesById={routesById} onSelect={onSelect} />
        ),
      },
      { path: "/s/:agency/:stopId", element: <p>Stop page</p> },
    ],
    { initialEntries: ["/"] },
  );
  render(<RouterProvider router={router} />);
  return router;
}

describe("StopSearch combobox", () => {
  it("is a labelled combobox that lists matches with their routes", async () => {
    const user = userEvent.setup();
    setup();
    const input = screen.getByRole("combobox", { name: "Find a stop" });
    expect(input).toHaveAttribute("aria-expanded", "false");
    await user.type(input, "harv");
    expect(input).toHaveAttribute("aria-expanded", "true");
    const options = screen.getAllByRole("option");
    expect(options[0]).toHaveTextContent("Harvard");
    expect(options[0]).toHaveTextContent("Red Line");
    expect(options[1]).toHaveTextContent("Harvard Upper Busway");
    expect(screen.getByRole("status")).toHaveTextContent("2 stops found");
  });

  it("supports arrow keys + Enter and navigates to the stop page", async () => {
    const user = userEvent.setup();
    const router = setup();
    const input = screen.getByRole("combobox");
    await user.type(input, "newbury");
    await user.keyboard("{ArrowDown}");
    const active = screen.getByRole("option", { selected: true });
    expect(input).toHaveAttribute("aria-activedescendant", active.id);
    await user.keyboard("{Enter}");
    expect(router.state.location.pathname).toBe("/s/mbta/64");
  });

  it("calls onSelect instead of navigating when provided, and Escape closes the list", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    setup(onSelect);
    const input = screen.getByRole("combobox");
    await user.type(input, "park");
    await user.keyboard("{Escape}");
    expect(input).toHaveAttribute("aria-expanded", "false");
    await user.keyboard("{ArrowDown}{Enter}");
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: "place-pktrm" }));
  });

  it("says when nothing matches", async () => {
    const user = userEvent.setup();
    setup();
    await user.type(screen.getByRole("combobox"), "zzzz");
    expect(screen.getByText(/No stops match “zzzz”/, { selector: "p.small" })).toBeInTheDocument();
  });
});
