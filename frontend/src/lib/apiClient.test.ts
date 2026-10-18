import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  api,
  ApiError,
  errorMessage,
  getCsrfToken,
  onUnauthorized,
  setCsrfToken,
} from "./apiClient";

type Call = { url: string; init: RequestInit };

function mockFetch(...responses: Response[]) {
  const calls: Call[] = [];
  const fn = vi.fn((url: string, init: RequestInit) => {
    calls.push({ url, init });
    const next = responses.shift();
    if (!next) throw new Error("unexpected fetch");
    return Promise.resolve(next);
  });
  vi.stubGlobal("fetch", fn);
  return calls;
}

const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
const problem = (
  status: number,
  slug: string | null,
  extra: Record<string, unknown> = {},
  headers: Record<string, string> = {},
) =>
  new Response(
    JSON.stringify({
      type: slug ? `urn:stopwatch:problem:${slug}` : "about:blank",
      title: "Error",
      status,
      ...extra,
    }),
    { status, headers: { "content-type": "application/problem+json", ...headers } },
  );
const header = (call: Call, name: string) => new Headers(call.init.headers).get(name);

beforeEach(() => setCsrfToken(null));
afterEach(() => vi.unstubAllGlobals());

describe("apiClient headers", () => {
  it("sends X-Requested-With and same-origin credentials on every request, but no CSRF token on GET", async () => {
    setCsrfToken("tok-1");
    const calls = mockFetch(json(200, { commutes: [] }));
    await api.get("/commutes");
    expect(calls[0]!.url).toBe("/api/v1/commutes");
    expect(header(calls[0]!, "X-Requested-With")).toBe("stopwatch");
    expect(header(calls[0]!, "X-CSRF-Token")).toBeNull();
    expect(calls[0]!.init.credentials).toBe("same-origin");
  });

  it("adds X-CSRF-Token, JSON body and Idempotency-Key on state-changing requests while signed in", async () => {
    setCsrfToken("tok-1");
    const calls = mockFetch(json(201, { id: "c1" }));
    await api.post("/commutes", { route_id: "1" }, { idempotencyKey: "key-123" });
    const call = calls[0]!;
    expect(call.init.method).toBe("POST");
    expect(header(call, "X-Requested-With")).toBe("stopwatch");
    expect(header(call, "X-CSRF-Token")).toBe("tok-1");
    expect(header(call, "Idempotency-Key")).toBe("key-123");
    expect(header(call, "Content-Type")).toBe("application/json");
    expect(call.init.body).toBe(JSON.stringify({ route_id: "1" }));
  });

  it("omits X-CSRF-Token when not signed in (e.g. POST /auth/demo)", async () => {
    const calls = mockFetch(json(201, { user: {}, csrf_token: "new" }));
    await api.post("/auth/demo");
    expect(header(calls[0]!, "X-CSRF-Token")).toBeNull();
    expect(header(calls[0]!, "X-Requested-With")).toBe("stopwatch");
    expect(calls[0]!.init.body).toBeUndefined();
  });

  it("sends the token on PUT, PATCH and DELETE too", async () => {
    setCsrfToken("tok-2");
    const calls = mockFetch(json(200, {}), json(200, {}), new Response(null, { status: 204 }));
    await api.put("/commutes/a/alert", { threshold_min: 5 });
    await api.patch("/commutes/a", { label: "x" });
    await expect(api.delete("/commutes/a")).resolves.toBeUndefined();
    expect(calls.map((c) => header(c, "X-CSRF-Token"))).toEqual(["tok-2", "tok-2", "tok-2"]);
  });
});

describe("apiClient errors", () => {
  it("parses problem+json into ApiError with slug and field errors", async () => {
    mockFetch(
      problem(422, "validation", {
        title: "Validation failed",
        errors: [{ field: "stop_id", message: "Route doesn't serve this stop" }],
      }),
    );
    const err = await api.post("/commutes", {}).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    const apiErr = err as ApiError;
    expect(apiErr.status).toBe(422);
    expect(apiErr.slug).toBe("validation");
    expect(apiErr.fieldErrors).toEqual({ stop_id: "Route doesn't serve this stop" });
  });

  it("reads Retry-After on rate limiting and explains it", async () => {
    mockFetch(
      problem(
        429,
        "rate-limited",
        { detail: "Too many requests; try again later." },
        { "Retry-After": "30" },
      ),
    );
    const err = (await api.post("/auth/demo").catch((e: unknown) => e)) as ApiError;
    expect(err.slug).toBe("rate-limited");
    expect(err.retryAfterS).toBe(30);
    expect(errorMessage(err)).toBe("Too many requests. Please try again in 30 seconds.");
  });

  it("clears the CSRF token and notifies listeners on 401", async () => {
    setCsrfToken("tok-1");
    const listener = vi.fn();
    const off = onUnauthorized(listener);
    mockFetch(problem(401, "unauthenticated"));
    await expect(api.get("/commutes")).rejects.toMatchObject({
      status: 401,
      slug: "unauthenticated",
    });
    expect(getCsrfToken()).toBeNull();
    expect(listener).toHaveBeenCalledTimes(1);
    off();
  });

  it("refreshes a rotated CSRF token from /me and retries the request once", async () => {
    setCsrfToken("stale");
    const calls = mockFetch(
      problem(403, "csrf"),
      json(200, { user: { id: "u" }, csrf_token: "fresh", features: {} }),
      json(201, { id: "c1" }),
    );
    await expect(api.post("/commutes", { a: 1 })).resolves.toEqual({ id: "c1" });
    expect(calls.map((c) => `${c.init.method} ${c.url}`)).toEqual([
      "POST /api/v1/commutes",
      "GET /api/v1/me",
      "POST /api/v1/commutes",
    ]);
    expect(header(calls[2]!, "X-CSRF-Token")).toBe("fresh");
    expect(getCsrfToken()).toBe("fresh");
  });

  it("does not retry a CSRF failure more than once", async () => {
    setCsrfToken("stale");
    const calls = mockFetch(
      problem(403, "csrf"),
      json(200, { csrf_token: "fresh" }),
      problem(403, "csrf"),
    );
    await expect(api.delete("/commutes/x")).rejects.toMatchObject({ status: 403, slug: "csrf" });
    expect(calls).toHaveLength(3);
  });

  it("turns network failures into a status-0 ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))),
    );
    await expect(api.get("/me")).rejects.toMatchObject({ status: 0 });
  });

  it("keeps about:blank problems slug-less", async () => {
    mockFetch(problem(404, null));
    const err = (await api.delete("/commutes/nope").catch((e: unknown) => e)) as ApiError;
    expect(err.slug).toBeNull();
    expect(err.status).toBe(404);
  });
});
