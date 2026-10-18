import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/apiClient";
import { routeFullLabel } from "../../lib/format";
import { useRouteDetail, useRoutesById } from "../../lib/queries";
import type {
  AgencyManifest,
  AlertInput,
  AlertRule,
  Commute,
  CommuteInput,
  CommutesResponse,
  MeResponse,
} from "../../lib/types";

export const COMMUTES_KEY = ["commutes"] as const;

/** Limits from contracts §4 (the API enforces them with 409; the UI explains them up front). */
export function commuteLimit(me: MeResponse): number {
  return me.user.is_demo ? 3 : 20;
}

export function useCommutes(enabled: boolean) {
  return useQuery({
    queryKey: COMMUTES_KEY,
    queryFn: ({ signal }) =>
      api.get<CommutesResponse>("/commutes", { signal }).then((r) => r.commutes),
    enabled,
    staleTime: 60_000,
  });
}

function newKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function")
    return crypto.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

/** An Idempotency-Key that stays the same across retries of one logical create. */
export function makeIdempotencyKey(): string {
  return newKey();
}

export function useCreateCommute() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ input, idempotencyKey }: { input: CommuteInput; idempotencyKey: string }) =>
      api.post<Commute>("/commutes", input, { idempotencyKey }),
    onSuccess: (created) => {
      qc.setQueryData<Commute[]>(COMMUTES_KEY, (prev) =>
        prev ? [...prev.filter((c) => c.id !== created.id), created] : [created],
      );
      void qc.invalidateQueries({ queryKey: COMMUTES_KEY });
    },
  });
}

export function useUpdateCommute() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Partial<CommuteInput> }) =>
      api.patch<Commute>(`/commutes/${encodeURIComponent(id)}`, patch),
    onSuccess: (updated) => {
      qc.setQueryData<Commute[]>(COMMUTES_KEY, (prev) =>
        prev?.map((c) => (c.id === updated.id ? updated : c)),
      );
      void qc.invalidateQueries({ queryKey: COMMUTES_KEY });
    },
  });
}

export function useDeleteCommute() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/commutes/${encodeURIComponent(id)}`),
    onSuccess: (_void, id) => {
      qc.setQueryData<Commute[]>(COMMUTES_KEY, (prev) => prev?.filter((c) => c.id !== id));
      void qc.invalidateQueries({ queryKey: COMMUTES_KEY });
    },
  });
}

export function useSetAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: AlertInput }) =>
      api.put<AlertRule>(`/commutes/${encodeURIComponent(id)}/alert`, input),
    onSuccess: (alert, { id }) => {
      qc.setQueryData<Commute[]>(COMMUTES_KEY, (prev) =>
        prev?.map((c) => (c.id === id ? { ...c, alert } : c)),
      );
    },
  });
}

export function useDeleteAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/commutes/${encodeURIComponent(id)}/alert`),
    onSuccess: (_void, id) => {
      qc.setQueryData<Commute[]>(COMMUTES_KEY, (prev) =>
        prev?.map((c) => (c.id === id ? { ...c, alert: null } : c)),
      );
    },
  });
}

/** Display names for a commute, resolved from the routes list and route file. */
export function useCommuteNames(commute: Commute, agency: AgencyManifest) {
  const routes = useRoutesById(agency);
  const detail = useRouteDetail(agency, commute.route_id);
  const route = routes.get(commute.route_id);
  const direction = detail.data?.directions.find((d) => d.direction_id === commute.direction_id);
  const stop = direction?.stops.find((s) => s.stop_id === commute.stop_id);
  return {
    route,
    routeLabel: route ? routeFullLabel(route) : `Route ${commute.route_id}`,
    headsign: direction?.headsign ?? null,
    stopName: stop?.name ?? `Stop ${commute.stop_id}`,
  };
}
