/**
 * Live predictions straight from the MBTA V3 API (JSON:API), called by the browser.
 * Stopwatch servers are never involved (US-4). Unkeyed access is limited to ~20 requests
 * per minute per IP, so callers poll at 30 s and back off on 429.
 */

export const MBTA_API = "https://api-v3.mbta.com";

interface JsonApiRef {
  id: string;
  type: string;
}

interface PredictionResource {
  id: string;
  type: "prediction";
  attributes: {
    arrival_time: string | null;
    departure_time: string | null;
    schedule_relationship: string | null;
    status: string | null;
    direction_id: number;
  };
  relationships?: {
    schedule?: { data: JsonApiRef | null };
    trip?: { data: JsonApiRef | null };
  };
}

interface ScheduleResource {
  id: string;
  type: "schedule";
  attributes: { arrival_time: string | null; departure_time: string | null };
}

export interface PredictionsDocument {
  data: PredictionResource[];
  included?: (ScheduleResource | { id: string; type: string; attributes?: unknown })[];
}

export type LiveStatus = "scheduled" | "canceled" | "skipped" | "added";

export interface LiveArrival {
  id: string;
  predicted: Date | null;
  scheduled: Date | null;
  /** Predicted − scheduled, in whole minutes (null when either is missing). */
  minutesLate: number | null;
  status: LiveStatus;
  /** Free-text status from the agency, e.g. "Approaching", "Stopped 2 stops away". */
  note: string | null;
}

export class LiveError extends Error {
  readonly kind: "rate_limited" | "unavailable";
  constructor(kind: "rate_limited" | "unavailable", message: string) {
    super(message);
    this.name = "LiveError";
    this.kind = kind;
  }
}

export function predictionsUrl(params: {
  stopId: string;
  routeId: string;
  directionId: number;
}): string {
  const q = new URLSearchParams({
    "filter[stop]": params.stopId,
    "filter[route]": params.routeId,
    "filter[direction_id]": String(params.directionId),
    include: "schedule",
    sort: "time",
    "page[limit]": "5",
  });
  return `${MBTA_API}/predictions?${q.toString()}`;
}

function toDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

function toStatus(rel: string | null): LiveStatus {
  switch ((rel ?? "").toUpperCase()) {
    case "CANCELLED":
    case "CANCELED":
      return "canceled";
    case "SKIPPED":
      return "skipped";
    case "ADDED":
      return "added";
    default:
      return "scheduled";
  }
}

export function parsePredictions(doc: PredictionsDocument): LiveArrival[] {
  const schedules = new Map<string, ScheduleResource>();
  for (const inc of doc.included ?? []) {
    if (inc.type === "schedule") schedules.set(inc.id, inc as ScheduleResource);
  }
  const arrivals = doc.data.map((p): LiveArrival => {
    const schedId = p.relationships?.schedule?.data?.id;
    const sched = schedId ? schedules.get(schedId) : undefined;
    const predicted = toDate(p.attributes.arrival_time ?? p.attributes.departure_time);
    const scheduled = toDate(sched?.attributes.arrival_time ?? sched?.attributes.departure_time);
    return {
      id: p.id,
      predicted,
      scheduled,
      minutesLate:
        predicted && scheduled
          ? Math.round((predicted.getTime() - scheduled.getTime()) / 60_000)
          : null,
      status: toStatus(p.attributes.schedule_relationship),
      note: p.attributes.status,
    };
  });
  const key = (a: LiveArrival) => (a.predicted ?? a.scheduled)?.getTime() ?? Infinity;
  return arrivals.sort((a, b) => key(a) - key(b));
}

export async function fetchLiveArrivals(
  params: { stopId: string; routeId: string; directionId: number },
  signal?: AbortSignal,
): Promise<LiveArrival[]> {
  let res: Response;
  try {
    res = await fetch(predictionsUrl(params), {
      signal,
      // Third-party origin: send no cookies and no referrer.
      credentials: "omit",
      referrerPolicy: "no-referrer",
      headers: { Accept: "application/vnd.api+json" },
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new LiveError("unavailable", "Couldn't reach the MBTA live data service.");
  }
  if (res.status === 429) {
    throw new LiveError("rate_limited", "The MBTA live data service is busy (rate limited).");
  }
  if (!res.ok)
    throw new LiveError("unavailable", `The MBTA live data service returned ${res.status}.`);
  const doc = (await res.json()) as PredictionsDocument;
  return parsePredictions(doc);
}
