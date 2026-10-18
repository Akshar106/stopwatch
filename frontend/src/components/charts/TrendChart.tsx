import * as Plot from "@observablehq/plot";
import type { TrendPoint } from "../../lib/types";
import { usePlot } from "./usePlot";

const parseWeek = (s: string) => new Date(`${s}T00:00:00Z`);

/** Weekly route-level trend: on-time % (top) and p50/p90 delay in minutes (bottom). */
export default function TrendChart({ trend }: { trend: TrendPoint[] }) {
  const onTimeRef = usePlot(
    (width) => {
      const data = trend
        .filter((p) => p.on_time_pct != null)
        .map((p) => ({ week: parseWeek(p.week_start), pct: p.on_time_pct! }));
      return Plot.plot({
        width,
        height: 180,
        marginLeft: 40,
        ariaLabel: "Weekly on-time percentage",
        style: { fontSize: "12px", background: "transparent" },
        x: {
          type: "utc",
          label: null,
          inset: 12,
          tickFormat: "%b %d",
          ticks: Math.min(8, Math.floor(width / 80)),
        },
        y: { label: "On time (%)", grid: true, nice: true },
        marks: [
          Plot.lineY(data, { x: "week", y: "pct", stroke: "#2f7fd6", strokeWidth: 2 }),
          Plot.dot(data, { x: "week", y: "pct", fill: "#2f7fd6", r: 3.5 }),
          Plot.tip(
            data,
            Plot.pointerX({
              x: "week",
              y: "pct",
              title: (d: { week: Date; pct: number }) =>
                `Week of ${d.week.toISOString().slice(0, 10)}\n${d.pct.toFixed(1)}% on time`,
            }),
          ),
        ],
      });
    },
    [trend],
  );

  const delayRef = usePlot(
    (width) => {
      const data = trend.flatMap((p) => [
        ...(p.p50_s != null
          ? [{ week: parseWeek(p.week_start), minutes: p.p50_s / 60, series: "Typical (p50)" }]
          : []),
        ...(p.p90_s != null
          ? [{ week: parseWeek(p.week_start), minutes: p.p90_s / 60, series: "Worst case (p90)" }]
          : []),
      ]);
      return Plot.plot({
        width,
        height: 200,
        marginLeft: 40,
        ariaLabel: "Weekly typical and worst-case delay in minutes",
        style: { fontSize: "12px", background: "transparent" },
        x: {
          type: "utc",
          label: null,
          inset: 12,
          tickFormat: "%b %d",
          ticks: Math.min(8, Math.floor(width / 80)),
        },
        y: { label: "Delay (min)", grid: true, nice: true },
        color: {
          domain: ["Typical (p50)", "Worst case (p90)"],
          range: ["#e0773a", "#a32a0f"],
          legend: true,
        },
        marks: [
          Plot.ruleY([0]),
          Plot.lineY(
            data.filter((d) => d.series.startsWith("Typical")),
            { x: "week", y: "minutes", stroke: "series", strokeWidth: 2 },
          ),
          Plot.lineY(
            data.filter((d) => d.series.startsWith("Worst")),
            { x: "week", y: "minutes", stroke: "series", strokeWidth: 2, strokeDasharray: "5,3" },
          ),
          Plot.dot(data, { x: "week", y: "minutes", fill: "series", r: 3 }),
        ],
      });
    },
    [trend],
  );

  return (
    <div className="stack">
      <div ref={onTimeRef} className="chart-mount" />
      <div ref={delayRef} className="chart-mount" />
    </div>
  );
}
