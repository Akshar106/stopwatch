import { useMemo } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { ChartFigure, TrendChart } from "../../components/charts";
import { RouteBadge } from "../../components/RouteBadge";
import { EmptyState, ErrorState, PageSkeleton } from "../../components/States";
import { tabPanelProps } from "../../components/tabPanelProps";
import { Tabs } from "../../components/Tabs";
import { DataError } from "../../lib/dataClient";
import {
  formatCount,
  formatDate,
  formatDelay,
  formatPct,
  routeFullLabel,
  routeTypeLabel,
} from "../../lib/format";
import { usePageTitle } from "../../lib/hooks";
import { useAgency, useRouteDetail, useRoutesById } from "../../lib/queries";
import type {
  AgencyManifest,
  Direction,
  DirectionId,
  RouteDetail,
  RouteSummary,
  StopCells,
} from "../../lib/types";
import { ReliabilityView } from "../reliability/ReliabilityView";
import styles from "./RoutePage.module.css";

export default function RoutePage() {
  const { agency: agencyId, routeId = "" } = useParams();
  const { agency, isLoading, error, notFound, refetch } = useAgency(agencyId);
  if (isLoading) return <RouteLoading title={`Route ${routeId}`} />;
  if (error)
    return <ErrorState title="Couldn't load transit data" error={error} onRetry={refetch} />;
  if (notFound || !agency) {
    return (
      <EmptyState title="Unknown agency">
        <p>
          We don’t publish data for “{agencyId}”. <Link to="/">Go home</Link>.
        </p>
      </EmptyState>
    );
  }
  return <RouteForAgency agency={agency} routeId={routeId} />;
}

/** One placeholder while the manifest and then the route's data load, so nothing moves in between. */
function RouteLoading({ title }: { title: string }) {
  return (
    <>
      <h1>{title}</h1>
      <PageSkeleton label="Loading route…" />
    </>
  );
}

function RouteForAgency({ agency, routeId }: { agency: AgencyManifest; routeId: string }) {
  const detail = useRouteDetail(agency, routeId);
  const routesById = useRoutesById(agency);
  const summary = routesById.get(routeId);
  const info = detail.data?.route ?? summary;
  const title = info ? routeFullLabel(info) : `Route ${routeId}`;
  usePageTitle(title);

  if (detail.isPending) return <RouteLoading title={title} />;
  if (detail.error) {
    const missing = detail.error instanceof DataError && detail.error.status === 404;
    return (
      <>
        <h1>{title}</h1>
        {missing ? (
          <EmptyState title="No published data for this route">
            <p>
              It may be out of scope (we cover bus and subway) or too new.{" "}
              <Link to="/">Search for a stop</Link>.
            </p>
          </EmptyState>
        ) : (
          <ErrorState
            title="Couldn't load this route"
            error={detail.error}
            onRetry={() => void detail.refetch()}
          />
        )}
      </>
    );
  }
  return <RouteView agency={agency} route={detail.data} summary={summary} />;
}

function RouteView({
  agency,
  route,
  summary,
}: {
  agency: AgencyManifest;
  route: RouteDetail;
  summary: RouteSummary | undefined;
}) {
  const [params, setParams] = useSearchParams();
  const dirParam = Number(params.get("dir"));
  const direction: Direction | undefined =
    route.directions.find((d) => d.direction_id === dirParam) ?? route.directions[0];
  const stopParam = params.get("stop");
  const stop: StopCells | undefined =
    direction?.stops.find((s) => s.stop_id === stopParam) ??
    direction?.stops.find((s) => s.summary.on_time_pct != null) ??
    direction?.stops[0];

  const setParam = (patch: Record<string, string | null>) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        for (const [k, v] of Object.entries(patch)) {
          if (v == null) next.delete(k);
          else next.set(k, v);
        }
        return next;
      },
      { replace: true, preventScrollReset: true },
    );

  const stats = summary?.summary;
  const coverage = route.coverage;
  const lowCoverage = coverage.coverage_pct != null && coverage.coverage_pct < 80;

  return (
    <>
      <header className={styles.header}>
        <RouteBadge route={route.route} size="lg" />
        <div>
          <p className="eyebrow">{routeTypeLabel(route.route.type)}</p>
          <h1>{routeFullLabel(route.route)}</h1>
        </div>
      </header>

      <dl className="stat-grid">
        <div className="stat">
          <dt>On time</dt>
          <dd>{formatPct(stats?.on_time_pct)}</dd>
        </div>
        <div className="stat">
          <dt>Typical delay</dt>
          <dd>{formatDelay(stats?.p50_s)}</dd>
        </div>
        <div className="stat">
          <dt>Worst case (p90)</dt>
          <dd>{formatDelay(stats?.p90_s)}</dd>
        </div>
        <div className="stat">
          <dt>Arrivals observed</dt>
          <dd>{formatCount(stats?.n)}</dd>
        </div>
      </dl>
      <p className="small muted">
        All stops and hours, {formatDate(route.window.from, { year: false })} –{" "}
        {formatDate(route.window.to)}. <Link to="/about/methodology">Methodology</Link>
      </p>

      <section className="section" aria-labelledby="stops-heading">
        <h2 id="stops-heading">Stops</h2>
        {route.directions.length === 0 || !direction ? (
          <EmptyState title="No stop data published for this route." />
        ) : (
          <>
            {route.directions.length > 1 && (
              <Tabs
                label="Direction"
                idPrefix="direction"
                value={direction.direction_id}
                items={route.directions.map((d) => ({
                  value: d.direction_id,
                  label: d.headsign ? `Toward ${d.headsign}` : `Direction ${d.direction_id}`,
                }))}
                onChange={(value: DirectionId) =>
                  setParam({ dir: String(value), stop: null, cell: null })
                }
              />
            )}
            <div
              {...(route.directions.length > 1
                ? tabPanelProps("direction", direction.direction_id)
                : {})}
            >
              <StopList
                stops={direction.stops}
                selected={stop?.stop_id ?? null}
                onSelect={(id) => setParam({ stop: id, cell: null })}
              />
            </div>
          </>
        )}
      </section>

      {stop && direction && (
        <section className="section" aria-labelledby="stop-reliability-heading">
          <div className="section-header">
            <h2 id="stop-reliability-heading">At {stop.name}</h2>
            <Link
              to={`/s/${encodeURIComponent(agency.id)}/${encodeURIComponent(stop.stop_id)}?route=${encodeURIComponent(route.route.id)}&dir=${direction.direction_id}`}
            >
              Stop page with live arrivals
            </Link>
          </div>
          <ReliabilityView
            agency={agency}
            route={route}
            stop={stop}
            headsign={direction.headsign}
          />
        </section>
      )}

      <section className="section" aria-labelledby="trend-heading">
        <h2 id="trend-heading">Weekly trend</h2>
        {route.trend.length === 0 ? (
          <p className="muted">No weekly history yet.</p>
        ) : (
          <div className="card">
            <ChartFigure
              title="Route-level reliability by week"
              description="All stops and hours combined. Each point is one week (Monday start)."
              height="400px"
              table={
                <table className="data-table">
                  <thead>
                    <tr>
                      <th scope="col">Week of</th>
                      <th scope="col">On time</th>
                      <th scope="col">Typical</th>
                      <th scope="col">Worst case</th>
                      <th scope="col">Arrivals</th>
                    </tr>
                  </thead>
                  <tbody>
                    {route.trend.map((p) => (
                      <tr key={p.week_start}>
                        <th scope="row">{formatDate(p.week_start)}</th>
                        <td>{formatPct(p.on_time_pct, 1)}</td>
                        <td>{formatDelay(p.p50_s)}</td>
                        <td>{formatDelay(p.p90_s)}</td>
                        <td>{formatCount(p.n)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              }
            >
              <TrendChart trend={route.trend} />
            </ChartFigure>
          </div>
        )}
      </section>

      <section className="section" aria-labelledby="coverage-heading">
        <h2 id="coverage-heading">Coverage</h2>
        <figure className={`card ${styles.coverage}`}>
          <figcaption className="small muted">
            Scheduled trips we observed in the data window
          </figcaption>
          <p className={styles.coverageValue}>
            <strong className="num">{formatPct(coverage.coverage_pct, 1)}</strong>{" "}
            <span className="muted">
              {formatCount(coverage.observed_trips)} of {formatCount(coverage.scheduled_trips)}{" "}
              trips
            </span>
          </p>
          <div
            className={styles.meter}
            role="img"
            aria-label={`${formatPct(coverage.coverage_pct, 1)} of scheduled trips observed`}
          >
            <span
              className={`${styles.meterFill} ${lowCoverage ? styles.meterLow : ""}`}
              style={{ width: `${Math.min(100, coverage.coverage_pct ?? 0)}%` }}
            />
            <span className={styles.meterMark} style={{ left: "80%" }} aria-hidden="true" />
          </div>
          <p className="small muted">
            {lowCoverage ? (
              <strong>Low confidence: under 80% of trips were observed.</strong>
            ) : (
              "Above the 80% line we consider the numbers reliable."
            )}{" "}
            <Link to="/health">Data health</Link>
          </p>
        </figure>
      </section>
    </>
  );
}

function StopList({
  stops,
  selected,
  onSelect,
}: {
  stops: StopCells[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const ordered = useMemo(() => [...stops].sort((a, b) => a.order - b.order), [stops]);
  return (
    <ol className={styles.stopList}>
      {ordered.map((s) => {
        const pct = s.summary.on_time_pct;
        const isSelected = s.stop_id === selected;
        return (
          <li key={s.stop_id}>
            <button
              type="button"
              className={`${styles.stopButton} ${isSelected ? styles.stopSelected : ""}`}
              aria-pressed={isSelected}
              onClick={() => onSelect(s.stop_id)}
            >
              <span className={styles.stopName}>{s.name}</span>
              <span className={styles.stopStats}>
                <span className={styles.bar} aria-hidden="true">
                  <span className={styles.barFill} style={{ width: `${pct ?? 0}%` }} />
                </span>
                <span className="small num">
                  {pct == null
                    ? "Not enough data"
                    : `${formatPct(pct)} on time · typical ${formatDelay(s.summary.p50_s)}`}
                </span>
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
