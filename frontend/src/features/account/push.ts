import { api, ApiError } from "../../lib/apiClient";

/**
 * Web Push opt-in (should-tier alerts). The service worker is registered only when the user
 * asks for alerts, so anonymous visitors never install one.
 */

const SUB_ID_KEY = "stopwatch.push-subscription-id";

export function pushSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

export function urlBase64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const raw = atob((base64 + padding).replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

export function storedSubscriptionId(): string | null {
  try {
    return window.localStorage.getItem(SUB_ID_KEY);
  } catch {
    return null;
  }
}

function storeSubscriptionId(id: string | null) {
  try {
    if (id) window.localStorage.setItem(SUB_ID_KEY, id);
    else window.localStorage.removeItem(SUB_ID_KEY);
  } catch {
    // Non-essential: the server prunes dead endpoints on 404/410.
  }
}

export async function enablePush(vapidPublicKey: string): Promise<string> {
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    throw new Error(
      permission === "denied"
        ? "Notifications are blocked for this site. Allow them in your browser settings to get alerts."
        : "Notifications weren't allowed.",
    );
  }
  const registration = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
  await navigator.serviceWorker.ready;
  const subscription =
    (await registration.pushManager.getSubscription()) ??
    (await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(vapidPublicKey),
    }));
  const json = subscription.toJSON();
  try {
    const { id } = await api.post<{ id: string }>("/push-subscriptions", {
      endpoint: json.endpoint,
      keys: json.keys,
    });
    storeSubscriptionId(id);
    return id;
  } catch (err) {
    // Don't leave a browser subscription the server doesn't know about.
    await subscription.unsubscribe().catch(() => undefined);
    if (err instanceof ApiError && (err.slug === "subscription-limit" || err.status === 409)) {
      throw new Error(
        "Your account already has the maximum of 10 devices getting alerts. Turn alerts off on another device first.",
        { cause: err },
      );
    }
    if (err instanceof ApiError && err.slug === "validation") {
      throw new Error(
        "This browser’s push service isn’t supported. Try Chrome, Firefox, Edge or Safari.",
        { cause: err },
      );
    }
    throw err;
  }
}

export async function disablePush(): Promise<void> {
  const id = storedSubscriptionId();
  const registration = await navigator.serviceWorker.getRegistration("/");
  const subscription = await registration?.pushManager.getSubscription();
  await subscription?.unsubscribe();
  if (id) await api.delete(`/push-subscriptions/${encodeURIComponent(id)}`);
  storeSubscriptionId(null);
}
