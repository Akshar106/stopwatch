import { describe, expect, it } from "vitest";
import { fixtures } from "../test/fixtures";
import {
  buildSearchIndex,
  groupPlaces,
  MatchRank,
  normalize,
  resolvePlace,
  searchStops,
} from "./search";
import type { StopEntry } from "./types";

const stop = (id: string, name: string, extra: Partial<StopEntry> = {}): StopEntry => ({
  id,
  name,
  lat: 42.36,
  lon: -71.06,
  parent: null,
  routes: ["1"],
  ...extra,
});

describe("normalize", () => {
  it("lowercases, strips diacritics and punctuation", () => {
    expect(normalize("  Café-Église @ St. Paul's  ")).toBe("cafe eglise st paul s");
    expect(normalize("Mass Ave & Newbury")).toBe("mass ave and newbury");
  });
});

describe("searchStops ranking", () => {
  const index = buildSearchIndex([
    stop("1", "Central Square"),
    stop("2", "Massachusetts Ave @ Central St"),
    stop("3", "Centre St @ Eliot St"),
    stop("4", "Decentral Plaza"),
    stop("5", "Central"),
  ]);

  it("ranks prefix > word-start > substring, shorter names first within a rank", () => {
    const results = searchStops(index, "central");
    expect(results.map((r) => r.place.name)).toEqual([
      "Central",
      "Central Square",
      "Massachusetts Ave @ Central St",
      "Decentral Plaza",
    ]);
    expect(results.map((r) => r.rank)).toEqual([
      MatchRank.Prefix,
      MatchRank.Prefix,
      MatchRank.WordStart,
      MatchRank.Substring,
    ]);
  });

  it("matches every query word at a word start", () => {
    const results = searchStops(index, "mass cent");
    expect(results[0]?.place.name).toBe("Massachusetts Ave @ Central St");
    expect(results[0]?.rank).toBe(MatchRank.WordStart);
  });

  it("is case- and diacritic-insensitive", () => {
    const idx = buildSearchIndex([stop("9", "Plaza Café Ñandú")]);
    expect(searchStops(idx, "CAFE")).toHaveLength(1);
    expect(searchStops(idx, "nandu")).toHaveLength(1);
    expect(searchStops(idx, "ÑAND")[0]?.rank).toBe(MatchRank.WordStart);
  });

  it("finds a stop by the number on the sign", () => {
    const results = searchStops(buildSearchIndex(fixtures.stops.stops), "64");
    expect(results[0]?.place.name).toBe("Massachusetts Ave @ Newbury St");
  });

  it("returns nothing for an empty query and respects the limit", () => {
    expect(searchStops(index, "   ")).toEqual([]);
    expect(searchStops(index, "e", 2)).toHaveLength(2);
  });
});

describe("station grouping", () => {
  it("collapses platforms of one parent into a single place with the union of routes", () => {
    const places = groupPlaces([
      stop("70075", "Park Street", { parent: "place-pktrm", routes: ["Red"], lat: 42.3564 }),
      stop("70076", "Park Street", { parent: "place-pktrm", routes: ["Red"], lat: 42.3566 }),
      stop("70196", "Park Street", { parent: "place-pktrm", routes: ["Green-B"], lat: 42.3565 }),
    ]);
    expect(places).toHaveLength(1);
    expect(places[0]).toMatchObject({ id: "place-pktrm", stopIds: ["70075", "70076", "70196"] });
    expect(new Set(places[0]!.routes)).toEqual(new Set(["Red", "Green-B"]));
    expect(places[0]!.lat).toBeCloseTo(42.3565, 4);
  });

  it("resolves both a platform id and the station id to the station", () => {
    const index = buildSearchIndex(fixtures.stops.stops);
    expect(resolvePlace(index, "70067")?.id).toBe("place-harsq");
    expect(resolvePlace(index, "place-harsq")?.stopIds).toEqual(["70067", "70068"]);
    expect(resolvePlace(index, "nope")).toBeNull();
  });
});

describe("search performance (US-1: < 100 ms per keystroke over ~8k stops)", () => {
  const words = [
    "Massachusetts",
    "Washington",
    "Harvard",
    "Central",
    "Broadway",
    "Main",
    "Elm",
    "Union",
    "Beacon",
    "Tremont",
    "Boylston",
    "Columbus",
    "Dudley",
    "Warren",
    "Blue Hill",
    "Centre",
    "Hyde Park",
  ];
  const synthetic: StopEntry[] = Array.from({ length: 8000 }, (_, i) => {
    const a = words[i % words.length]!;
    const b = words[(i * 7 + 3) % words.length]!;
    return stop(
      String(10000 + i),
      `${a} ${i % 3 ? "St" : "Ave"} @ ${b} ${i % 5 ? "St" : "Sq"} ${i}`,
      {
        parent: i % 10 === 0 ? `place-${Math.floor(i / 20)}` : null,
      },
    );
  });

  it("answers every keystroke of several queries well under 100 ms", () => {
    const index = buildSearchIndex(synthetic);
    let worst = 0;
    for (const query of [
      "massachusetts ave @ ha",
      "blue hill",
      "zzz no match",
      "st 79",
      "centre",
    ]) {
      for (let i = 1; i <= query.length; i++) {
        const t0 = performance.now();
        searchStops(index, query.slice(0, i));
        worst = Math.max(worst, performance.now() - t0);
      }
    }
    expect(worst).toBeLessThan(100);
  });

  it("builds the index for 8k stops quickly", () => {
    const t0 = performance.now();
    buildSearchIndex(synthetic);
    expect(performance.now() - t0).toBeLessThan(500);
  });
});
