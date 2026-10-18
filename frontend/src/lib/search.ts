import type { StopEntry } from "./types";

/**
 * Client-side stop search (US-1: < 100 ms per keystroke over ~8k stops).
 *
 * Platforms that share a parent station collapse into one "place" so "Park Street" appears
 * once, with every route that serves any of its platforms. All normalization happens once
 * when the index is built; a query is then a single linear scan with cheap string checks.
 */

export interface Place {
  /** Parent station id when the stop has one, otherwise the stop id. Used in /s/:agency/:id. */
  id: string;
  name: string;
  lat: number;
  lon: number;
  routes: string[];
  /** Stop ids (platforms) that belong to this place. */
  stopIds: string[];
}

interface IndexedPlace {
  place: Place;
  norm: string;
  /** " " + norm, so word-start checks are a single includes(" " + token). */
  spaced: string;
  ids: string[];
}

export interface SearchIndex {
  places: Place[];
  entries: IndexedPlace[];
}

export const MatchRank = { Prefix: 0, WordStart: 1, Substring: 2 } as const;
export type MatchRank = (typeof MatchRank)[keyof typeof MatchRank];

export interface SearchResult {
  place: Place;
  rank: MatchRank;
}

/** Lowercase, strip diacritics, turn punctuation into spaces, collapse whitespace. */
export function normalize(text: string): string {
  return text
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}

export function groupPlaces(stops: readonly StopEntry[]): Place[] {
  const byKey = new Map<string, Place & { _routes: Set<string>; _n: number }>();
  for (const stop of stops) {
    const key = stop.parent ?? stop.id;
    const existing = byKey.get(key);
    if (existing) {
      existing.stopIds.push(stop.id);
      for (const r of stop.routes) existing._routes.add(r);
      // Running mean keeps the station pin centered between its platforms.
      existing._n += 1;
      existing.lat += (stop.lat - existing.lat) / existing._n;
      existing.lon += (stop.lon - existing.lon) / existing._n;
    } else {
      byKey.set(key, {
        id: key,
        name: stop.name,
        lat: stop.lat,
        lon: stop.lon,
        routes: [],
        stopIds: [stop.id],
        _routes: new Set(stop.routes),
        _n: 1,
      });
    }
  }
  return [...byKey.values()].map(({ _routes, _n: _, ...place }) => ({
    ...place,
    routes: [..._routes],
  }));
}

export function buildSearchIndex(stops: readonly StopEntry[]): SearchIndex {
  const places = groupPlaces(stops);
  const entries = places.map((place) => {
    const norm = normalize(place.name);
    return {
      place,
      norm,
      spaced: ` ${norm}`,
      ids: [place.id, ...place.stopIds].map((id) => id.toLowerCase()),
    };
  });
  return { places, entries };
}

function rankEntry(entry: IndexedPlace, q: string, tokens: string[]): MatchRank | null {
  if (entry.norm.startsWith(q)) return MatchRank.Prefix;
  // Exact stop code ("64") is as good as a prefix match: riders read it off the sign.
  if (entry.ids.includes(q)) return MatchRank.Prefix;
  if (tokens.every((t) => entry.spaced.includes(` ${t}`))) return MatchRank.WordStart;
  if (entry.norm.includes(q)) return MatchRank.Substring;
  return null;
}

/**
 * Rank: prefix of the whole name > every query word starts a word in the name > substring.
 * Ties break on shorter name (closer match), then alphabetically.
 */
export function searchStops(index: SearchIndex, query: string, limit = 8): SearchResult[] {
  const q = normalize(query);
  if (q.length === 0) return [];
  const tokens = q.split(" ");
  const results: SearchResult[] = [];
  for (const entry of index.entries) {
    const rank = rankEntry(entry, q, tokens);
    if (rank !== null) results.push({ place: entry.place, rank });
  }
  results.sort(
    (a, b) =>
      a.rank - b.rank ||
      a.place.name.length - b.place.name.length ||
      a.place.name.localeCompare(b.place.name),
  );
  return results.slice(0, limit);
}

/**
 * Resolve a URL id to a place: either a stop id (platform or bus stop) or a parent station id.
 * A platform id resolves to its whole station so the route picker shows every line there.
 */
export function resolvePlace(index: SearchIndex, id: string): Place | null {
  for (const place of index.places) {
    if (place.id === id || place.stopIds.includes(id)) return place;
  }
  return null;
}
