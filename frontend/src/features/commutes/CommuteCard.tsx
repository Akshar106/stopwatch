import type { ReactNode } from "react";
import { Link } from "react-router";
import { RouteBadge, UnknownRouteBadge } from "../../components/RouteBadge";
import { formatDays, formatHHMM } from "../../lib/format";
import type { AgencyManifest, Commute } from "../../lib/types";
import { useCommuteNames } from "./api";
import { CommuteSummary } from "./CommuteSummary";
import styles from "./Commutes.module.css";

export function CommuteCard({
  commute,
  agency,
  actions,
  headingLevel = 3,
}: {
  commute: Commute;
  agency: AgencyManifest;
  actions?: ReactNode;
  headingLevel?: 2 | 3;
}) {
  const names = useCommuteNames(commute, agency);
  const Heading = headingLevel === 2 ? "h2" : "h3";
  const title = commute.label || names.stopName;
  const stopHref = `/s/${encodeURIComponent(agency.id)}/${encodeURIComponent(commute.stop_id)}?route=${encodeURIComponent(commute.route_id)}&dir=${commute.direction_id}`;

  return (
    <article className={`card ${styles.card}`} aria-labelledby={`commute-${commute.id}`}>
      <div className={styles.cardHeader}>
        {names.route ? (
          <RouteBadge route={names.route} />
        ) : (
          <UnknownRouteBadge id={commute.route_id} />
        )}
        <div>
          <Heading id={`commute-${commute.id}`} className={styles.cardTitle}>
            <Link to={stopHref}>{title}</Link>
          </Heading>
          <p className="small muted">
            {names.routeLabel}
            {names.headsign && <> · toward {names.headsign}</>}
            {commute.label && <> · {names.stopName}</>}
          </p>
          <p className={`small ${styles.when}`}>
            {formatDays(commute.days)} · {formatHHMM(commute.window_start)}–
            {formatHHMM(commute.window_end)}
          </p>
        </div>
      </div>
      <CommuteSummary commute={commute} agency={agency} />
      {actions && <div className={styles.actions}>{actions}</div>}
    </article>
  );
}
