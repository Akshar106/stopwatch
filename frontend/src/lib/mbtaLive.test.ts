import { afterEach, describe, expect, it, vi } from "vitest";
import { mockPredictions } from "../test/mocks/mbta";
import { fetchLiveArrivals, LiveError, parsePredictions, predictionsUrl } from "./mbtaLive";

afterEach(() => vi.unstubAllGlobals());

describe("predictionsUrl", () => {
  it("calls the MBTA V3 API directly with the documented filters", () => {
    const url = new URL(predictionsUrl({ stopId: "64", routeId: "1", directionId: 0 }));
    expect(url.origin).toBe("https://api-v3.mbta.com");
    expect(url.pathname).toBe("/predictions");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      "filter[stop]": "64",
      "filter[route]": "1",
      "filter[direction_id]": "0",
      include: "schedule",
      sort: "time",
      "page[limit]": "5",
    });
  });
});

describe("parsePredictions", () => {
  it("joins schedules, computes minutes late and flags cancellations", () => {
    const now = new Date("2026-10-19T12:00:00Z");
    const arrivals = parsePredictions(
      mockPredictions(new URL(predictionsUrl({ stopId: "64", routeId: "1", directionId: 0 })), now),
    );
    expect(arrivals.map((a) => a.minutesLate)).toEqual([1, 0, 6, null]);
    expect(arrivals[3]!.status).toBe("canceled");
    expect(arrivals[0]!.note).toBe("Approaching");
    expect(arrivals[0]!.predicted?.toISOString()).toBe("2026-10-19T12:02:00.000Z");
  });
});

describe("fetchLiveArrivals", () => {
  it("never sends cookies or a referrer to the third-party API", async () => {
    const fetchMock = vi.fn((_url: string, _init: RequestInit) =>
      Promise.resolve(new Response(JSON.stringify({ data: [] }))),
    );
    vi.stubGlobal("fetch", fetchMock);
    await fetchLiveArrivals({ stopId: "64", routeId: "1", directionId: 0 });
    const init = fetchMock.mock.calls[0]![1];
    expect(init.credentials).toBe("omit");
    expect(init.referrerPolicy).toBe("no-referrer");
  });

  it("distinguishes rate limiting from other failures", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response("", { status: 429 }))),
    );
    await expect(
      fetchLiveArrivals({ stopId: "1", routeId: "1", directionId: 0 }),
    ).rejects.toMatchObject({ kind: "rate_limited" });
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("offline"))),
    );
    const err = await fetchLiveArrivals({ stopId: "1", routeId: "1", directionId: 0 }).catch(
      (e: unknown) => e,
    );
    expect(err).toBeInstanceOf(LiveError);
    expect((err as LiveError).kind).toBe("unavailable");
  });
});
