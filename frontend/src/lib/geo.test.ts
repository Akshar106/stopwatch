import { describe, expect, it } from "vitest";
import { fixtures } from "../test/fixtures";
import { formatDistance, haversineMeters, nearestPlaces, walkingMinutes } from "./geo";
import { buildSearchIndex } from "./search";

describe("haversineMeters", () => {
  it("is zero for the same point and symmetric", () => {
    const a = { lat: 42.3601, lon: -71.0589 };
    const b = { lat: 42.3736, lon: -71.119 };
    expect(haversineMeters(a, a)).toBe(0);
    expect(haversineMeters(a, b)).toBeCloseTo(haversineMeters(b, a), 6);
  });

  it("matches known distances", () => {
    // Boston City Hall → Harvard Square ≈ 5.2 km; Boston → New York ≈ 306 km.
    expect(
      haversineMeters({ lat: 42.3603, lon: -71.058 }, { lat: 42.3734, lon: -71.1189 }) / 1000,
    ).toBeCloseTo(5.2, 1);
    expect(
      haversineMeters({ lat: 42.3601, lon: -71.0589 }, { lat: 40.7128, lon: -74.006 }) / 1000,
    ).toBeCloseTo(306, -1);
  });

  it("handles the antimeridian", () => {
    expect(haversineMeters({ lat: 0, lon: 179.9 }, { lat: 0, lon: -179.9 })).toBeLessThan(25_000);
  });
});

describe("nearestPlaces", () => {
  const index = buildSearchIndex(fixtures.stops.stops);

  it("returns the closest places in order, stations counted once", () => {
    // Standing at Harvard Square.
    const results = nearestPlaces(index.places, { lat: 42.3733, lon: -71.1189 }, 10);
    expect(results).toHaveLength(10);
    expect(results[0]!.place.id).toMatch(/^(110|place-harsq)$/);
    const distances = results.map((r) => r.distanceM);
    expect([...distances].sort((a, b) => a - b)).toEqual(distances);
    expect(new Set(results.map((r) => r.place.id)).size).toBe(10);
    expect(results.filter((r) => r.place.id === "place-harsq")).toHaveLength(1);
  });

  it("respects the limit", () => {
    expect(nearestPlaces(index.places, { lat: 42.35, lon: -71.06 }, 3)).toHaveLength(3);
  });
});

describe("distance formatting", () => {
  it("formats meters and kilometers", () => {
    expect(formatDistance(84)).toBe("80 m");
    expect(formatDistance(1530)).toBe("1.5 km");
    expect(formatDistance(23_400)).toBe("23 km");
    expect(walkingMinutes(400)).toBe(5);
    expect(walkingMinutes(10)).toBe(1);
  });
});
