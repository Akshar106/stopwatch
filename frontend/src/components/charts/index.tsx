import { lazy, Suspense, type ReactNode } from "react";
import { useNearViewport } from "../../lib/hooks";
import { Skeleton } from "../States";
import styles from "./Charts.module.css";

/**
 * Chart components are lazy so Observable Plot (and d3) stay out of the initial bundle.
 * Every chart is wrapped in a <figure> with a caption and a data-table alternative.
 */
export const DelayHistogramChart = lazy(() => import("./DelayHistogramChart"));
export const TrendChart = lazy(() => import("./TrendChart"));
export const CoverageChart = lazy(() => import("./CoverageChart"));

export function ChartFigure({
  title,
  description,
  table,
  height = "12rem",
  children,
}: {
  title: string;
  description?: ReactNode;
  table?: ReactNode;
  height?: string;
  children: ReactNode;
}) {
  // Plot is the biggest chunk; fetch it only when a chart is about to scroll into view.
  const [ref, near] = useNearViewport<HTMLDivElement>();
  const skeleton = <Skeleton height={height} label={`Loading chart: ${title}`} />;
  return (
    <figure className={styles.figure}>
      <figcaption className={styles.caption}>{title}</figcaption>
      {description && <div className={styles.description}>{description}</div>}
      <div ref={ref} className={styles.chart} style={{ minHeight: height }}>
        {near ? <Suspense fallback={skeleton}>{children}</Suspense> : skeleton}
      </div>
      {table && (
        <details className="disclosure">
          <summary>Show data table</summary>
          <div className="table-scroll">{table}</div>
        </details>
      )}
    </figure>
  );
}
