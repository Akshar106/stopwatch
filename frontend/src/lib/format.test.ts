import { describe, expect, it } from "vitest";
import { bucketLabels } from "./cells";
import { contrastRatio, delayBin, normalizeHex, onTimeBin, routeColors } from "./color";
import {
  describeDelay,
  formatDays,
  formatDelay,
  formatDuration,
  formatHHMM,
  hourLabel,
  routeFullLabel,
  routeName,
} from "./format";

describe("format", () => {
  it("formats signed delays", () => {
    expect(formatDelay(210)).toBe("+3.5 min");
    expect(formatDelay(-45)).toBe("−0.8 min");
    expect(formatDelay(900)).toBe("+15 min");
    expect(formatDelay(10)).toBe("+0.2 min");
    expect(formatDelay(1)).toBe("0 min");
    expect(formatDelay(null)).toBe("—");
    expect(formatDelay(120, { unit: false })).toBe("+2.0");
    expect(describeDelay(210)).toBe("3.5 minutes late");
    expect(describeDelay(-60)).toBe("1 minute early");
  });

  it("formats days compactly", () => {
    expect(formatDays(["mon", "tue", "wed", "thu", "fri"])).toBe("Mon–Fri");
    expect(formatDays(["sat", "sun"])).toBe("Sat, Sun");
    expect(formatDays(["fri", "mon", "wed"])).toBe("Mon, Wed, Fri");
    expect(formatDays(["mon", "tue", "wed", "thu", "fri", "sat", "sun"])).toBe("Every day");
  });

  it("formats clock values", () => {
    expect(hourLabel(0)).toBe("12 AM");
    expect(hourLabel(12)).toBe("12 PM");
    expect(hourLabel(17)).toBe("5 PM");
    expect(formatHHMM("07:05")).toBe("7:05 AM");
    expect(formatDuration(45)).toBe("45 s");
    expect(formatDuration(3 * 3600 + 300)).toBe("3 h 5 min");
  });

  it("names routes", () => {
    const bus = { id: "1", short_name: "1", long_name: "Harvard - Nubian", type: 3 };
    const red = { id: "Red", short_name: "", long_name: "Red Line", type: 1 };
    expect(routeName(bus)).toBe("Route 1");
    expect(routeName(red)).toBe("Red Line");
    expect(routeFullLabel(bus)).toBe("Route 1 · Harvard - Nubian");
    expect(routeFullLabel(red)).toBe("Red Line");
  });

  it("labels histogram buckets from edges", () => {
    expect(bucketLabels([-60, 60, 180, 300, 600, 1200])).toEqual([
      "< −1",
      "−1–1",
      "1–3",
      "3–5",
      "5–10",
      "10–20",
      "20+",
    ]);
  });
});

describe("color", () => {
  it("normalizes GTFS colors and keeps text readable", () => {
    expect(normalizeHex("da291c")).toBe("#DA291C");
    expect(normalizeHex("#FFC72C")).toBe("#FFC72C");
    expect(normalizeHex("red")).toBeNull();
    // Agency says white text on yellow: unreadable, so we pick dark text instead.
    const { fg } = routeColors({ color: "FFC72C", text_color: "FFFFFF" });
    expect(contrastRatio("#FFC72C", fg)).toBeGreaterThanOrEqual(4.5);
    expect(routeColors({ color: null, text_color: null }).bg).toMatch(/^#/);
  });

  it("bins delays and on-time rates so darker means worse", () => {
    expect(delayBin(-120).label).toMatch(/Early/);
    expect(delayBin(0).min).toBe(-60);
    expect(delayBin(700).min).toBe(600);
    expect(onTimeBin(95).min).toBe(90);
    expect(onTimeBin(10).label).toBe("Under 50%");
  });
});
