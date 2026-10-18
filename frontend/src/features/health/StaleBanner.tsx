import { Link } from "react-router";
import { formatRelative } from "../../lib/format";
import { effectiveStatus } from "../../lib/health";
import { useNow } from "../../lib/hooks";
import { useAllHealth, useManifest } from "../../lib/queries";
import styles from "./StaleBanner.module.css";

/** Site-wide banner when an agency's collection is more than 15 minutes stale (US-11). */
export function StaleBanner() {
  const manifest = useManifest();
  const agencies = manifest.data?.agencies ?? [];
  const health = useAllHealth(agencies);
  const now = useNow(60_000);
  const stale = agencies
    .map((agency, i) => ({ agency, health: health[i] }))
    .filter((x) => x.health && effectiveStatus(x.health, now) === "stale");

  if (stale.length === 0) return null;
  return (
    <div className={styles.banner} role="status">
      <div className={styles.inner}>
        <span aria-hidden="true" className={styles.icon}>
          ⚠
        </span>
        <p>
          {stale.map(({ agency, health: h }) => (
            <span key={agency.id}>
              <strong>{agency.name} data is stale.</strong> Last successful update{" "}
              {formatRelative(h?.last_success_at, now)}.{" "}
            </span>
          ))}
          Historical reliability is unaffected; live predictions still come straight from the
          agency. <Link to="/health">Data health</Link>
        </p>
      </div>
    </div>
  );
}
