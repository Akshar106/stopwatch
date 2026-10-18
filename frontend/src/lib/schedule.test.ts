import { describe, expect, it } from "vitest";
import {
  dayTypesFor,
  hourOverlapsWindow,
  hoursInWindow,
  isValidWindow,
  nowInZone,
  parseHHMM,
  serviceHourOrder,
} from "./schedule";

describe("days", () => {
  it("maps weekdays to day types", () => {
    expect(dayTypesFor(["mon", "fri"])).toEqual(new Set(["wkd"]));
    expect(dayTypesFor(["sat"])).toEqual(new Set(["sat"]));
    expect(dayTypesFor(["thu", "sun"])).toEqual(new Set(["wkd", "sun"]));
    expect(dayTypesFor([])).toEqual(new Set());
  });
});

describe("time windows", () => {
  it("parses HH:MM and rejects junk", () => {
    expect(parseHHMM("07:30")).toBe(450);
    expect(parseHHMM("24:00")).toBe(1440);
    expect(parseHHMM("24:30")).toBeNaN();
    expect(parseHHMM("7:3")).toBeNaN();
    expect(parseHHMM("12:60")).toBeNaN();
  });

  it("requires end after start", () => {
    expect(isValidWindow("07:30", "08:30")).toBe(true);
    expect(isValidWindow("08:30", "08:30")).toBe(false);
    expect(isValidWindow("09:00", "08:00")).toBe(false);
    expect(isValidWindow("", "08:00")).toBe(false);
  });

  it("finds the clock hours a window touches (half-open)", () => {
    expect(hoursInWindow("07:30", "08:30")).toEqual([7, 8]);
    expect(hoursInWindow("07:00", "08:00")).toEqual([7]);
    expect(hoursInWindow("07:00", "08:01")).toEqual([7, 8]);
    expect(hoursInWindow("23:15", "24:00")).toEqual([23]);
    expect(hourOverlapsWindow(8, "08:59", "09:30")).toBe(true);
    expect(hourOverlapsWindow(9, "08:00", "09:00")).toBe(false);
    expect(hourOverlapsWindow(8, "09:00", "08:00")).toBe(false);
  });
});

describe("nowInZone", () => {
  it("uses the agency's local clock, not the browser's", () => {
    // 2026-10-17T02:30Z is Friday 10:30 PM in Boston (EDT, UTC−4).
    expect(nowInZone("America/New_York", new Date("2026-10-17T02:30:00Z"))).toEqual({
      dayType: "wkd",
      hour: 22,
    });
    // 2026-10-18T04:10Z is Sunday 12:10 AM in Boston.
    expect(nowInZone("America/New_York", new Date("2026-10-18T04:10:00Z"))).toEqual({
      dayType: "sun",
      hour: 0,
    });
    expect(nowInZone("America/New_York", new Date("2026-10-17T16:00:00Z"))).toEqual({
      dayType: "sat",
      hour: 12,
    });
  });
});

describe("serviceHourOrder", () => {
  it("puts early-morning hours after late evening", () => {
    const hours = [0, 1, 5, 12, 23];
    expect([...hours].sort((a, b) => serviceHourOrder(a) - serviceHourOrder(b))).toEqual([
      5, 12, 23, 0, 1,
    ]);
  });
});
