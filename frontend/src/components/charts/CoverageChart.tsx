import * as Plot from "@observablehq/plot";
import type { CoverageDay } from "../../lib/types";
import { usePlot } from "./usePlot";

export const LOW_CONFIDENCE_PCT = 80;

/** Daily coverage (% of scheduled trips observed), with the 80% low-confidence line. */
export default function CoverageChart({ days }: { days: CoverageDay[] }) {
  const ref = usePlot(
    (width) => {
      const data = days
        .filter((d) => d.coverage_pct != null)
        .map((d) => ({
          date: new Date(`${d.service_date}T00:00:00Z`),
          pct: d.coverage_pct!,
          low: d.coverage_pct! < LOW_CONFIDENCE_PCT ? "Below 80% (low confidence)" : "80% or more",
        }));
      return Plot.plot({
        width,
        height: 200,
        marginLeft: 40,
        ariaLabel: "Daily coverage: percent of scheduled trips observed",
        style: { fontSize: "12px", background: "transparent" },
        x: { type: "band", label: null, tickFormat: "%b %d", ticks: [], axis: null },
        y: { label: "Coverage (%)", domain: [0, 100], grid: true },
        color: {
          domain: ["80% or more", "Below 80% (low confidence)"],
          range: ["#3d9a5f", "#d4542a"],
          legend: true,
        },
        marks: [
          Plot.barY(data, { x: "date", y: "pct", fill: "low", inset: 0.5 }),
          Plot.ruleY([LOW_CONFIDENCE_PCT], {
            stroke: "currentColor",
            strokeDasharray: "4,3",
            strokeOpacity: 0.7,
          }),
          Plot.axisX({
            ticks: data.filter((_, i) => i % 7 === 0).map((d) => d.date),
            tickFormat: "%b %d",
            label: null,
          }),
          Plot.tip(
            data,
            Plot.pointerX({
              x: "date",
              y: "pct",
              title: (d: { date: Date; pct: number }) =>
                `${d.date.toISOString().slice(0, 10)}\n${d.pct.toFixed(1)}% observed`,
            }),
          ),
        ],
      });
    },
    [days],
  );
  return <div ref={ref} className="chart-mount" />;
}
