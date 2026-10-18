import type { MeResponse, ProblemDetails } from "./types";

/**
 * Thin fetch wrapper for the dynamic API (docs/contracts.md §4).
 *
 * - Same-origin cookies (the session cookie is HttpOnly; JS never sees it).
 * - `X-Requested-With: stopwatch` on every request.
 * - `X-CSRF-Token` on state-changing requests while signed in. The token is held in memory
 *   only (never localStorage), populated from GET /me and the login/demo responses.
 * - Errors are parsed from application/problem+json into ApiError; `type` is
 *   `urn:stopwatch:problem:<slug>` for errors the UI branches on (exposed as `slug`).
 * - A 403 `csrf` (token rotated because the session changed) refreshes the token from GET /me
 *   and retries the request once.
 * - A 401 clears the token and notifies listeners so the UI can drop to signed-out state.
 */

export const API_BASE = "/api/v1";
export const PROBLEM_PREFIX = "urn:stopwatch:problem:";

/** Problem slugs the API documents (contracts §4 + API implementation). */
export type ProblemSlug =
  | "unauthenticated"
  | "demo-restricted"
  | "rate-limited"
  | "demo-capacity"
  | "commute-limit"
  | "subscription-limit"
  | "validation"
  | "feature-disabled"
  | "csrf"
  | "missing-requested-with"
  | "ask-quota"
  | "ask-disabled"
  | "demo-disabled"
  | "google-login-disabled";

export class ApiError extends Error {
  readonly status: number;
  readonly problem: ProblemDetails | null;
  readonly requestId: string | null;
  /** Seconds from a Retry-After header (429 rate-limited), if any. */
  readonly retryAfterS: number | null;

  constructor(
    status: number,
    problem: ProblemDetails | null,
    requestId: string | null,
    message?: string,
    retryAfterS: number | null = null,
  ) {
    super(message ?? problem?.detail ?? problem?.title ?? `Request failed (${status})`);
    this.name = "ApiError";
    this.status = status;
    this.problem = problem;
    this.requestId = requestId;
    this.retryAfterS = retryAfterS;
  }

  /** "commute-limit" for type "urn:stopwatch:problem:commute-limit"; null for about:blank. */
  get slug(): ProblemSlug | null {
    const type = this.problem?.type ?? "";
    return type.startsWith(PROBLEM_PREFIX)
      ? (type.slice(PROBLEM_PREFIX.length) as ProblemSlug)
      : null;
  }

  /** 422 field errors keyed by field name. */
  get fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const e of this.problem?.errors ?? []) out[e.field] = e.message;
    return out;
  }
}

export function isApiError(e: unknown, status?: number): e is ApiError {
  return e instanceof ApiError && (status === undefined || e.status === status);
}

export function hasSlug(e: unknown, slug: ProblemSlug): e is ApiError {
  return e instanceof ApiError && e.slug === slug;
}

let csrfToken: string | null = null;
const unauthorizedListeners = new Set<() => void>();

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export function getCsrfToken(): string | null {
  return csrfToken;
}

export function onUnauthorized(listener: () => void): () => void {
  unauthorizedListeners.add(listener);
  return () => unauthorizedListeners.delete(listener);
}

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export interface RequestOptions {
  body?: unknown;
  idempotencyKey?: string;
  signal?: AbortSignal;
}

const SAFE_METHODS = new Set<Method>(["GET"]);

async function parseBody(res: Response): Promise<unknown> {
  if (res.status === 204) return undefined;
  const type = res.headers.get("content-type") ?? "";
  if (type.includes("json")) {
    try {
      return await res.json();
    } catch {
      return undefined;
    }
  }
  const text = await res.text();
  return text.length ? text : undefined;
}

function asProblem(body: unknown, status: number): ProblemDetails | null {
  if (body && typeof body === "object" && "title" in body) {
    const p = body as Partial<ProblemDetails>;
    return {
      type: typeof p.type === "string" ? p.type : "about:blank",
      title: String(p.title),
      status: typeof p.status === "number" ? p.status : status,
      detail: typeof p.detail === "string" ? p.detail : undefined,
      errors: Array.isArray(p.errors) ? p.errors : undefined,
    };
  }
  return null;
}

function retryAfter(res: Response): number | null {
  const value = res.headers.get("retry-after");
  if (!value) return null;
  const seconds = Number(value);
  if (Number.isFinite(seconds)) return Math.max(0, Math.round(seconds));
  const date = Date.parse(value);
  return Number.isFinite(date) ? Math.max(0, Math.round((date - Date.now()) / 1000)) : null;
}

/** Fetch a fresh CSRF token (the token is bound to the session and rotates with it). */
async function refreshCsrfToken(signal?: AbortSignal): Promise<boolean> {
  try {
    const me = await send<MeResponse>("GET", "/me", { signal }, false);
    csrfToken = me.csrf_token;
    return true;
  } catch {
    return false;
  }
}

export async function apiRequest<T>(
  method: Method,
  path: string,
  opts: RequestOptions = {},
): Promise<T> {
  return send<T>(method, path, opts, true);
}

async function send<T>(
  method: Method,
  path: string,
  opts: RequestOptions,
  allowCsrfRetry: boolean,
): Promise<T> {
  const headers: Record<string, string> = {
    Accept: "application/json, application/problem+json",
    "X-Requested-With": "stopwatch",
  };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (!SAFE_METHODS.has(method) && csrfToken) headers["X-CSRF-Token"] = csrfToken;
  if (opts.idempotencyKey) headers["Idempotency-Key"] = opts.idempotencyKey;

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      credentials: "same-origin",
      signal: opts.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(0, null, null, "Can't reach Stopwatch right now. Check your connection.");
  }

  const body = await parseBody(res);
  if (!res.ok) {
    const error = new ApiError(
      res.status,
      asProblem(body, res.status),
      res.headers.get("x-request-id"),
      undefined,
      retryAfter(res),
    );
    if (res.status === 401) {
      csrfToken = null;
      unauthorizedListeners.forEach((listener) => listener());
    } else if (
      error.slug === "csrf" &&
      allowCsrfRetry &&
      !SAFE_METHODS.has(method) &&
      (await refreshCsrfToken(opts.signal))
    ) {
      return send<T>(method, path, opts, false);
    }
    throw error;
  }
  return body as T;
}

export const api = {
  get: <T>(path: string, opts?: Omit<RequestOptions, "body">) => apiRequest<T>("GET", path, opts),
  post: <T>(path: string, body?: unknown, opts?: RequestOptions) =>
    apiRequest<T>("POST", path, { ...opts, body }),
  put: <T>(path: string, body?: unknown, opts?: RequestOptions) =>
    apiRequest<T>("PUT", path, { ...opts, body }),
  patch: <T>(path: string, body?: unknown, opts?: RequestOptions) =>
    apiRequest<T>("PATCH", path, { ...opts, body }),
  delete: <T = void>(path: string, opts?: RequestOptions) => apiRequest<T>("DELETE", path, opts),
};

/** Human-readable message for any thrown value. */
export function errorMessage(err: unknown, fallback = "Something went wrong."): string {
  if (err instanceof ApiError) {
    if (err.slug === "rate-limited" || (err.status === 429 && !err.slug)) {
      const wait = err.retryAfterS;
      return wait != null && wait > 0
        ? `Too many requests. Please try again in ${wait < 90 ? `${wait} seconds` : `${Math.ceil(wait / 60)} minutes`}.`
        : "Too many requests. Please wait a moment and try again.";
    }
    if (err.slug === "demo-restricted")
      return "That isn't available for demo accounts. Sign in with Google to use it.";
    if (err.slug === "feature-disabled") return "That feature is turned off on this server.";
    if (err.status >= 500) return "Stopwatch had a problem on its side. Please try again.";
    return err.message || fallback;
  }
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}
