#!/usr/bin/env node
/**
 * Budget check for the initial JavaScript (docs/05 §11: < 200 KB gzip).
 *
 * "Initial" = every script the browser fetches before first render: the entry module plus the
 * chunks it statically imports, which Vite lists in dist/index.html as <script type="module">
 * and <link rel="modulepreload">. Lazy route and chart chunks are reported but not counted.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

const BUDGET_KB = Number(process.env.INITIAL_JS_BUDGET_KB ?? 200);
const dist = fileURLToPath(new URL("../dist/", import.meta.url));

let html;
try {
  html = readFileSync(join(dist, "index.html"), "utf8");
} catch {
  console.error("dist/index.html not found. Run `vite build` first.");
  process.exit(1);
}

const initial = new Set();
for (const m of html.matchAll(/<script[^>]+type="module"[^>]+src="([^"]+)"/g)) initial.add(m[1]);
for (const m of html.matchAll(/<link[^>]+rel="modulepreload"[^>]+href="([^"]+)"/g))
  initial.add(m[1]);
const css = [...html.matchAll(/<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"/g)].map((m) => m[1]);

const gz = (rel) => gzipSync(readFileSync(join(dist, rel.replace(/^\//, "")))).length;
const kb = (bytes) => (bytes / 1024).toFixed(1);

let total = 0;
console.log("Initial JS (gzip):");
for (const file of initial) {
  const size = gz(file);
  total += size;
  console.log(`  ${kb(size).padStart(7)} KB  ${file}`);
}
const cssTotal = css.reduce((sum, f) => sum + gz(f), 0);

const lazy = readdirSync(join(dist, "assets"))
  .filter((f) => f.endsWith(".js") && !initial.has(`/assets/${f}`))
  .map((f) => ({ f, size: gz(`assets/${f}`) }))
  .sort((a, b) => b.size - a.size);
const lazyTotal = lazy.reduce((sum, x) => sum + x.size, 0);

console.log(`  ${"-".repeat(7)}`);
console.log(`  ${kb(total).padStart(7)} KB  total initial JS (budget ${BUDGET_KB} KB)`);
console.log(`  ${kb(cssTotal).padStart(7)} KB  initial CSS`);
console.log(
  `  ${kb(lazyTotal).padStart(7)} KB  lazy JS in ${lazy.length} chunks (largest: ${lazy[0]?.f ?? "-"} ${kb(lazy[0]?.size ?? 0)} KB)`,
);

if (total > BUDGET_KB * 1024) {
  console.error(`\n✗ Initial JS is ${kb(total)} KB gzip, over the ${BUDGET_KB} KB budget.`);
  process.exit(1);
}
console.log(`\n✓ Initial JS within budget.`);
