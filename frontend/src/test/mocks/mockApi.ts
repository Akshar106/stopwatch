import type {
  AskResponse,
  Commute,
  ConfigResponse,
  MeResponse,
  ProblemDetails,
  User,
  Weekday,
} from "../../lib/types.ts";
import type { RouteStops } from "./fixtures.ts";

/**
 * In-memory stand-in for /api/v1 (docs/contracts.md §4), used by Playwright and by
 * `npm run dev:mock`. It enforces the same header rules as the real API (X-Requested-With on
 * state changes, X-CSRF-Token while signed in) so the client's behavior is actually exercised.
 */

export interface MockRequest {
  method: string;
  /** Path after /api/v1, e.g. "/commutes/abc". */
  path: string;
  query: URLSearchParams;
  headers: Record<string, string>;
  body: unknown;
}

export interface MockResponse {
  status: number;
  headers?: Record<string, string>;
  body?: unknown;
}

export interface MockApiOptions {
  routeStops: RouteStops;
  features?: Partial<ConfigResponse["features"]>;
  vapidPublicKey?: string | null;
  now?: () => Date;
}

const WEEKDAYS: Weekday[] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

const TITLES: Record<number, string> = {
  401: "Unauthorized",
  403: "Forbidden",
  404: "Not Found",
  405: "Method Not Allowed",
  409: "Conflict",
  422: "Validation failed",
  429: "Too Many Requests",
  503: "Service Unavailable",
};

/** problem+json like the real API: type is urn:stopwatch:problem:<slug> or about:blank. */
function problem(
  status: number,
  slug: string | null,
  detail?: string,
  errors?: ProblemDetails["errors"],
  headers: Record<string, string> = {},
): MockResponse {
  return {
    status,
    headers: { "content-type": "application/problem+json", ...headers },
    body: {
      type: slug ? `urn:stopwatch:problem:${slug}` : "about:blank",
      title: TITLES[status] ?? "Error",
      status,
      ...(detail ? { detail } : {}),
      ...(errors ? { errors } : {}),
    },
  };
}

const PUSH_HOSTS = [
  /(^|\.)fcm\.googleapis\.com$/,
  /(^|\.)push\.services\.mozilla\.com$/,
  /(^|\.)push\.apple\.com$/,
  /(^|\.)notify\.windows\.com$/,
];

function validPushEndpoint(endpoint: unknown): boolean {
  if (typeof endpoint !== "string") return false;
  try {
    const url = new URL(endpoint);
    return url.protocol === "https:" && PUSH_HOSTS.some((re) => re.test(url.hostname));
  } catch {
    return false;
  }
}

const json = (status: number, body: unknown): MockResponse => ({
  status,
  headers: { "content-type": "application/json" },
  body,
});

const noContent: MockResponse = { status: 204 };

function minutes(hhmm: unknown): number {
  const m = typeof hhmm === "string" ? /^(\d{2}):(\d{2})$/.exec(hhmm) : null;
  return m ? Number(m[1]) * 60 + Number(m[2]) : NaN;
}

export class MockApi {
  private user: User | null = null;
  private csrf: string | null = null;
  private commutes: Commute[] = [];
  private idempotent = new Map<string, Commute>();
  private pushSubs = new Map<string, string>();
  private seq = 0;
  readonly requests: MockRequest[] = [];
  private readonly opts: Required<Omit<MockApiOptions, "features">> & {
    features: ConfigResponse["features"];
  };

  constructor(options: MockApiOptions) {
    this.opts = {
      routeStops: options.routeStops,
      vapidPublicKey:
        options.vapidPublicKey ??
        "BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkrxZJjSgSnfckjBJuBkr3qBUYIHBQFLXYp5Nksh8U",
      now: options.now ?? (() => new Date()),
      features: { alerts: true, ask: true, google_login: false, demo: true, ...options.features },
    };
  }

  private id(prefix: string) {
    this.seq += 1;
    return `${prefix}-${this.seq.toString().padStart(4, "0")}-${Math.random().toString(16).slice(2, 10)}`;
  }

  private me(): MeResponse {
    const { demo: _demo, ...features } = this.opts.features;
    return { user: this.user!, csrf_token: this.csrf!, features };
  }

  /** Signs in a demo user directly (test setup shortcut). */
  signInDemo(): MeResponse {
    const now = this.opts.now();
    this.user = {
      id: this.id("user"),
      display_name: "Demo rider",
      email: null,
      is_demo: true,
      demo_expires_at: new Date(now.getTime() + 24 * 3600_000).toISOString(),
      created_at: now.toISOString(),
    };
    this.csrf = this.id("csrf");
    this.commutes = [];
    return this.me();
  }

  /** Signs in a regular (Google) user directly (test setup shortcut). */
  signInUser(): MeResponse {
    const now = this.opts.now();
    this.user = {
      id: this.id("user"),
      display_name: "Riley Rider",
      email: "riley@example.com",
      is_demo: false,
      demo_expires_at: null,
      created_at: now.toISOString(),
    };
    this.csrf = this.id("csrf");
    this.commutes = [];
    return this.me();
  }

  /** Test setup shortcut: create a commute for the signed-in user without going through HTTP. */
  seedCommute(input: Record<string, unknown>): Commute {
    const out = this.createCommute(input, undefined);
    if (out.status !== 201) throw new Error(`seedCommute failed: ${JSON.stringify(out.body)}`);
    return out.body as Commute;
  }

  /** Rotates the CSRF token, as the real API does when the session changes. */
  rotateCsrf(): void {
    this.csrf = this.id("csrf");
  }

  handle(req: MockRequest): MockResponse {
    this.requests.push(req);
    const method = req.method.toUpperCase();
    const h = Object.fromEntries(Object.entries(req.headers).map(([k, v]) => [k.toLowerCase(), v]));
    const changesState = method !== "GET" && method !== "HEAD";

    if (changesState && h["x-requested-with"] !== "stopwatch") {
      return problem(
        403,
        "missing-requested-with",
        "State-changing requests must send X-Requested-With: stopwatch.",
      );
    }

    const p = req.path.replace(/\/+$/, "") || "/";

    // ---- public ----
    if (method === "GET" && p === "/healthz") return json(200, { status: "ok", version: "mock" });
    if (method === "GET" && p === "/config") {
      return json(200, {
        features: this.opts.features,
        vapid_public_key: this.opts.vapidPublicKey,
      });
    }
    if (method === "GET" && p === "/auth/login") {
      if (!this.opts.features.google_login)
        return problem(404, "google-login-disabled", "Google sign-in is not configured.");
      return { status: 302, headers: { location: "/signin?error=login_failed" } };
    }
    if (method === "POST" && p === "/auth/demo") {
      if (!this.opts.features.demo)
        return problem(404, "demo-disabled", "Demo accounts are not available.");
      return json(201, this.signInDemo());
    }

    // ---- session required ----
    if (!this.user) return problem(401, "unauthenticated", "Sign in to continue.");
    if (changesState && h["x-csrf-token"] !== this.csrf) {
      return problem(403, "csrf", "Missing or invalid X-CSRF-Token.");
    }

    if (method === "GET" && p === "/me") return json(200, this.me());
    if (method === "POST" && (p === "/auth/logout" || p === "/auth/logout-all")) {
      this.user = null;
      this.csrf = null;
      return noContent;
    }
    if (method === "GET" && p === "/me/export") {
      return json(200, {
        exported_at: this.opts.now().toISOString(),
        user: this.user,
        commutes: this.commutes,
        sessions: [
          {
            created_at: this.user.created_at,
            last_seen_at: this.opts.now().toISOString(),
            user_agent: h["user-agent"] ?? null,
          },
        ],
        push_subscriptions: [...this.pushSubs.keys()].map((id) => ({
          id,
          created_at: this.user!.created_at,
        })),
        audit: [{ at: this.user.created_at, action: "auth.demo_created", outcome: "success" }],
      });
    }
    if (method === "DELETE" && p === "/me") {
      this.user = null;
      this.csrf = null;
      this.commutes = [];
      return noContent;
    }

    if (p === "/commutes" && method === "GET") return json(200, { commutes: this.commutes });
    if (p === "/commutes" && method === "POST")
      return this.createCommute(req.body, h["idempotency-key"]);

    const commuteMatch = /^\/commutes\/([^/]+)(\/alert)?$/.exec(p);
    if (commuteMatch) {
      const id = decodeURIComponent(commuteMatch[1]!);
      const commute = this.commutes.find((c) => c.id === id);
      if (!commute) return problem(404, null);
      if (commuteMatch[2]) return this.alert(commute, method, req.body);
      if (method === "PATCH") return this.patchCommute(commute, req.body);
      if (method === "DELETE") {
        this.commutes = this.commutes.filter((c) => c.id !== id);
        return noContent;
      }
    }

    if (method === "POST" && p === "/push-subscriptions") {
      if (!this.opts.features.alerts)
        return problem(404, "feature-disabled", "Alerts are not enabled.");
      if (this.user.is_demo)
        return problem(403, "demo-restricted", "Sign in with Google to use this feature.");
      const sub = (req.body ?? {}) as { endpoint?: unknown };
      if (!validPushEndpoint(sub.endpoint)) {
        return problem(422, "validation", undefined, [
          { field: "endpoint", message: "Unsupported push service." },
        ]);
      }
      if (this.pushSubs.size >= 10)
        return problem(409, "subscription-limit", "Too many push subscriptions on this account.");
      const id = this.id("push");
      this.pushSubs.set(id, String(sub.endpoint));
      this.commutes = this.commutes.map((c) =>
        c.alert ? { ...c, alert: { ...c.alert, active: true } } : c,
      );
      return json(201, { id });
    }
    const pushMatch = /^\/push-subscriptions\/([^/]+)$/.exec(p);
    if (method === "DELETE" && pushMatch) {
      this.pushSubs.delete(decodeURIComponent(pushMatch[1]!));
      return noContent;
    }

    if (method === "POST" && p === "/ask") return this.ask(req.body);

    return problem(404, null, `No mock for ${method} ${p}`);
  }

  private validate(input: Record<string, unknown>, partial: boolean): ProblemDetails["errors"] {
    const errors: NonNullable<ProblemDetails["errors"]> = [];
    const has = (k: string) => input[k] !== undefined;
    if (!partial || has("days")) {
      const days = input.days;
      if (
        !Array.isArray(days) ||
        days.length === 0 ||
        days.some((d) => !WEEKDAYS.includes(d as Weekday))
      ) {
        errors.push({ field: "days", message: "Choose at least one valid day." });
      }
    }
    if (!partial || has("window_start") || has("window_end")) {
      const s = minutes(input.window_start);
      const e = minutes(input.window_end);
      if (!(e > s)) errors.push({ field: "window_end", message: "End must be after start." });
    }
    if (!partial || has("route_id") || has("stop_id") || has("direction_id")) {
      const stops = this.opts.routeStops[String(input.route_id)]?.[Number(input.direction_id)];
      if (!stops) errors.push({ field: "route_id", message: "Unknown route or direction." });
      else if (!stops.includes(String(input.stop_id))) {
        errors.push({
          field: "stop_id",
          message: "That route doesn't serve this stop in this direction.",
        });
      }
    }
    return errors.length ? errors : undefined;
  }

  private createCommute(body: unknown, key: string | undefined): MockResponse {
    if (key && this.idempotent.has(key)) {
      return {
        ...json(201, this.idempotent.get(key)),
        headers: { "content-type": "application/json", "idempotent-replayed": "true" },
      };
    }
    const input = (body ?? {}) as Record<string, unknown>;
    const limit = this.user!.is_demo ? 3 : 20;
    if (this.commutes.length >= limit) {
      return problem(409, "commute-limit", `You can save up to ${limit} commutes.`);
    }
    const errors = this.validate(input, false);
    if (errors) return problem(422, "validation", undefined, errors);
    const now = this.opts.now().toISOString();
    const commute: Commute = {
      id: this.id("commute"),
      agency_id: typeof input.agency_id === "string" ? input.agency_id : "mbta",
      route_id: String(input.route_id),
      direction_id: Number(input.direction_id) === 1 ? 1 : 0,
      stop_id: String(input.stop_id),
      label: typeof input.label === "string" && input.label ? input.label : null,
      days: WEEKDAYS.filter((d) => (input.days as string[]).includes(d)),
      window_start: String(input.window_start),
      window_end: String(input.window_end),
      created_at: now,
      updated_at: now,
      alert: null,
    };
    this.commutes.push(commute);
    if (key) this.idempotent.set(key, commute);
    return json(201, commute);
  }

  private patchCommute(commute: Commute, body: unknown): MockResponse {
    const patch = (body ?? {}) as Record<string, unknown>;
    const merged = { ...commute, ...patch } as unknown as Record<string, unknown>;
    const errors = this.validate(merged, false);
    if (errors) return problem(422, "validation", undefined, errors);
    const updated = {
      ...(merged as unknown as Commute),
      updated_at: this.opts.now().toISOString(),
    };
    this.commutes = this.commutes.map((c) => (c.id === commute.id ? updated : c));
    return json(200, updated);
  }

  private alert(commute: Commute, method: string, body: unknown): MockResponse {
    if (method === "DELETE") {
      this.commutes = this.commutes.map((c) => (c.id === commute.id ? { ...c, alert: null } : c));
      return noContent;
    }
    if (method !== "PUT") return problem(405, null);
    if (!this.opts.features.alerts)
      return problem(404, "feature-disabled", "Alerts are not enabled.");
    if (this.user!.is_demo)
      return problem(403, "demo-restricted", "Sign in with Google to use this feature.");
    const input = (body ?? {}) as { threshold_min?: unknown; notify_cancellations?: unknown };
    const t = Number(input.threshold_min);
    if (!Number.isInteger(t) || t < 3 || t > 60) {
      return problem(422, "validation", undefined, [
        { field: "threshold_min", message: "Must be 3–60." },
      ]);
    }
    const alert = {
      threshold_min: t,
      notify_cancellations: Boolean(input.notify_cancellations),
      active: this.pushSubs.size > 0,
    };
    this.commutes = this.commutes.map((c) => (c.id === commute.id ? { ...c, alert } : c));
    return json(200, alert);
  }

  private ask(body: unknown): MockResponse {
    if (!this.opts.features.ask)
      return problem(503, "ask-disabled", "Ask Stopwatch is unavailable.");
    if (this.user!.is_demo)
      return problem(403, "demo-restricted", "Sign in with Google to use this feature.");
    const raw = (body as { question?: unknown } | null)?.question;
    const q = typeof raw === "string" ? raw : "";
    if (!q || q.length > 300) {
      return problem(422, "validation", undefined, [
        { field: "question", message: "1–300 characters." },
      ]);
    }
    if (/weather|stock|joke/i.test(q)) {
      const res: AskResponse = {
        answer: null,
        fallback: true,
        reason: "refused",
        facts: [],
        links: [],
      };
      return json(200, res);
    }
    if (/fallback/i.test(q)) {
      const res: AskResponse = {
        answer: null,
        fallback: true,
        reason: "ungrounded",
        facts: [],
        links: [],
      };
      return json(200, res);
    }
    const res: AskResponse = {
      answer:
        "On weekdays between 8 and 9 AM, the 1 at Massachusetts Ave @ Newbury St is typically about 3 minutes late, and 1 in 10 arrivals is 9 or more minutes late.",
      fallback: false,
      reason: null,
      facts: [
        {
          label: "Typical delay (p50)",
          value: "+3.1 min",
          source: "routes/1.json · dir 0 · stop 64 · wkd 8:00",
        },
        {
          label: "Worst case (p90)",
          value: "+9.4 min",
          source: "routes/1.json · dir 0 · stop 64 · wkd 8:00",
        },
      ],
      links: [
        { label: "Massachusetts Ave @ Newbury St", href: "/s/mbta/64?route=1&dir=0&cell=wkd-8" },
      ],
    };
    return json(200, res);
  }
}
