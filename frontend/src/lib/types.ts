/**
 * Typed mirror of docs/contracts.md §3 (published data) and §4 (dynamic API).
 * The contract is normative: change both in the same PR.
 */

// ---------------------------------------------------------------------------
// §3 Published data
// ---------------------------------------------------------------------------

export type DayType = "wkd" | "sat" | "sun";
export const DAY_TYPES: readonly DayType[] = ["wkd", "sat", "sun"];

export interface DataWindow {
  from: string;
  to: string;
  days: number;
}

export interface Manifest {
  schema_version: 1;
  build_id: string;
  generated_at: string;
  agencies: AgencyManifest[];
}

export interface AgencyManifest {
  id: string;
  name: string;
  timezone: string;
  live_api: "mbta-v3" | null;
  window: DataWindow;
  on_time_definition_s: [number, number];
  histogram_edges_s: number[];
  min_samples: number;
  paths: {
    stops: string;
    routes: string;
    route_template: string;
    coverage: string;
    health: string;
    validation: string | null;
  };
}

export interface StopsIndex {
  agency_id: string;
  stops: StopEntry[];
}

export interface StopEntry {
  id: string;
  name: string;
  lat: number;
  lon: number;
  parent: string | null;
  routes: string[];
}

export interface RoutesList {
  agency_id: string;
  routes: RouteSummary[];
}

export interface RouteInfo {
  id: string;
  short_name: string | null;
  long_name: string | null;
  type: number;
  color: string | null;
  text_color: string | null;
  sort_order: number | null;
}

export interface Stats {
  n: number;
  on_time_pct: number | null;
  p50_s: number | null;
  p90_s: number | null;
}

export interface RouteSummary extends RouteInfo {
  summary: Stats & { coverage_pct: number | null };
}

export interface RouteDetail {
  agency_id: string;
  route: RouteInfo;
  window: DataWindow;
  on_time_definition_s: [number, number];
  histogram_edges_s: number[];
  min_samples: number;
  directions: Direction[];
  trend: TrendPoint[];
  coverage: { observed_trips: number; scheduled_trips: number; coverage_pct: number | null };
}

export type DirectionId = 0 | 1;

export interface Direction {
  direction_id: DirectionId;
  headsign: string | null;
  stops: StopCells[];
}

export interface StopCells {
  stop_id: string;
  name: string;
  order: number;
  summary: Stats;
  cells: Cell[];
}

export interface Cell {
  day: DayType;
  hour: number;
  n: number;
  p50_s: number | null;
  p90_s: number | null;
  on_time_pct: number | null;
  early_pct: number | null;
  canceled: number;
  skipped: number;
  sched_headway_s: number | null;
  ewt_s: number | null;
  hist: number[];
}

export interface TrendPoint {
  week_start: string;
  n: number;
  on_time_pct: number | null;
  p50_s: number | null;
  p90_s: number | null;
}

export interface CoverageDay {
  service_date: string;
  scheduled_trips: number;
  observed_trips: number;
  canceled_trips: number;
  coverage_pct: number | null;
}

export interface Coverage {
  agency_id: string;
  days: CoverageDay[];
}

export type HealthStatus = "ok" | "degraded" | "stale" | "unknown";

export interface Health {
  agency_id: string;
  generated_at: string;
  status: HealthStatus;
  last_success_at: string | null;
  feed_timestamp: string | null;
  feed_age_s: number | null;
  ticks_last_hour: { ok: number; failed: number; not_advanced: number; expected: 60 };
  recent_gaps: { start: string; end: string; minutes: number }[];
}

export interface Validation {
  agency_id: string;
  generated_at: string;
  week: string;
  sample: number;
  median_abs_error_s: number | null;
  p90_abs_error_s: number | null;
  by_route: Record<string, { n: number; median_abs_error_s: number }>;
}

// ---------------------------------------------------------------------------
// §4 Dynamic API
// ---------------------------------------------------------------------------

export interface Features {
  alerts: boolean;
  ask: boolean;
  google_login: boolean;
}

export interface ConfigResponse {
  features: Features & { demo: boolean };
  vapid_public_key: string | null;
}

export interface User {
  id: string;
  display_name: string | null;
  email: string | null;
  is_demo: boolean;
  demo_expires_at: string | null;
  created_at: string;
}

export interface MeResponse {
  user: User;
  csrf_token: string;
  features: Features;
}

export type Weekday = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";
export const WEEKDAYS: readonly Weekday[] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

export interface AlertRule {
  threshold_min: number;
  notify_cancellations: boolean;
  active: boolean;
}

export interface Commute {
  id: string;
  agency_id: string;
  route_id: string;
  direction_id: DirectionId;
  stop_id: string;
  label: string | null;
  days: Weekday[];
  window_start: string;
  window_end: string;
  created_at: string;
  updated_at: string;
  alert: AlertRule | null;
}

export interface CommuteInput {
  agency_id: string;
  route_id: string;
  direction_id: DirectionId;
  stop_id: string;
  label?: string | null;
  days: Weekday[];
  window_start: string;
  window_end: string;
}

export interface CommutesResponse {
  commutes: Commute[];
}

export interface AlertInput {
  threshold_min: number;
  notify_cancellations: boolean;
}

export interface ExportResponse {
  exported_at: string;
  user: User;
  commutes: Commute[];
  sessions: { created_at: string; last_seen_at: string; user_agent: string | null }[];
  push_subscriptions: { id: string; created_at: string }[];
  audit: { at: string; action: string; outcome: string }[];
}

export interface AskResponse {
  answer: string | null;
  fallback: boolean;
  reason: string | null;
  facts: { label: string; value: string; source: string }[];
  links: { label: string; href: string }[];
}

export interface ProblemDetails {
  type: string;
  title: string;
  status: number;
  detail?: string;
  errors?: { field: string; message: string }[];
}
