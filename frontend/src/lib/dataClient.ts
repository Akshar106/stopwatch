import type {
  AgencyManifest,
  Coverage,
  Health,
  Manifest,
  RouteDetail,
  RoutesList,
  StopsIndex,
  Validation,
} from "./types";

/**
 * Published-data client (docs/contracts.md §2–3).
 *
 * The manifest is the only mutable entry point (60 s cache). Everything under
 * /data/v1/builds/{build_id}/ is immutable, so once fetched it is cached for the session.
 * Swapping builds is atomic: a new manifest points at new paths, which are new cache keys.
 */

export const MANIFEST_URL = "/data/v1/manifest.json";

export class DataError extends Error {
  readonly status: number;
  readonly url: string;
  constructor(url: string, status: number, message?: string) {
    super(
      message ??
        (status === 404 ? "Not found" : `Couldn't load data (${status || "network error"})`),
    );
    this.name = "DataError";
    this.status = status;
    this.url = url;
  }
}

export async function fetchJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, {
      signal,
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new DataError(url, 0, "Can't reach the data server. Check your connection.");
  }
  if (!res.ok) throw new DataError(url, res.status);
  try {
    return (await res.json()) as T;
  } catch {
    throw new DataError(url, res.status, "The data file is malformed.");
  }
}

export function fetchManifest(signal?: AbortSignal): Promise<Manifest> {
  return fetchJson<Manifest>(MANIFEST_URL, signal).then((m) => {
    if (m.schema_version !== 1) {
      throw new DataError(
        MANIFEST_URL,
        200,
        `Unsupported data schema version ${String(m.schema_version)}`,
      );
    }
    return m;
  });
}

export function findAgency(manifest: Manifest, agencyId: string): AgencyManifest | null {
  return manifest.agencies.find((a) => a.id === agencyId) ?? null;
}

/** Route ids can contain characters like "/" or spaces; the key is URL-encoded (§2). */
export function routeDetailPath(agency: AgencyManifest, routeId: string): string {
  return agency.paths.route_template.replace("{route_id}", encodeURIComponent(routeId));
}

export const fetchStops = (agency: AgencyManifest, signal?: AbortSignal) =>
  fetchJson<StopsIndex>(agency.paths.stops, signal);
export const fetchRoutes = (agency: AgencyManifest, signal?: AbortSignal) =>
  fetchJson<RoutesList>(agency.paths.routes, signal);
export const fetchRouteDetail = (agency: AgencyManifest, routeId: string, signal?: AbortSignal) =>
  fetchJson<RouteDetail>(routeDetailPath(agency, routeId), signal);
export const fetchCoverage = (agency: AgencyManifest, signal?: AbortSignal) =>
  fetchJson<Coverage>(agency.paths.coverage, signal);
export const fetchHealth = (agency: AgencyManifest, signal?: AbortSignal) =>
  fetchJson<Health>(agency.paths.health, signal);

export async function fetchValidation(
  agency: AgencyManifest,
  signal?: AbortSignal,
): Promise<Validation | null> {
  if (!agency.paths.validation) return null;
  try {
    return await fetchJson<Validation>(agency.paths.validation, signal);
  } catch (err) {
    // The validation report is optional ("should" tier): absence is not an error.
    if (err instanceof DataError && err.status === 404) return null;
    throw err;
  }
}
