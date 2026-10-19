import { useMemo } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { RouteBadge, UnknownRouteBadge } from "../../components/RouteBadge";
import { EmptyState, ErrorState, PageSkeleton } from "../../components/States";
import { DataError } from "../../lib/dataClient";
import { routeName } from "../../lib/format";
import { usePageTitle } from "../../lib/hooks";
import { useAgency, useRouteDetail, useRoutesById, useSearchIndex } from "../../lib/queries";
import { resolvePlace, type Place } from "../../lib/search";
import type { AgencyManifest, DirectionId, RouteSummary } from "../../lib/types";
import { LivePanel } from "../live/LivePanel";
import { ReliabilityView } from "../reliability/ReliabilityView";
import styles from "./StopPage.module.css";

export default function StopPage() {
  const { agency: agencyId, stopId = "" } = useParams();
  const { agency, isLoading, error, notFound, refetch } = useAgency(agencyId);

  if (isLoading) return <StopLoading stopId={stopId} />;
  if (error)
    return <ErrorState title="Couldn't load transit data" error={error} onRetry={refetch} />;
  if (notFound || !agency) {
    return (
      <EmptyState title="Unknown agency">
        <p>
          We don’t publish data for “{agencyId}”. <Link to="/">Search for a stop</Link>.
        </p>
      </EmptyState>
    );
  }
  return <StopForAgency agency={agency} stopId={stopId} />;
}

/** One placeholder while the manifest and then the stop list load, so nothing moves in between. */
function StopLoading({ stopId }: { stopId: string }) {
  return (
    <>
      <h1>Stop {stopId}</h1>
      <PageSkeleton label="Loading stop…" />
    </>
  );
}

function StopForAgency({ agency, stopId }: { agency: AgencyManifest; stopId: string }) {
  const { index, query } = useSearchIndex(agency);
  const routesById = useRoutesById(agency);
  const place = useMemo(() => (index ? resolvePlace(index, stopId) : null), [index, stopId]);
  usePageTitle(place?.name ?? null);

  if (query.isPending) return <StopLoading stopId={stopId} />;
  if (query.error) {
    return (
      <ErrorState
        title="Couldn't load the stop list"
        error={query.error}
        onRetry={() => void query.refetch()}
      />
    );
  }
  if (!place) {
    return (
      <>
        <h1>Stop not found</h1>
        <EmptyState title={`We couldn't find stop “${stopId}”.`}>
          <p>
            It may have been removed from the schedule. <Link to="/">Search for another stop</Link>.
          </p>
        </EmptyState>
      </>
    );
  }
  return <StopView agency={agency} place={place} routesById={routesById} />;
}

function StopView({
  agency,
  place,
  routesById,
}: {
  agency: AgencyManifest;
  place: Place;
  routesById: Map<string, RouteSummary>;
}) {
  const [params, setParams] = useSearchParams();
  const routeIds = useMemo(
    () =>
      [...place.routes].sort(
        (a, b) => (routesById.get(a)?.sort_order ?? 1e9) - (routesById.get(b)?.sort_order ?? 1e9),
      ),
    [place.routes, routesById],
  );
  const requestedRoute = params.get("route");
  const routeId =
    requestedRoute && routeIds.includes(requestedRoute) ? requestedRoute : (routeIds[0] ?? null);
  const detail = useRouteDetail(agency, routeId);

  const directions = useMemo(
    () =>
      (detail.data?.directions ?? []).flatMap((d) => {
        const stop = d.stops.find(
          (s) => place.stopIds.includes(s.stop_id) || s.stop_id === place.id,
        );
        return stop ? [{ direction: d, stop }] : [];
      }),
    [detail.data, place],
  );
  const requestedDir = Number(params.get("dir"));
  const current =
    directions.find((d) => d.direction.direction_id === requestedDir) ?? directions[0];

  const choose = (patch: { route?: string; dir?: DirectionId }) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (patch.route !== undefined) {
          next.set("route", patch.route);
          next.delete("dir");
          next.delete("cell");
        }
        if (patch.dir !== undefined) {
          next.set("dir", String(patch.dir));
          next.delete("cell");
        }
        return next;
      },
      { replace: true, preventScrollReset: true, flushSync: true },
    );
  };

  const isStation = place.stopIds.length > 1;

  return (
    <>
      <header className={styles.header}>
        <p className="eyebrow">{isStation ? "Station" : `Stop ${place.id}`}</p>
        <h1>{place.name}</h1>
        <p className={styles.routes}>
          {routeIds.map((id) => {
            const r = routesById.get(id);
            return r ? <RouteBadge key={id} route={r} /> : <UnknownRouteBadge key={id} id={id} />;
          })}
        </p>
      </header>

      {routeIds.length === 0 ? (
        <EmptyState title="No routes with published data serve this stop." />
      ) : (
        <div className={styles.pickers}>
          {routeIds.length > 1 && (
            <fieldset>
              <legend className="label">Route</legend>
              <div className="segmented">
                {routeIds.map((id) => {
                  const r = routesById.get(id);
                  return (
                    <label key={id}>
                      <input
                        type="radio"
                        name="route"
                        value={id}
                        checked={id === routeId}
                        onChange={() => choose({ route: id })}
                      />
                      {r ? routeName(r) : id}
                    </label>
                  );
                })}
              </div>
            </fieldset>
          )}
          {directions.length > 1 && current && (
            <fieldset>
              <legend className="label">Direction</legend>
              <div className="segmented">
                {directions.map(({ direction }) => (
                  <label key={direction.direction_id}>
                    <input
                      type="radio"
                      name="direction"
                      value={direction.direction_id}
                      checked={direction.direction_id === current.direction.direction_id}
                      onChange={() => choose({ dir: direction.direction_id })}
                    />
                    {direction.headsign
                      ? `Toward ${direction.headsign}`
                      : `Direction ${direction.direction_id}`}
                  </label>
                ))}
              </div>
            </fieldset>
          )}
        </div>
      )}

      {routeId && detail.isPending && <PageSkeleton label="Loading reliability data…" />}
      {detail.error && (
        <ErrorState
          title={
            detail.error instanceof DataError && detail.error.status === 404
              ? "Reliability data for this route isn't published yet"
              : "Couldn't load reliability data"
          }
          error={
            detail.error instanceof DataError && detail.error.status === 404
              ? undefined
              : detail.error
          }
          onRetry={() => void detail.refetch()}
        />
      )}
      {detail.data && !current && (
        <EmptyState title="No data for this stop on this route">
          <p>The published data for this route doesn’t include this stop.</p>
        </EmptyState>
      )}
      {detail.data && current && (
        <section aria-labelledby="reliability-heading" className={styles.reliability}>
          <div className="section-header">
            <h2 id="reliability-heading">
              {routeName(detail.data.route)}
              {current.direction.headsign && ` toward ${current.direction.headsign}`}
            </h2>
            <Link
              to={`/r/${encodeURIComponent(agency.id)}/${encodeURIComponent(detail.data.route.id)}?dir=${current.direction.direction_id}&stop=${encodeURIComponent(current.stop.stop_id)}`}
            >
              Compare stops on this route
            </Link>
          </div>
          <ReliabilityView
            agency={agency}
            route={detail.data}
            stop={current.stop}
            headsign={current.direction.headsign}
          />
          <LivePanel
            agency={agency}
            stopId={current.stop.stop_id}
            routeId={detail.data.route.id}
            directionId={current.direction.direction_id}
            headsign={current.direction.headsign}
          />
        </section>
      )}
    </>
  );
}
