import { useMemo, useRef, type KeyboardEvent } from "react";
import {
  DELAY_BINS,
  delayBin,
  ON_TIME_BINS,
  onTimeBin,
  readableTextOn,
  type HeatmapMetric,
} from "../lib/color";
import { cellLabel, cellText, hasEnoughData, type CellKey } from "../lib/cells";
import { DAY_TYPE_LABEL, DAY_TYPE_SHORT, hourLabel } from "../lib/format";
import { serviceHourOrder } from "../lib/schedule";
import { DAY_TYPES, type Cell, type DayType } from "../lib/types";
import styles from "./Heatmap.module.css";

function cellVisual(cell: Cell, metric: HeatmapMetric, minSamples: number) {
  if (!hasEnoughData(cell, minSamples)) return null;
  const bg = metric === "p50" ? delayBin(cell.p50_s!).color : onTimeBin(cell.on_time_pct!).color;
  return { bg, fg: readableTextOn(bg), text: cellText(cell, metric, minSamples) };
}

/**
 * Day type × hour reliability grid. Rows are hours in service-day order (4 AM first) so the
 * grid reads top-to-bottom on a phone; columns are weekday / Saturday / Sunday.
 *
 * Accessibility: a real <table> with row/column headers; every cell prints its value and has
 * a full spoken label; one roving tab stop with arrow-key navigation; selection is
 * aria-pressed. Thin-data cells are hatched *and* say so in text.
 */
export function Heatmap({
  cells,
  metric,
  minSamples,
  selected,
  onSelect,
  caption,
}: {
  cells: Cell[];
  metric: HeatmapMetric;
  minSamples: number;
  selected: CellKey | null;
  onSelect: (cell: Cell) => void;
  caption: string;
}) {
  const { hours, lookup } = useMemo(() => {
    const lookup = new Map<string, Cell>();
    const hourSet = new Set<number>();
    for (const c of cells) {
      lookup.set(`${c.day}-${c.hour}`, c);
      hourSet.add(c.hour);
    }
    const hours = [...hourSet].sort((a, b) => serviceHourOrder(a) - serviceHourOrder(b));
    return { hours, lookup };
  }, [cells]);

  const buttonRefs = useRef(new Map<string, HTMLButtonElement>());
  const firstKey = useMemo(() => {
    for (const h of hours)
      for (const d of DAY_TYPES) if (lookup.has(`${d}-${h}`)) return `${d}-${h}`;
    return null;
  }, [hours, lookup]);
  const selectedKey = selected ? `${selected.day}-${selected.hour}` : null;
  const tabStop = selectedKey && lookup.has(selectedKey) ? selectedKey : firstKey;

  const move = (e: KeyboardEvent<HTMLButtonElement>, day: DayType, hour: number) => {
    const col = DAY_TYPES.indexOf(day);
    const row = hours.indexOf(hour);
    const steps: Record<string, [number, number]> = {
      ArrowUp: [-1, 0],
      ArrowDown: [1, 0],
      ArrowLeft: [0, -1],
      ArrowRight: [0, 1],
    };
    const step = steps[e.key];
    let target: Cell | undefined;
    if (step) {
      let r = row + step[0];
      let c = col + step[1];
      while (r >= 0 && r < hours.length && c >= 0 && c < DAY_TYPES.length) {
        target = lookup.get(`${DAY_TYPES[c]}-${hours[r]}`);
        if (target) break;
        r += step[0];
        c += step[1];
      }
    } else if (e.key === "Home" || e.key === "End") {
      const rowCells = DAY_TYPES.map((d) => lookup.get(`${d}-${hour}`)).filter(Boolean) as Cell[];
      target = e.key === "Home" ? rowCells[0] : rowCells[rowCells.length - 1];
    } else {
      return;
    }
    e.preventDefault();
    if (target) {
      onSelect(target);
      buttonRefs.current.get(`${target.day}-${target.hour}`)?.focus();
    }
  };

  if (cells.length === 0) {
    return <p className="muted">No scheduled service at this stop in the data window.</p>;
  }

  return (
    <div className={styles.wrap}>
      <table className={styles.table}>
        <caption className="visually-hidden">
          {caption}. Use the arrow keys to move between cells; the selected cell's details appear
          below the grid.
        </caption>
        <thead>
          <tr>
            <th scope="col" className={styles.corner}>
              <span className="visually-hidden">Hour</span>
            </th>
            {DAY_TYPES.map((d) => (
              <th key={d} scope="col" className={styles.colHeader}>
                <abbr title={DAY_TYPE_LABEL[d]} className={styles.abbr}>
                  {DAY_TYPE_SHORT[d]}
                </abbr>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {hours.map((hour) => (
            <tr key={hour}>
              <th scope="row" className={styles.rowHeader}>
                {hourLabel(hour)}
              </th>
              {DAY_TYPES.map((day) => {
                const key = `${day}-${hour}`;
                const cell = lookup.get(key);
                if (!cell) {
                  return (
                    <td key={key} className={styles.empty}>
                      <span aria-hidden="true">·</span>
                      <span className="visually-hidden">No scheduled service</span>
                    </td>
                  );
                }
                const visual = cellVisual(cell, metric, minSamples);
                const isSelected = key === selectedKey;
                const label = cellLabel(cell, minSamples, metric);
                return (
                  <td key={key} className={styles.td}>
                    <button
                      ref={(el) => {
                        if (el) buttonRefs.current.set(key, el);
                        else buttonRefs.current.delete(key);
                      }}
                      type="button"
                      className={`${styles.cell} ${visual ? "" : styles.thin} ${isSelected ? styles.selected : ""}`}
                      style={visual ? { background: visual.bg, color: visual.fg } : undefined}
                      aria-pressed={isSelected}
                      aria-label={label}
                      title={label}
                      tabIndex={key === tabStop ? 0 : -1}
                      onClick={() => onSelect(cell)}
                      onKeyDown={(e) => move(e, day, hour)}
                      data-testid={`cell-${key}`}
                    >
                      {visual ? visual.text : "—"}
                    </button>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function HeatmapLegend({
  metric,
  minSamples,
}: {
  metric: HeatmapMetric;
  minSamples: number;
}) {
  const bins = metric === "p50" ? DELAY_BINS : ON_TIME_BINS;
  return (
    <div className={styles.legend}>
      <p className={styles.legendTitle}>
        {metric === "p50" ? "Typical delay (median, minutes)" : "Arrivals on time"}
      </p>
      <ul className={styles.legendList}>
        {bins.map((b) => (
          <li key={b.label}>
            <span className={styles.swatch} style={{ background: b.color }} aria-hidden="true" />
            {b.label}
          </li>
        ))}
        <li>
          <span className={`${styles.swatch} ${styles.thin}`} aria-hidden="true" />
          Not enough data (fewer than {minSamples} arrivals)
        </li>
        <li>
          <span className={`${styles.swatch} ${styles.swatchEmpty}`} aria-hidden="true">
            ·
          </span>
          No scheduled service
        </li>
      </ul>
    </div>
  );
}
