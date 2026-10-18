import { Link } from "react-router";
import { bucketLabels, hasEnoughData } from "../lib/cells";
import {
  DAY_TYPE_LABEL,
  formatCount,
  formatDelay,
  formatDuration,
  formatPct,
  hourRangeLabel,
} from "../lib/format";
import type { Cell } from "../lib/types";
import { ChartFigure, DelayHistogramChart } from "./charts";
import styles from "./CellDetail.module.css";

/** Detail panel for one heatmap cell (US-3, US-5). */
export function CellDetail({
  cell,
  edges,
  onTime,
  minSamples,
}: {
  cell: Cell | null;
  edges: number[];
  onTime: [number, number];
  minSamples: number;
}) {
  if (!cell) {
    return (
      <section className={`card ${styles.panel}`} aria-label="Cell details">
        <p className="muted">Select a cell in the grid to see its details.</p>
      </section>
    );
  }
  const enough = hasEnoughData(cell, minSamples);
  const heading = `${DAY_TYPE_LABEL[cell.day]}, ${hourRangeLabel(cell.hour)}`;
  const labels = bucketLabels(edges);
  const total = cell.hist.reduce((a, b) => a + b, 0);

  return (
    <section
      className={`card ${styles.panel}`}
      aria-labelledby="cell-detail-heading"
      aria-live="polite"
    >
      <p className="eyebrow">Scheduled arrivals</p>
      <h3 id="cell-detail-heading">{heading}</h3>
      {!enough ? (
        <div className="notice" data-testid="not-enough-data">
          <p>
            <strong>Not enough data.</strong> Only {formatCount(cell.n)} observed{" "}
            {cell.n === 1 ? "arrival" : "arrivals"} in this hour; we show statistics once there are
            at least {minSamples}.
          </p>
          {(cell.canceled > 0 || cell.skipped > 0) && (
            <p className="small">
              Canceled trips: {formatCount(cell.canceled)} · Skipped stops:{" "}
              {formatCount(cell.skipped)}
            </p>
          )}
        </div>
      ) : (
        <>
          <dl className="stat-grid">
            <div className="stat">
              <dt>Typical delay (p50)</dt>
              <dd>{formatDelay(cell.p50_s)}</dd>
            </div>
            <div className="stat">
              <dt>Worst case (p90)</dt>
              <dd>{formatDelay(cell.p90_s)}</dd>
            </div>
            <div className="stat">
              <dt>On time</dt>
              <dd>
                {formatPct(cell.on_time_pct)}
                <span className="sub">
                  {formatDelay(onTime[0])} to {formatDelay(onTime[1])}
                </span>
              </dd>
            </div>
            <div className="stat">
              <dt>Early</dt>
              <dd>
                {formatPct(cell.early_pct)}
                <span className="sub">
                  more than {formatDelay(Math.abs(onTime[0])).replace("+", "")} early
                </span>
              </dd>
            </div>
            <div className="stat">
              <dt>Observed arrivals</dt>
              <dd>{formatCount(cell.n)}</dd>
            </div>
            <div className="stat">
              <dt>Canceled / skipped</dt>
              <dd>
                {formatCount(cell.canceled)} / {formatCount(cell.skipped)}
                <span className="sub">counted separately, never “on time”</span>
              </dd>
            </div>
            {cell.ewt_s != null && (
              <div className="stat">
                <dt>Excess wait time</dt>
                <dd>
                  {formatDelay(cell.ewt_s)}
                  <span className="sub">
                    vs schedule
                    {cell.sched_headway_s != null &&
                      ` (every ${formatDuration(cell.sched_headway_s)})`}
                  </span>
                </dd>
              </div>
            )}
          </dl>
          {cell.ewt_s != null && (
            <details className={`disclosure ${styles.help}`}>
              <summary>What is excess wait time?</summary>
              <p className="small">
                On frequent service riders don’t time their arrival to a schedule, so the useful
                question is how much longer than planned they wait on average. Excess wait time is
                the average actual wait minus the average scheduled wait, from the gaps between
                consecutive arrivals. It only appears when buses or trains are scheduled at least
                every 12 minutes. <Link to="/about/methodology#ewt">Methodology</Link>
              </p>
            </details>
          )}
          <ChartFigure
            title="How late arrivals were"
            description={`Share of ${formatCount(total)} arrivals by delay. Green bars are on time.`}
            height="200px"
            table={
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">Delay (min)</th>
                    <th scope="col">Arrivals</th>
                    <th scope="col">Share</th>
                  </tr>
                </thead>
                <tbody>
                  {cell.hist.map((count, i) => (
                    <tr key={labels[i]}>
                      <th scope="row">{labels[i]}</th>
                      <td>{formatCount(count)}</td>
                      <td>{total ? formatPct((100 * count) / total) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            }
          >
            <DelayHistogramChart
              hist={cell.hist}
              edges={edges}
              onTime={onTime}
              label={`Delay distribution for ${heading}`}
            />
          </ChartFigure>
        </>
      )}
    </section>
  );
}
