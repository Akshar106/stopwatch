import { useState } from "react";
import { Link } from "react-router";
import { formatDistance, nearestPlaces, walkingMinutes, type NearbyPlace } from "../../lib/geo";
import type { SearchIndex } from "../../lib/search";
import type { RouteSummary } from "../../lib/types";
import { RouteChips } from "./StopSearch";
import styles from "./NearMe.module.css";

type State =
  | { kind: "idle" }
  | { kind: "locating" }
  | { kind: "done"; results: NearbyPlace[] }
  | { kind: "error"; message: string };

const GEO_ERRORS: Record<number, string> = {
  1: "Location permission was denied. You can still search by name.",
  2: "Your location isn't available right now. Try again or search by name.",
  3: "Finding your location took too long. Try again or search by name.",
};

/**
 * "Near me" (US-2). The position from navigator.geolocation stays in component state: nearest
 * stops are computed here from the stop index already downloaded, and nothing about the
 * position is sent anywhere (an E2E test asserts no request contains the coordinates).
 */
export function NearMe({
  agencyId,
  index,
  routesById,
}: {
  agencyId: string;
  index: SearchIndex | null;
  routesById: Map<string, RouteSummary>;
}) {
  const [state, setState] = useState<State>({ kind: "idle" });

  const locate = () => {
    if (!("geolocation" in navigator)) {
      setState({
        kind: "error",
        message: "This browser can't share its location. Search by name instead.",
      });
      return;
    }
    setState({ kind: "locating" });
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        if (!index) {
          setState({
            kind: "error",
            message: "The stop list hasn't loaded yet. Try again in a moment.",
          });
          return;
        }
        const origin = { lat: pos.coords.latitude, lon: pos.coords.longitude };
        setState({ kind: "done", results: nearestPlaces(index.places, origin, 10) });
      },
      (err) => setState({ kind: "error", message: GEO_ERRORS[err.code] ?? GEO_ERRORS[2]! }),
      { enableHighAccuracy: false, timeout: 10_000, maximumAge: 60_000 },
    );
  };

  return (
    <section className={styles.nearMe} aria-labelledby="near-me-heading">
      <div className={styles.header}>
        <h2 id="near-me-heading" className={styles.heading}>
          Stops near you
        </h2>
        <button
          type="button"
          className="btn"
          onClick={locate}
          disabled={state.kind === "locating" || !index}
          aria-describedby="near-me-privacy"
        >
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
            <circle cx="12" cy="12" r="3.5" fill="currentColor" />
            <path
              d="M12 2v4M12 18v4M2 12h4M18 12h4"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            />
            <circle cx="12" cy="12" r="7" fill="none" stroke="currentColor" strokeWidth="2" />
          </svg>
          {state.kind === "locating" ? "Finding you…" : "Near me"}
        </button>
      </div>
      <p id="near-me-privacy" className="small muted">
        Your location never leaves this device: nearest stops are worked out in your browser.
      </p>
      <div aria-live="polite">
        {state.kind === "error" && <p className="notice notice-warning">{state.message}</p>}
        {state.kind === "done" && (
          <ol className={styles.list} aria-label="Nearest stops">
            {state.results.map(({ place, distanceM }) => (
              <li key={place.id}>
                <Link
                  to={`/s/${encodeURIComponent(agencyId)}/${encodeURIComponent(place.id)}`}
                  className={styles.item}
                >
                  <span className={styles.name}>{place.name}</span>
                  <span className={styles.meta}>
                    <RouteChips ids={place.routes} routesById={routesById} />
                    <span className="small muted num">
                      {formatDistance(distanceM)} · ~{walkingMinutes(distanceM)} min walk
                    </span>
                  </span>
                </Link>
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}
