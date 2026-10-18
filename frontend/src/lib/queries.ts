import { useQueries, useQuery, type UseQueryResult } from "@tanstack/react-query";
import { useMemo } from "react";
import {
  fetchCoverage,
  fetchHealth,
  fetchManifest,
  fetchRouteDetail,
  fetchRoutes,
  fetchStops,
  fetchValidation,
  findAgency,
  routeDetailPath,
} from "./dataClient";
import { buildSearchIndex, type SearchIndex } from "./search";
import type { AgencyManifest, Health, Manifest, RouteDetail, RouteSummary } from "./types";

/** Query hooks for published data. Immutable build files never go stale within a session. */

const IMMUTABLE = { staleTime: Infinity, gcTime: 30 * 60_000 } as const;

export function useManifest(): UseQueryResult<Manifest> {
  return useQuery({
    queryKey: ["manifest"],
    queryFn: ({ signal }) => fetchManifest(signal),
    staleTime: 60_000,
  });
}

export interface AgencyState {
  agency: AgencyManifest | null;
  manifest: Manifest | undefined;
  isLoading: boolean;
  error: Error | null;
  notFound: boolean;
  refetch: () => void;
}

export function useAgency(agencyId: string | undefined): AgencyState {
  const q = useManifest();
  const agency = q.data && agencyId ? findAgency(q.data, agencyId) : null;
  return {
    agency,
    manifest: q.data,
    isLoading: q.isPending,
    error: q.error,
    notFound: !!q.data && !agency,
    refetch: () => void q.refetch(),
  };
}

/** The first agency in the manifest is the default for search and commutes. */
export function useDefaultAgency(): AgencyState {
  const q = useManifest();
  return {
    agency: q.data?.agencies[0] ?? null,
    manifest: q.data,
    isLoading: q.isPending,
    error: q.error,
    notFound: !!q.data && q.data.agencies.length === 0,
    refetch: () => void q.refetch(),
  };
}

export function useStopsIndex(agency: AgencyManifest | null) {
  return useQuery({
    queryKey: ["data", agency?.paths.stops],
    queryFn: ({ signal }) => fetchStops(agency!, signal),
    enabled: !!agency,
    ...IMMUTABLE,
  });
}

/** Search index derived from the stops file; built once per build. */
export function useSearchIndex(agency: AgencyManifest | null): {
  index: SearchIndex | null;
  query: ReturnType<typeof useStopsIndex>;
} {
  const query = useStopsIndex(agency);
  const index = useMemo(
    () => (query.data ? buildSearchIndex(query.data.stops) : null),
    [query.data],
  );
  return { index, query };
}

export function useRoutesList(agency: AgencyManifest | null) {
  return useQuery({
    queryKey: ["data", agency?.paths.routes],
    queryFn: ({ signal }) => fetchRoutes(agency!, signal),
    enabled: !!agency,
    ...IMMUTABLE,
  });
}

export function useRoutesById(agency: AgencyManifest | null): Map<string, RouteSummary> {
  const { data } = useRoutesList(agency);
  return useMemo(() => new Map((data?.routes ?? []).map((r) => [r.id, r])), [data]);
}

function routeDetailQuery(agency: AgencyManifest | null, routeId: string | null | undefined) {
  return {
    queryKey: ["data", agency && routeId ? routeDetailPath(agency, routeId) : null],
    queryFn: ({ signal }: { signal: AbortSignal }) => fetchRouteDetail(agency!, routeId!, signal),
    enabled: !!agency && !!routeId,
    ...IMMUTABLE,
  };
}

export function useRouteDetail(agency: AgencyManifest | null, routeId: string | null | undefined) {
  return useQuery(routeDetailQuery(agency, routeId));
}

export function useRouteDetails(
  agency: AgencyManifest | null,
  routeIds: readonly string[],
): Map<string, UseQueryResult<RouteDetail>> {
  const results = useQueries({ queries: routeIds.map((id) => routeDetailQuery(agency, id)) });
  return new Map(routeIds.map((id, i) => [id, results[i]!]));
}

export function useCoverage(agency: AgencyManifest | null) {
  return useQuery({
    queryKey: ["data", agency?.paths.coverage],
    queryFn: ({ signal }) => fetchCoverage(agency!, signal),
    enabled: !!agency,
    ...IMMUTABLE,
  });
}

export function useValidation(agency: AgencyManifest | null) {
  return useQuery({
    queryKey: ["data", agency?.paths.validation ?? "none"],
    queryFn: ({ signal }) => fetchValidation(agency!, signal),
    enabled: !!agency,
    staleTime: 60 * 60_000,
  });
}

const HEALTH_POLL = { staleTime: 60_000, refetchInterval: 60_000 } as const;

export function useHealth(agency: AgencyManifest | null) {
  return useQuery({
    queryKey: ["health", agency?.paths.health],
    queryFn: ({ signal }) => fetchHealth(agency!, signal),
    enabled: !!agency,
    ...HEALTH_POLL,
  });
}

export function useAllHealth(agencies: readonly AgencyManifest[]): (Health | undefined)[] {
  return useQueries({
    queries: agencies.map((agency) => ({
      queryKey: ["health", agency.paths.health],
      queryFn: ({ signal }: { signal: AbortSignal }) => fetchHealth(agency, signal),
      ...HEALTH_POLL,
    })),
    combine: (results) => results.map((r) => r.data),
  });
}
