import { useMemo } from "react";
import { Link } from "react-router";
import { RouteBadge } from "../../components/RouteBadge";
import { ErrorState, Loading } from "../../components/States";
import { formatPct, routeFullLabel, routeShortLabel, routeTypeLabel } from "../../lib/format";
import { usePageTitle } from "../../lib/hooks";
import {
  useDefaultAgency,
  useManifest,
  useRoutesById,
  useRoutesList,
  useSearchIndex,
} from "../../lib/queries";
import type { AgencyManifest } from "../../lib/types";
import { useSession } from "../auth/session";
import { useCommutes } from "../commutes/api";
import { CommuteCard } from "../commutes/CommuteCard";
import { NearMe } from "../search/NearMe";
import { StopSearch } from "../search/StopSearch";
import styles from "./HomePage.module.css";

export default function HomePage() {
  usePageTitle(null);
  const { agency, isLoading, error, refetch } = useDefaultAgency();
  const { me } = useSession();

  return (
    <>
      <section className={styles.hero} aria-labelledby="home-title">
        <h1 id="home-title" className={styles.title}>
          How reliable is your stop?
        </h1>
        <p className={styles.lede}>
          Hour-by-hour delays and on-time rates for every bus and subway stop
          {agency ? ` on the ${agency.name}` : ""}, measured from the live feed every minute.
        </p>
        {isLoading && <Loading label="Loading stops…" />}
        {error && <ErrorState title="Couldn't load transit data" error={error} onRetry={refetch} />}
        {agency && <SearchArea agency={agency} />}
      </section>

      {me && agency && <YourCommutes agency={agency} />}
      {agency && <RoutesOverview agency={agency} />}
    </>
  );
}

function SearchArea({ agency }: { agency: AgencyManifest }) {
  const { index, query } = useSearchIndex(agency);
  const routesById = useRoutesById(agency);
  return (
    <div className={`card ${styles.searchCard}`}>
      <StopSearch
        agencyId={agency.id}
        index={index}
        routesById={routesById}
        loading={query.isPending}
      />
      {query.error && (
        <ErrorState
          title="Couldn't load the stop list"
          error={query.error}
          onRetry={() => void query.refetch()}
        />
      )}
      <NearMe agencyId={agency.id} index={index} routesById={routesById} />
    </div>
  );
}

function YourCommutes({ agency }: { agency: AgencyManifest }) {
  const commutes = useCommutes(true);
  const manifest = useManifest();
  if (commutes.isPending) return <Loading label="Loading your commutes…" />;
  if (commutes.error)
    return <ErrorState title="Couldn't load your commutes" error={commutes.error} />;
  return (
    <section className="section" aria-labelledby="your-commutes">
      <div className="section-header">
        <h2 id="your-commutes">Your commutes</h2>
        <Link to="/commutes">Manage commutes</Link>
      </div>
      {commutes.data.length === 0 ? (
        <p className="muted">
          You haven’t saved a commute yet. <Link to="/commutes">Add one</Link> to see its
          reliability here.
        </p>
      ) : (
        <ul className={styles.commutes}>
          {commutes.data.map((c) => (
            <li key={c.id}>
              <CommuteCard
                commute={c}
                agency={manifest.data?.agencies.find((a) => a.id === c.agency_id) ?? agency}
              />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function RoutesOverview({ agency }: { agency: AgencyManifest }) {
  const routes = useRoutesList(agency);
  const sorted = useMemo(
    () =>
      [...(routes.data?.routes ?? [])].sort(
        (a, b) => (a.sort_order ?? 1e9) - (b.sort_order ?? 1e9),
      ),
    [routes.data],
  );
  if (routes.isPending || routes.error) return null;
  return (
    <section className="section" aria-labelledby="routes-heading">
      <div className="section-header">
        <h2 id="routes-heading">Browse routes</h2>
        <span className="small muted">On-time rate over the last {agency.window.days} days</span>
      </div>
      <ul className={styles.routes}>
        {sorted.map((r) => (
          <li key={r.id}>
            <Link
              to={`/r/${encodeURIComponent(agency.id)}/${encodeURIComponent(r.id)}`}
              className={styles.routeLink}
            >
              <RouteBadge route={r} />
              <span className={styles.routeName}>
                {routeFullLabel(r) === routeShortLabel(r)
                  ? routeTypeLabel(r.type)
                  : routeFullLabel(r)}
              </span>
              <span className={`num ${styles.routeStat}`}>
                {formatPct(r.summary.on_time_pct)}
                <span className="visually-hidden"> on time</span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
