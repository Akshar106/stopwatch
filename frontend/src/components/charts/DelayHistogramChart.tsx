import * as Plot from "@observablehq/plot";
import { bucketLabels } from "../../lib/cells";
import { usePlot } from "./usePlot";

const EARLY = "#5b8fd1";
const ON_TIME = "#3d9a5f";
const LATE = "#e0773a";

/** Bar chart of a cell's delay histogram (bucket counts per histogram_edges_s). */
export default function DelayHistogramChart({
  hist,
  edges,
  onTime,
  label,
}: {
  hist: number[];
  edges: number[];
  onTime: [number, number];
  label: string;
}) {
  const ref = usePlot(
    (width) => {
      const total = hist.reduce((a, b) => a + b, 0) || 1;
      const labels = bucketLabels(edges);
      const data = hist.map((count, i) => {
        const lo = i === 0 ? -Infinity : edges[i - 1]!;
        const hi = i === edges.length ? Infinity : edges[i]!;
        const kind =
          hi <= onTime[0]
            ? "early"
            : lo >= onTime[0] && hi <= onTime[1]
              ? "on time"
              : lo < onTime[0]
                ? "early"
                : "late";
        return { bucket: labels[i]!, share: (100 * count) / total, count, kind };
      });
      return Plot.plot({
        width,
        height: 200,
        marginLeft: 40,
        marginBottom: 36,
        ariaLabel: label,
        style: { fontSize: "12px", background: "transparent" },
        x: { domain: labels, label: "Delay (minutes)", tickSize: 0 },
        y: { label: "% of arrivals", grid: true, nice: true },
        color: { domain: ["early", "on time", "late"], range: [EARLY, ON_TIME, LATE] },
        marks: [
          Plot.barY(data, { x: "bucket", y: "share", fill: "kind", rx: 2 }),
          Plot.text(data, {
            x: "bucket",
            y: "share",
            text: (d: { share: number }) => (d.share >= 0.5 ? `${Math.round(d.share)}%` : ""),
            dy: -7,
            fill: "currentColor",
          }),
          Plot.ruleY([0]),
        ],
      });
    },
    [hist, edges, onTime, label],
  );
  return <div ref={ref} className="chart-mount" />;
}
