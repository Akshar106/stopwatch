import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api, ApiError, isApiError, setCsrfToken } from "../../lib/apiClient";
import type { ConfigResponse, Features, MeResponse } from "../../lib/types";

/**
 * Session state. The session cookie is HttpOnly, so the browser can't tell whether it is
 * signed in without asking. To keep anonymous page views free of API calls (and Lambda
 * invocations), a non-sensitive "probably signed in" hint is kept in localStorage; GET /me is
 * only called when it is set. The hint is a boolean, never a token.
 */

export const ME_KEY = ["me"] as const;
export const CONFIG_KEY = ["config"] as const;
const HINT_KEY = "stopwatch.session-hint";

export function hasSessionHint(): boolean {
  try {
    return window.localStorage.getItem(HINT_KEY) === "1";
  } catch {
    return false;
  }
}

export function setSessionHint(on: boolean): void {
  try {
    if (on) window.localStorage.setItem(HINT_KEY, "1");
    else window.localStorage.removeItem(HINT_KEY);
  } catch {
    // Storage disabled (private mode): fall back to asking /me only after explicit sign-in.
  }
}

const noRetryOn4xx = (failureCount: number, error: Error) =>
  !(error instanceof ApiError && error.status >= 400 && error.status < 500) && failureCount < 1;

export function useMe() {
  return useQuery({
    queryKey: ME_KEY,
    queryFn: async ({ signal }): Promise<MeResponse | null> => {
      if (!hasSessionHint()) return null;
      try {
        const me = await api.get<MeResponse>("/me", { signal });
        setCsrfToken(me.csrf_token);
        return me;
      } catch (err) {
        if (isApiError(err, 401)) {
          setSessionHint(false);
          return null;
        }
        throw err;
      }
    },
    staleTime: 5 * 60_000,
    retry: noRetryOn4xx,
  });
}

export interface Session {
  me: MeResponse | null;
  isLoading: boolean;
  error: Error | null;
}

export function useSession(): Session {
  const q = useMe();
  return { me: q.data ?? null, isLoading: q.isPending, error: q.error };
}

const NO_FEATURES: ConfigResponse = {
  features: { alerts: false, ask: false, google_login: false, demo: false },
  vapid_public_key: null,
};

/** Public feature flags. Failure degrades to "everything off" rather than an error page. */
export function useConfig() {
  const q = useQuery({
    queryKey: CONFIG_KEY,
    queryFn: ({ signal }) => api.get<ConfigResponse>("/config", { signal }),
    staleTime: 10 * 60_000,
    retry: noRetryOn4xx,
  });
  return { config: q.data ?? NO_FEATURES, isLoading: q.isPending, error: q.error };
}

/** Signed-in users get flags from /me; anonymous visitors from /config. */
export function useFeatures(): Features {
  const { me } = useSession();
  return me?.features ?? { alerts: false, ask: false, google_login: false };
}

export function clearSession(qc: QueryClient): void {
  setCsrfToken(null);
  setSessionHint(false);
  qc.setQueryData(ME_KEY, null);
  qc.removeQueries({ queryKey: ["commutes"] });
}

function acceptSession(qc: QueryClient, me: MeResponse): void {
  setCsrfToken(me.csrf_token);
  setSessionHint(true);
  qc.setQueryData(ME_KEY, me);
  void qc.invalidateQueries({ queryKey: ["commutes"] });
}

export function useDemoLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<MeResponse>("/auth/demo"),
    onSuccess: (me) => acceptSession(qc, me),
  });
}

export function useLogout(everywhere = false) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<void>(everywhere ? "/auth/logout-all" : "/auth/logout"),
    // Whatever the server says, the local session is gone.
    onSettled: () => clearSession(qc),
  });
}

/** Only same-site relative paths are allowed as post-login destinations. */
export function safeNextPath(next: string | null | undefined, fallback = "/"): string {
  if (!next) return fallback;
  if (!next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return fallback;
  if (next.startsWith("/api/") || next.startsWith("/signin")) return fallback;
  return next;
}

export function googleLoginUrl(next: string): string {
  return `/api/v1/auth/login?next=${encodeURIComponent(safeNextPath(next))}`;
}
