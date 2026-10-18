import react from "@vitejs/plugin-react";
import { defineConfig, type ProxyOptions } from "vite";
import { mockBackendPlugin } from "./mock-backend.plugin.ts";

/**
 * Content-Security-Policy from docs/05-security-reliability.md §4. In production CloudFront sends it;
 * `vite preview` sends the same header so E2E and Lighthouse runs exercise the real policy.
 * (The dev server can't: React Fast Refresh needs an inline preamble script.)
 */
export const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "connect-src 'self' https://api-v3.mbta.com",
  "img-src 'self' data:",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "frame-ancestors 'none'",
  "base-uri 'none'",
  "form-action 'self'",
].join("; ");

const SECURITY_HEADERS = {
  "Content-Security-Policy": CONTENT_SECURITY_POLICY,
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "strict-origin-when-cross-origin",
  "Permissions-Policy": "geolocation=(self), camera=(), microphone=()",
};

export default defineConfig(({ mode }) => {
  const target = process.env.VITE_PROXY_TARGET || "http://localhost:8000";
  const proxy: Record<string, ProxyOptions> = {
    "/api": { target },
    "/data": { target },
  };
  // `--mode mock` serves fixture data and an in-memory API so the app runs with no backend.
  const useMock = mode === "mock";

  return {
    plugins: [react(), useMock && mockBackendPlugin()],
    server: { port: 5173, proxy: useMock ? undefined : proxy },
    preview: {
      port: 4173,
      proxy: useMock ? undefined : proxy,
      headers: SECURITY_HEADERS,
    },
    build: {
      target: "es2022",
      // Charts (Observable Plot + d3) are lazy chunks; keep the warning meaningful for app code.
      chunkSizeWarningLimit: 600,
    },
  };
});
