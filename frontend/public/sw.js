/* Stopwatch service worker: Web Push delay/cancellation alerts only (no caching).
 * Registered from the account page when the user opts in to alerts.
 * Payload (from the notify job): {"title": string, "body": string, "url": string}. */
"use strict";

const DEFAULT_URL = "/commutes";

function safeUrl(value) {
  // Only open pages on this site: a relative path, or an absolute URL on our own origin.
  try {
    const url = new URL(typeof value === "string" ? value : DEFAULT_URL, self.location.origin);
    return url.origin === self.location.origin
      ? url.href
      : new URL(DEFAULT_URL, self.location.origin).href;
  } catch {
    return new URL(DEFAULT_URL, self.location.origin).href;
  }
}

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
  let payload;
  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    payload = { body: event.data ? event.data.text() : "" };
  }
  const title =
    typeof payload.title === "string" && payload.title ? payload.title : "Stopwatch alert";
  const body = typeof payload.body === "string" ? payload.body : "";
  const url = safeUrl(payload.url);
  event.waitUntil(
    self.registration.showNotification(title, {
      body,
      icon: "/favicon.svg",
      badge: "/favicon.svg",
      tag: url,
      renotify: true,
      data: { url },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = safeUrl(event.notification.data && event.notification.data.url);
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      for (const client of windows) {
        if (client.url === url && "focus" in client) return client.focus();
      }
      for (const client of windows) {
        if (new URL(client.url).origin === self.location.origin && "navigate" in client) {
          return client.focus().then((c) => (c ? c.navigate(url) : self.clients.openWindow(url)));
        }
      }
      return self.clients.openWindow(url);
    }),
  );
});
