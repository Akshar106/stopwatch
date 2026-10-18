import type { Place } from "./search";

/**
 * "Near me" math. Runs entirely in the browser over the published stop index: the user's
 * coordinates are never put in a URL, header or body (docs/05 §5, US-2).
 */

export interface LatLon {
  lat: number;
  lon: number;
}

const EARTH_RADIUS_M = 6_371_008.8;
const toRad = (deg: number) => (deg * Math.PI) / 180;

/** Great-circle distance in meters. */
export function haversineMeters(a: LatLon, b: LatLon): number {
  const dLat = toRad(b.lat - a.lat);
  const dLon = toRad(b.lon - a.lon);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(h)));
}

export interface NearbyPlace {
  place: Place;
  distanceM: number;
}

export function nearestPlaces(places: readonly Place[], origin: LatLon, limit = 10): NearbyPlace[] {
  return places
    .map((place) => ({ place, distanceM: haversineMeters(origin, place) }))
    .sort((a, b) => a.distanceM - b.distanceM)
    .slice(0, limit);
}

export function formatDistance(meters: number): string {
  if (meters < 1000) return `${Math.round(meters / 10) * 10} m`;
  return `${(meters / 1000).toFixed(meters < 10_000 ? 1 : 0)} km`;
}

/** Rough walking time at 80 m/min. */
export function walkingMinutes(meters: number): number {
  return Math.max(1, Math.round(meters / 80));
}
