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

/** Skeleton block for layout-stable loading (avoids CLS on data pages). */
export function Skeleton({ height = "8rem", label }: { height?: string; label: string }) {
  return (
    <div className={styles.skeleton} style={{ height }} role="status" aria-live="polite">
      <span className="visually-hidden">{label}</span>
    </div>
  );
}
