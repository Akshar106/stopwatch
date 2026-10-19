import type { ReactNode } from "react";
import styles from "./States.module.css";

/** Loading / error / empty states with the right live-region semantics. */

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className={styles.loading} role="status" aria-live="polite">
      <span className={styles.spinner} aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorState({
  title = "Something went wrong",
  error,
  onRetry,
  children,
}: {
  title?: string;
  error?: unknown;
  onRetry?: () => void;
  children?: ReactNode;
}) {
  const message = error instanceof Error ? error.message : typeof error === "string" ? error : null;
  return (
    <div className={`notice notice-error ${styles.block}`} role="alert">
      <p className={styles.title}>{title}</p>
      {message && <p>{message}</p>}
      {children}
      {onRetry && (
        <button type="button" className="btn btn-small" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className={`notice ${styles.block}`}>
      <p className={styles.title}>{title}</p>
      {children}
    </div>
  );
}

/**
 * Skeleton block for layout-stable loading (avoids CLS on data pages). Size it with `height`, or
 * with a `className` when the loaded content's height changes with the viewport.
 */
export function Skeleton({
  height,
  className,
  label,
}: {
  height?: string;
  className?: string;
  label: string;
}) {
  const size = height ?? (className ? undefined : "8rem");
  return (
    <div
      className={className ? `${styles.skeleton} ${className}` : styles.skeleton}
      style={size ? { height: size } : undefined}
      role="status"
      aria-live="polite"
    >
      <span className="visually-hidden">{label}</span>
    </div>
  );
}

/**
 * Skeleton for the rest of a page whose loaded content is always taller than the screen (stop,
 * route). Filling the viewport keeps the footer below the fold until the content arrives; a short
 * placeholder leaves the footer on screen and then shoves it off (a layout shift Lighthouse
 * counts), and makes the footer the page's largest paint.
 */
export function PageSkeleton({ label }: { label: string }) {
  return <Skeleton className={styles.page} label={label} />;
}
