import { readFileSync } from "node:fs";
import type { IncomingMessage, ServerResponse } from "node:http";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";
import type { Plugin } from "vite";
import type { RouteDetail } from "./src/lib/types.ts";
import {
  createDataResolver,
  ROUTE_DETAIL_FILES,
  routeStopsFrom,
} from "./src/test/mocks/fixtures.ts";
import { MockApi } from "./src/test/mocks/mockApi.ts";

/**
 * `vite --mode mock` / `vite preview --mode mock`: serves the fixture data at /data/v1 and an
 * in-memory API at /api/v1, so the whole app (including demo sign-in and commutes) runs with
 * no backend. Used for local UI work and Lighthouse CI.
 */
export function mockBackendPlugin(): Plugin {
  const dir = fileURLToPath(new URL("./src/test/fixtures/", import.meta.url));
  const load = (file: string): unknown => JSON.parse(readFileSync(dir + file, "utf8"));
  const resolveData = createDataResolver(load);
  const api = new MockApi({
    routeStops: routeStopsFrom(ROUTE_DETAIL_FILES.map((f) => load(f) as RouteDetail)),
  });

  const readBody = (req: IncomingMessage) =>
    new Promise<unknown>((resolve) => {
      let raw = "";
      req.on("data", (chunk: Buffer) => (raw += chunk.toString()));
      req.on("end", () => {
        try {
          resolve(raw ? JSON.parse(raw) : undefined);
        } catch {
          resolve(undefined);
        }
      });
    });

  const middleware = (req: IncomingMessage, res: ServerResponse, next: () => void) => {
    const url = new URL(req.url ?? "/", "http://localhost");
    if (url.pathname.startsWith("/data/v1/")) {
      const body = resolveData(url.pathname);
      if (body === undefined) {
        res.statusCode = 404;
        res.end();
        return;
      }
      res.setHeader("content-type", "application/json");
      res.setHeader("cache-control", "no-cache");
      res.setHeader("vary", "accept-encoding");
      // Production serves /data compressed (CloudFront `compress = true`); without this a route
      // file goes over Lighthouse's simulated mobile network ~10x larger than real users get it.
      if (/\bgzip\b/.test(String(req.headers["accept-encoding"] ?? ""))) {
        res.setHeader("content-encoding", "gzip");
        res.end(gzipSync(JSON.stringify(body)));
      } else {
        res.end(JSON.stringify(body));
      }
      return;
    }
    if (url.pathname.startsWith("/api/v1/")) {
      void readBody(req).then((body) => {
        const out = api.handle({
          method: req.method ?? "GET",
          path: url.pathname.slice("/api/v1".length),
          query: url.searchParams,
          headers: Object.fromEntries(Object.entries(req.headers).map(([k, v]) => [k, String(v)])),
          body,
        });
        res.statusCode = out.status;
        for (const [k, v] of Object.entries(out.headers ?? {})) res.setHeader(k, v);
        res.end(out.body === undefined ? undefined : JSON.stringify(out.body));
      });
      return;
    }
    next();
  };

  return {
    name: "stopwatch-mock-backend",
    configureServer(server) {
      server.middlewares.use(middleware);
    },
    configurePreviewServer(server) {
      server.middlewares.use(middleware);
    },
  };
}
