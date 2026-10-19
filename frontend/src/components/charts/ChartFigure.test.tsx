import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChartFigure } from ".";

/** A stand-in IntersectionObserver whose callback the test fires by hand. */
function stubIntersectionObserver() {
  let notify: ((entries: Partial<IntersectionObserverEntry>[]) => void) | null = null;
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      constructor(callback: (entries: Partial<IntersectionObserverEntry>[]) => void) {
        notify = callback;
      }
      observe() {}
      disconnect() {}
    },
  );
  return (isIntersecting: boolean) => act(() => notify?.([{ isIntersecting }]));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ChartFigure", () => {
  it("holds the chart's space with a skeleton until it nears the viewport", () => {
    const intersect = stubIntersectionObserver();
    render(
      <ChartFigure title="Trend" height="200px">
        <svg data-testid="chart" />
      </ChartFigure>,
    );
    expect(screen.queryByTestId("chart")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Loading chart: Trend");

    intersect(false);
    expect(screen.queryByTestId("chart")).not.toBeInTheDocument();

    intersect(true);
    expect(screen.getByTestId("chart")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("renders straight away without IntersectionObserver", () => {
    vi.stubGlobal("IntersectionObserver", undefined);
    render(
      <ChartFigure title="Trend">
        <svg data-testid="chart" />
      </ChartFigure>,
    );
    expect(screen.getByTestId("chart")).toBeInTheDocument();
  });
});
