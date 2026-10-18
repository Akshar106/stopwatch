import { useMemo } from "react";
import { Link, useSearchParams } from "react-router";
import { CellDetail } from "../../components/CellDetail";
import { Heatmap, HeatmapLegend } from "../../components/Heatmap";
import {
  findCell,
  formatCellKey,
  hasEnoughData,
  parseCellKey,
  type CellKey,
} from "../../lib/cells";
import type { HeatmapMetric } from "../../lib/color";
import { formatDate, formatPct, routeName } from "../../lib/format";
import { nowInZone } from "../../lib/schedule";
import type { AgencyManifest, RouteDetail, StopCells } from "../../lib/types";
import styles from "./ReliabilityView.module.css";

function defaultCell(stop: StopCells, timezone: string, minSamples: number): CellKey | null {
  const now = nowInZone(timezone);
  const current = findCell(stop.cells, { day: now.dayType, hour: now.hour });
  if (current && hasEnoughData(current, minSamples))
    return { day: current.day, hour: current.hour };
  const busiest = [...stop.cells].sort((a, b) => b.n - a.n)[0];
  return busiest ? { day: busiest.day, hour: busiest.hour } : null;
}

/**
 * Heatmap + cell detail for one stop in one direction of a route. Metric and selected cell
 * live in the URL (?metric=ontime&cell=wkd-8) so a view can be shared as a link.
 */
export function ReliabilityView({
  agency,
  route,
  stop,
  headsign,
}: {
  agency: AgencyManifest;
  route: RouteDetail;
  stop: StopCells;
  headsign: string | null;
}) {
  const [params, setParams] = useSearchParams();
  const metric: HeatmapMetric = params.get("metric") === "ontime" ? "on_time" : "p50";
  const minSamples = route.min_samples;
  const fallback = useMemo(
    () => defaultCell(stop, agency.timezone, minSamples),
    [stop, agency.timezone, minSamples],
  );
  const selectedKey = parseCellKey(params.get("cell")) ?? fallback;
  const selected = findCell(stop.cells, selectedKey) ?? findCell(stop.cells, fallback);

  const update = (key: string, value: string | null) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (value == null) next.delete(key);
        else next.set(key, value);
        return next;
      },
      // flushSync keeps the controlled radios in step with the URL on the same frame.
      { replace: true, preventScrollReset: true, flushSync: true },
    );
  };

  const caption = `Reliability of ${routeName(route.route)}${
    headsign ? ` toward ${headsign}` : ""
  } at ${stop.name}, by day type and hour`;

  return (
    <div className={styles.view}>
      <div className={styles.toolbar}>
        <fieldset className={styles.metric}>
          <legend className="visually-hidden">Color the grid by</legend>
          <div className="segmented">
            <label>
              <input
                type="radio"
                name="metric"
                value="p50"
                checked={metric === "p50"}
                onChange={() => update("metric", null)}
              />
              Typical delay
            </label>
            <label>
              <input
                type="radio"
                name="metric"
                value="ontime"
                checked={metric === "on_time"}
                onChange={() => update("metric", "ontime")}
              />
              % on time
            </label>
          </div>
        </fieldset>
        <p className={`small muted ${styles.window}`}>
          {formatDate(route.window.from, { year: false })} – {formatDate(route.window.to)} ·{" "}
          {route.window.days} days · hours in {agency.timezone.replace("_", " ")} time ·{" "}
          <Link to="/about/methodology">How we measure</Link>
        </p>
      </div>
      {route.coverage.coverage_pct != null && route.coverage.coverage_pct < 80 && (
        <p className="notice notice-warning small">
          <strong>Low confidence:</strong> only {formatPct(route.coverage.coverage_pct)} of this
          route’s scheduled trips were observed in this period.
        </p>
      )}
      <div className={styles.grid}>
        <div>
          <Heatmap
            cells={stop.cells}
            metric={metric}
            minSamples={minSamples}
            selected={selected ? { day: selected.day, hour: selected.hour } : null}
            onSelect={(cell) => update("cell", formatCellKey(cell))}
            caption={caption}
          />
          <HeatmapLegend metric={metric} minSamples={minSamples} />
        </div>
        <CellDetail
          cell={selected}
          edges={route.histogram_edges_s}
          onTime={route.on_time_definition_s}
          minSamples={minSamples}
        />
      </div>
    </div>
  );
}
