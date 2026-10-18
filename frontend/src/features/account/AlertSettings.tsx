import { useId, useState, type FormEvent } from "react";
import { errorMessage } from "../../lib/apiClient";
import { formatDays, formatHHMM } from "../../lib/format";
import type { AgencyManifest, Commute } from "../../lib/types";
import { useCommuteNames, useDeleteAlert, useSetAlert } from "../commutes/api";
import styles from "./AccountPage.module.css";

/** Per-commute alert rule: notify when the next vehicle is N+ minutes late or canceled. */
export function AlertSettings({ commute, agency }: { commute: Commute; agency: AgencyManifest }) {
  const id = useId();
  const names = useCommuteNames(commute, agency);
  const [threshold, setThreshold] = useState(String(commute.alert?.threshold_min ?? 10));
  const [cancellations, setCancellations] = useState(commute.alert?.notify_cancellations ?? true);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const save = useSetAlert();
  const remove = useDeleteAlert();
  const value = Number(threshold);
  const valid = Number.isInteger(value) && value >= 3 && value <= 60;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    setStatus(null);
    if (!valid) {
      setError("Choose a whole number of minutes from 3 to 60.");
      return;
    }
    setError(null);
    save.mutate(
      { id: commute.id, input: { threshold_min: value, notify_cancellations: cancellations } },
      {
        onSuccess: () => setStatus("Alert saved."),
        onError: (err) => setError(errorMessage(err)),
      },
    );
  };

  return (
    <form className={styles.alert} onSubmit={onSubmit} aria-labelledby={`${id}-title`}>
      <h4 id={`${id}-title`} className={styles.alertTitle}>
        {commute.label || names.stopName}
      </h4>
      <p className="small muted">
        {names.routeLabel}
        {names.headsign && ` toward ${names.headsign}`} · {formatDays(commute.days)}{" "}
        {formatHHMM(commute.window_start)}–{formatHHMM(commute.window_end)}
      </p>
      <p className="small">
        Status:{" "}
        <strong>
          {commute.alert
            ? commute.alert.active
              ? "On"
              : "Saved, waiting for a device to receive alerts"
            : "Off"}
        </strong>
      </p>
      <div className={styles.alertFields}>
        <div className="field">
          <label htmlFor={`${id}-threshold`}>Alert when late by at least (minutes)</label>
          <input
            id={`${id}-threshold`}
            type="number"
            inputMode="numeric"
            min={3}
            max={60}
            step={1}
            value={threshold}
            aria-invalid={!valid || undefined}
            aria-describedby={error ? `${id}-error` : undefined}
            onChange={(e) => setThreshold(e.target.value)}
          />
        </div>
        <label className="check">
          <input
            type="checkbox"
            checked={cancellations}
            onChange={(e) => setCancellations(e.target.checked)}
          />
          Also alert on cancellations
        </label>
      </div>
      {error && (
        <p id={`${id}-error`} className="small error" role="alert">
          {error}
        </p>
      )}
      <p className="small" role="status">
        {status}
      </p>
      <div className="row">
        <button type="submit" className="btn btn-small btn-primary" disabled={save.isPending}>
          {save.isPending ? "Saving…" : commute.alert ? "Update alert" : "Turn on alert"}
        </button>
        {commute.alert && (
          <button
            type="button"
            className="btn btn-small"
            disabled={remove.isPending}
            onClick={() =>
              remove.mutate(commute.id, {
                onSuccess: () => setStatus("Alert turned off."),
                onError: (err) => setError(errorMessage(err)),
              })
            }
          >
            Turn off
          </button>
        )}
      </div>
    </form>
  );
}
