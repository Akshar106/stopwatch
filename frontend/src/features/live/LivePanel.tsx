import { useQuery } from "@tanstack/react-query";
import { formatClock } from "../../lib/format";
import { useDocumentVisible, useNow } from "../../lib/hooks";
import { fetchLiveArrivals, LiveError, type LiveArrival } from "../../lib/mbtaLive";
import type { AgencyManifest } from "../../lib/types";
import styles from "./LivePanel.module.css";

const REFRESH_MS = 30_000;

function lateness(a: LiveArrival): { text: string; tone: "ok" | "late" | "early" | "muted" } {
  if (a.status === "canceled") return { text: "Canceled", tone: "late" };
  if (a.status === "skipped") return { text: "Not stopping", tone: "late" };
  if (a.minutesLate == null)
    return { text: a.status === "added" ? "Extra trip" : "No schedule", tone: "muted" };
  if (a.minutesLate > 0)
    return { text: `${a.minutesLate} min late`, tone: a.minutesLate > 5 ? "late" : "ok" };
  if (a.minutesLate < 0)
    return { text: `${-a.minutesLate} min early`, tone: a.minutesLate < -1 ? "early" : "ok" };
  return { text: "On time", tone: "ok" };
}

function countdown(a: LiveArrival, now: Date): string {
  const t = a.predicted ?? a.scheduled;
  if (!t) return "—";
  const minutes = Math.round((t.getTime() - now.getTime()) / 60_000);
  if (minutes <= 0) return "Now";
  return `${minutes} min`;
}

/**
 * "Right now" panel (US-4): next arrivals from the MBTA V3 API, fetched by the browser.
 * Polls every 30 s while the tab is visible, pauses when hidden, and degrades to
 * "Live data unavailable" on errors or rate limiting.
 */
export function LivePanel({
  agency,
  stopId,
  routeId,
  directionId,
  headsign,
}: {
  agency: AgencyManifest;
  stopId: string;
  routeId: string;
  directionId: number;
  headsign: string | null;
}) {
  const visible = useDocumentVisible();
  const now = useNow(15_000);
  const enabled = agency.live_api === "mbta-v3";
  const q = useQuery({
    queryKey: ["live", agency.id, stopId, routeId, directionId],
    queryFn: ({ signal }) => fetchLiveArrivals({ stopId, routeId, directionId }, signal),
    enabled,
    staleTime: REFRESH_MS - 5_000,
    refetchInterval: visible ? REFRESH_MS : false,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    retry: (count, err) => !(err instanceof LiveError && err.kind === "rate_limited") && count < 1,
  });

  if (!enabled) return null;

  return (
    <section className={`card ${styles.panel}`} aria-labelledby="live-heading">
      <div className={styles.header}>
        <h2 id="live-heading" className={styles.title}>
          <span className={styles.dot} aria-hidden="true" />
          Right now
        </h2>
        {q.dataUpdatedAt > 0 && !q.error && (
          <span className="small muted">
            Updated {formatClock(new Date(q.dataUpdatedAt), agency.timezone)}
            {!visible && " · paused"}
          </span>
        )}
      </div>
      <p className="small muted">
        Next arrivals{headsign ? ` toward ${headsign}` : ""}, straight from the MBTA’s live
        predictions.
      </p>

      {q.isPending && (
        <p className="muted" role="status">
          Loading live predictions…
        </p>
      )}

      {q.error && (
        <div className="notice" role="status">
          <p>
            <strong>Live data unavailable.</strong>{" "}
            {q.error instanceof LiveError && q.error.kind === "rate_limited"
              ? "The MBTA’s service is limiting requests right now; we’ll try again shortly."
              : "We couldn’t reach the MBTA’s live service. The reliability history above is unaffected."}
          </p>
          <button
            type="button"
            className="btn btn-small"
            onClick={() => void q.refetch()}
            disabled={q.isFetching}
          >
            {q.isFetching ? "Retrying…" : "Try again"}
          </button>
        </div>
      )}

      {q.data && q.data.length === 0 && !q.error && (
        <p className="muted">No upcoming arrivals are predicted for this stop right now.</p>
      )}

      {q.data && q.data.length > 0 && !q.error && (
        <table className={`data-table ${styles.table}`}>
          <caption className="visually-hidden">
            Next arrivals with predicted and scheduled times
          </caption>
          <thead>
            <tr>
              <th scope="col">Arrives</th>
              <th scope="col">Predicted</th>
              <th scope="col">Scheduled</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {q.data.map((a) => {
              const late = lateness(a);
              return (
                <tr
                  key={a.id}
                  className={
                    a.status === "canceled" || a.status === "skipped" ? styles.canceled : undefined
                  }
                >
                  <td className={styles.countdown}>{countdown(a, now)}</td>
                  <td>{a.predicted ? formatClock(a.predicted, agency.timezone) : "—"}</td>
                  <td>{a.scheduled ? formatClock(a.scheduled, agency.timezone) : "—"}</td>
                  <td>
                    <span className={`${styles.status} ${styles[late.tone]}`}>{late.text}</span>
                    {a.note && <span className="small muted"> · {a.note}</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}
