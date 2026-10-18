import { useEffect, useSyncExternalStore } from "react";

const SITE = "Stopwatch";

/** Sets document.title; the route-change focus handler announces the page's <h1>. */
export function usePageTitle(title: string | null | undefined): void {
  useEffect(() => {
    document.title = title ? `${title} · ${SITE}` : `${SITE} — how reliable is your stop?`;
  }, [title]);
}

function subscribeVisibility(callback: () => void) {
  document.addEventListener("visibilitychange", callback);
  return () => document.removeEventListener("visibilitychange", callback);
}

/** True while the tab is visible; polling pauses when it isn't. */
export function useDocumentVisible(): boolean {
  return useSyncExternalStore(
    subscribeVisibility,
    () => document.visibilityState !== "hidden",
    () => true,
  );
}

/** Re-renders every `ms` so relative times ("3 min ago") stay current. */
export function useNow(ms = 30_000): Date {
  return useSyncExternalStore(
    (cb) => {
      const id = window.setInterval(cb, ms);
      return () => window.clearInterval(id);
    },
    () => nowBucket(ms),
    () => nowBucket(ms),
  ).date;
}

const buckets = new Map<number, { t: number; date: Date }>();
function nowBucket(ms: number) {
  const t = Math.floor(Date.now() / ms);
  const cached = buckets.get(ms);
  if (cached && cached.t === t) return cached;
  const next = { t, date: new Date() };
  buckets.set(ms, next);
  return next;
}
