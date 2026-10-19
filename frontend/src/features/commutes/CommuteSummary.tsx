import { Link } from "react-router";
import { ErrorState, Skeleton } from "../../components/States";
import { formatCount, formatPct } from "../../lib/format";
import { useRouteDetail } from "../../lib/queries";
import { compareTrend, formatPercentile, summarizeWindow } from "../../lib/summary";
import type { AgencyManifest, Commute } from "../../lib/types";
import styles from "./Commutes.module.css";

/**
 * Personal summary for a saved commute (US-9), computed here from the public route file:
 * the window's hourly cells are merged; p50/p90 come from the merged histogram.
 */
export function CommuteSummary({ commute, agency }: { commute: Commute; agency: AgencyManifest }) {
  const detail = useRouteDetail(agency, commute.route_id);
  if (detail.isPending)
    return <Skeleton height="6rem" label="Loading reliability for this commute" />;
  if (detail.error) {
    return (
      <ErrorState
        title="Couldn't load this route's data"
        error={detail.error}
        onRetry={() => void detail.refetch()}
      />
    );
  }
  const route = detail.data;
  const direction = route.directions.find((d) => d.direction_id === commute.direction_id);
  const stop = direction?.stops.find((s) => s.stop_id === commute.stop_id);
  if (!stop) {
    return (
      <p className="notice small">
        This stop isn’t served in this direction in the current data. It may have moved or been
        renamed — edit the commute to pick it again.
      </p>
    );
  }
  const s = summarizeWindow(
    stop,
    commute.days,
    commute.window_start,
    commute.window_end,
    route.histogram_edges_s,
    route.min_samples,
  );
  const trend = compareTrend(route.trend);

  return (
    <div className={styles.summary} data-testid="commute-summary">
      {!s.enoughData ? (
        <p className="notice small">
          <strong>Not enough data</strong> for this window yet ({formatCount(s.n)} observed
          arrivals; we need at least {route.min_samples}).
        </p>
      ) : (
        <dl className="stat-grid">
          <div className="stat">
            <dt>Typical delay</dt>
            <dd>
              {formatPercentile(s.p50)}
              <span className="sub">approximate median</span>
            </dd>
          </div>
          <div className="stat">
            <dt>Worst case (p90)</dt>
            <dd>
              {formatPercentile(s.p90)}
              <span className="sub">approximate</span>
            </dd>
          </div>
          <div className="stat">
            <dt>On time</dt>
            <dd>
              {formatPct(s.on_time_pct)}
              <span className="sub">{formatCount(s.n)} arrivals</span>
            </dd>
          </div>
        </dl>
      )}
      <p className="small muted">
        Your window covers {s.cells.length} hourly {s.cells.length === 1 ? "slot" : "slots"} over{" "}
        {route.window.days} days
        {s.canceled > 0 && <> · {formatCount(s.canceled)} canceled trips</>}. Percentiles are
        approximated from grouped delays.{" "}
        <Link to="/about/methodology#commutes">How this is calculated</Link>
      </p>
      {trend && trend.latest.on_time_pct != null && (
        <p className={`small ${styles.trend}`}>
          <span className="badge">Route-level</span> Last week {formatPct(trend.latest.on_time_pct)}{" "}
          on time
          {trend.delta_pts != null && (
            <>
              {" "}
              ({trend.delta_pts >= 0 ? "+" : "−"}
              {Math.abs(trend.delta_pts).toFixed(1)} pts vs{" "}
              {trend.weeks_compared === 1
                ? "the previous week"
                : `the previous ${trend.weeks_compared} weeks`}
              )
            </>
          )}
        </p>
      )}
    </div>
  );
}
