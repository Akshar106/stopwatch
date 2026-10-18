import { Link } from "react-router";
import { ChartFigure, CoverageChart } from "../../components/charts";
import { ErrorState, Loading, Skeleton } from "../../components/States";
import {
  formatCount,
  formatDate,
  formatDateTime,
  formatDuration,
  formatPct,
  formatRelative,
} from "../../lib/format";
import { effectiveStatus, STATUS_DESCRIPTION, STATUS_LABEL } from "../../lib/health";
import { useNow, usePageTitle } from "../../lib/hooks";
import { useCoverage, useHealth, useManifest } from "../../lib/queries";
import type { AgencyManifest, HealthStatus } from "../../lib/types";
import styles from "./HealthPage.module.css";

const STATUS_ICON: Record<HealthStatus, string> = {
  ok: "✓",
  degraded: "!",
  stale: "✕",
  unknown: "?",
};

export function StatusBadge({ status }: { status: HealthStatus }) {
  return (
    <span className={`${styles.status} ${styles[status]}`}>
      <span aria-hidden="true" className={styles.statusIcon}>
        {STATUS_ICON[status]}
      </span>
      {STATUS_LABEL[status]}
    </span>
  );
}

export default function HealthPage() {
  usePageTitle("Data health");
  const manifest = useManifest();
  return (
    <>
      <h1>Data health</h1>
      <p className="muted">
        Stopwatch collects each agency’s real-time feed every minute. This page shows whether
        collection is working, how much of the schedule we actually observed, and where the gaps are
        — so you can judge how far to trust the numbers.
      </p>
      {manifest.isPending && <Loading label="Loading data health…" />}
      {manifest.error && (
        <ErrorState
          title="Couldn't load data health"
          error={manifest.error}
          onRetry={() => void manifest.refetch()}
        />
      )}
      {manifest.data && (
        <>
          <p className="small muted">
            Current published build <code>{manifest.data.build_id}</code>, generated{" "}
            {formatDateTime(manifest.data.generated_at)}.
          </p>
          {manifest.data.agencies.map((agency) => (
            <AgencyHealth key={agency.id} agency={agency} />
          ))}
        </>
      )}
    </>
  );
}

function AgencyHealth({ agency }: { agency: AgencyManifest }) {
  const health = useHealth(agency);
  const coverage = useCoverage(agency);
  const now = useNow(30_000);
  const h = health.data;
  const status = h ? effectiveStatus(h, now) : null;
  const days = coverage.data?.days.slice(-30) ?? [];
  const latest = days[days.length - 1];

  return (
    <section className="section" aria-labelledby={`health-${agency.id}`}>
      <div className="section-header">
        <h2 id={`health-${agency.id}`}>{agency.name}</h2>
        {status && <StatusBadge status={status} />}
      </div>

      {health.isPending && (
        <Skeleton height="8rem" label={`Loading ${agency.name} collection status`} />
      )}
      {health.error && (
        <ErrorState
          title="Collection status unavailable"
          error={health.error}
          onRetry={() => void health.refetch()}
        />
      )}
      {h && status && (
        <div className="card">
          <p>{STATUS_DESCRIPTION[status]}</p>
          <dl className="stat-grid">
            <div className="stat">
              <dt>Last successful collection</dt>
              <dd>
                {formatRelative(h.last_success_at, now)}
                <span className="sub">{formatDateTime(h.last_success_at, agency.timezone)}</span>
              </dd>
            </div>
            <div className="stat">
              <dt>Feed age</dt>
              <dd>
                {formatDuration(h.feed_age_s)}
                <span className="sub">how old the agency’s data was</span>
              </dd>
            </div>
            <div className="stat">
              <dt>Collections, last hour</dt>
              <dd>
                {h.ticks_last_hour.ok} / {h.ticks_last_hour.expected}
                <span className="sub">
                  {h.ticks_last_hour.failed} failed · {h.ticks_last_hour.not_advanced} feed not
                  updated
                </span>
              </dd>
            </div>
            <div className="stat">
              <dt>Latest day coverage</dt>
              <dd>
                {latest ? formatPct(latest.coverage_pct, 1) : "—"}
                <span className="sub">{latest ? formatDate(latest.service_date) : "no data"}</span>
              </dd>
            </div>
          </dl>
          <p className="small muted">Status file updated {formatRelative(h.generated_at, now)}.</p>
        </div>
      )}

      <h3 className={styles.subheading}>Gaps in the last 7 days</h3>
      {h &&
        (h.recent_gaps.length === 0 ? (
          <p className="muted">No collection gaps of 3 minutes or more.</p>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <caption className="visually-hidden">Collection gaps of 3 minutes or more</caption>
              <thead>
                <tr>
                  <th scope="col">Started</th>
                  <th scope="col">Ended</th>
                  <th scope="col">Length</th>
                </tr>
              </thead>
              <tbody>
                {h.recent_gaps.map((g) => (
                  <tr key={g.start}>
                    <td>{formatDateTime(g.start, agency.timezone)}</td>
                    <td>{formatDateTime(g.end, agency.timezone)}</td>
                    <td>{g.minutes} min</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}

      <h3 className={styles.subheading}>Coverage, last 30 days</h3>
      {coverage.isPending && <Skeleton height="12rem" label="Loading coverage" />}
      {coverage.error && (
        <ErrorState
          title="Coverage unavailable"
          error={coverage.error}
          onRetry={() => void coverage.refetch()}
        />
      )}
      {coverage.data && days.length === 0 && <p className="muted">No coverage data yet.</p>}
      {days.length > 0 && (
        <div className="card">
          <ChartFigure
            title="Share of scheduled trips observed each service day"
            description={
              <>
                Days under the dashed 80% line are marked <strong>low confidence</strong> wherever
                their numbers appear.{" "}
                <Link to="/about/methodology#coverage">What coverage means</Link>
              </>
            }
            height="220px"
            table={
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">Service date</th>
                    <th scope="col">Coverage</th>
                    <th scope="col">Observed</th>
                    <th scope="col">Scheduled</th>
                    <th scope="col">Canceled</th>
                  </tr>
                </thead>
                <tbody>
                  {days.map((d) => (
                    <tr key={d.service_date}>
                      <th scope="row">{formatDate(d.service_date)}</th>
                      <td>{formatPct(d.coverage_pct, 1)}</td>
                      <td>{formatCount(d.observed_trips)}</td>
                      <td>{formatCount(d.scheduled_trips)}</td>
                      <td>{formatCount(d.canceled_trips)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            }
          >
            <CoverageChart days={days} />
          </ChartFigure>
        </div>
      )}
    </section>
  );
}
