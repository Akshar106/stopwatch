import { routeColors } from "../lib/color";
import { routeShortLabel, routeTypeLabel } from "../lib/format";
import type { RouteInfo } from "../lib/types";
import styles from "./RouteBadge.module.css";

type BadgeRoute = Pick<
  RouteInfo,
  "id" | "short_name" | "long_name" | "type" | "color" | "text_color"
>;

/** Route chip in the agency's route color. The label is text, so color is decoration only. */
export function RouteBadge({
  route,
  size = "md",
}: {
  route: BadgeRoute;
  size?: "sm" | "md" | "lg";
}) {
  const { bg, fg } = routeColors(route);
  const label = routeShortLabel(route);
  return (
    <span
      className={`${styles.badge} ${styles[size]}`}
      style={{ background: bg, color: fg }}
      title={`${routeTypeLabel(route.type)} ${label}`}
    >
      {label}
    </span>
  );
}

/** Placeholder when a stop lists a route id that isn't in routes.json. */
export function UnknownRouteBadge({ id }: { id: string }) {
  return <span className={`${styles.badge} ${styles.sm} ${styles.unknown}`}>{id}</span>;
}
