import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { cellLabel, hasEnoughData, type CellKey } from "../lib/cells";
import type { HeatmapMetric } from "../lib/color";
import type { Cell } from "../lib/types";
import { Heatmap, HeatmapLegend } from "./Heatmap";

const cell = (over: Partial<Cell>): Cell => ({
  day: "wkd",
  hour: 8,
  n: 74,
  p50_s: 210,
  p90_s: 640,
  on_time_pct: 61.2,
  early_pct: 4,
  canceled: 2,
  skipped: 0,
  sched_headway_s: 600,
  ewt_s: 95,
  hist: [3, 18, 22, 9, 12, 7, 3],
  ...over,
});

const CELLS: Cell[] = [
  cell({ day: "wkd", hour: 7, p50_s: 90, on_time_pct: 88 }),
  cell({ day: "wkd", hour: 8 }),
  cell({
    day: "sat",
    hour: 8,
    n: 5,
    p50_s: null,
    p90_s: null,
    on_time_pct: null,
    early_pct: null,
    ewt_s: null,
  }),
  cell({ day: "sun", hour: 7, p50_s: -90, on_time_pct: 70 }),
  cell({ day: "wkd", hour: 0, p50_s: 30 }),
];

function Harness({
  metric = "p50",
  onSelect = vi.fn(),
}: {
  metric?: HeatmapMetric;
  onSelect?: (c: Cell) => void;
}) {
  const [selected, setSelected] = useState<CellKey | null>({ day: "wkd", hour: 8 });
  return (
    <Heatmap
      cells={CELLS}
      metric={metric}
      minSamples={8}
      selected={selected}
      onSelect={(c) => {
        setSelected({ day: c.day, hour: c.hour });
        onSelect(c);
      }}
      caption="Route 1 at Mass Ave"
    />
  );
}

describe("Heatmap", () => {
  it("prints each cell's value so color is not the only encoding", () => {
    render(<Harness />);
    expect(screen.getByTestId("cell-wkd-8")).toHaveTextContent("+3.5");
    expect(screen.getByTestId("cell-sun-7")).toHaveTextContent("−1.5");
    expect(
      screen.getByRole("button", {
        name: "+3.5 min: Weekdays, 8 AM–9 AM, typical delay 3.5 minutes late, 61% on time, 74 arrivals",
      }),
    ).toBeInTheDocument();
  });

  it("shows on-time percentages in on-time mode", () => {
    render(<Harness metric="on_time" />);
    expect(screen.getByTestId("cell-wkd-7")).toHaveTextContent("88%");
    expect(screen.getByTestId("cell-wkd-7")).toHaveAccessibleName(
      /^88% on time: Weekdays, 7 AM–8 AM/,
    );
  });

  it("renders thin cells as 'not enough data' in text, not only as a pattern", () => {
    render(<Harness />);
    const thin = screen.getByTestId("cell-sat-8");
    expect(thin).toHaveTextContent("—");
    expect(thin).toHaveAccessibleName(
      /Saturday, 8 AM–9 AM: not enough data \(5 observed arrivals, need 8\)/,
    );
    expect(thin).not.toHaveStyle({ background: expect.any(String) as string });
    expect(hasEnoughData(CELLS[2]!, 8)).toBe(false);
    expect(cellLabel(CELLS[2]!, 8)).toMatch(/not enough data/);
  });

  it("marks hours without service and orders rows by service day (12 AM last)", () => {
    render(<Harness />);
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getByRole("rowheader").textContent)).toEqual([
      "7 AM",
      "8 AM",
      "12 AM",
    ]);
    expect(within(rows[0]!).getAllByText("No scheduled service")).toHaveLength(1);
  });

  it("has a single tab stop and moves selection with the arrow keys", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<Harness onSelect={onSelect} />);
    const buttons = screen.getAllByRole("button");
    expect(buttons.filter((b) => b.tabIndex === 0)).toHaveLength(1);
    const selected = screen.getByTestId("cell-wkd-8");
    expect(selected).toHaveAttribute("aria-pressed", "true");

    selected.focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByTestId("cell-sat-8")).toHaveFocus();
    expect(onSelect).toHaveBeenLastCalledWith(expect.objectContaining({ day: "sat", hour: 8 }));

    await user.keyboard("{ArrowUp}");
    // sat-7 has no service; the grid skips upward to the next cell in that column, if any → stays put.
    expect(screen.getByTestId("cell-sat-8")).toHaveFocus();

    await user.keyboard("{ArrowLeft}{ArrowUp}");
    expect(screen.getByTestId("cell-wkd-7")).toHaveFocus();
    expect(screen.getByTestId("cell-wkd-7")).toHaveAttribute("aria-pressed", "true");
  });

  it("explains an empty grid", () => {
    render(
      <Heatmap
        cells={[]}
        metric="p50"
        minSamples={8}
        selected={null}
        onSelect={vi.fn()}
        caption="x"
      />,
    );
    expect(screen.getByText(/No scheduled service/)).toBeInTheDocument();
  });
});

describe("HeatmapLegend", () => {
  it("lists every bin plus the thin-data and no-service keys", () => {
    render(<HeatmapLegend metric="p50" minSamples={8} />);
    expect(screen.getByText("Not enough data (fewer than 8 arrivals)")).toBeInTheDocument();
    expect(screen.getByText("No scheduled service")).toBeInTheDocument();
    expect(screen.getByText("+10 min or more")).toBeInTheDocument();
  });
});
