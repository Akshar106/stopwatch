import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { ErrorState, Loading } from "../../components/States";
import { api, errorMessage } from "../../lib/apiClient";
import { formatDateTime } from "../../lib/format";
import { usePageTitle } from "../../lib/hooks";
import { useManifest } from "../../lib/queries";
import type { ExportResponse, MeResponse } from "../../lib/types";
import { RequireAuth } from "../auth/RequireAuth";
import { clearSession, useConfig, useLogout } from "../auth/session";
import { useCommutes } from "../commutes/api";
import { AlertSettings } from "./AlertSettings";
import { disablePush, enablePush, pushSupported, storedSubscriptionId } from "./push";
import styles from "./AccountPage.module.css";

export default function AccountPage() {
  usePageTitle("Account");
  const [deleted, setDeleted] = useState(false);
  if (deleted) {
    return (
      <div className={styles.page}>
        <h1>Your account has been deleted</h1>
        <p>
          Your profile, commutes, alerts and sessions were removed. A pseudonymous security record
          of the deletion is kept for up to a year, and backups age out within 30 days.
        </p>
        <Link to="/" className="btn btn-primary">
          Back to Stopwatch
        </Link>
      </div>
    );
  }
  return (
    <RequireAuth>{(me) => <Account me={me} onDeleted={() => setDeleted(true)} />}</RequireAuth>
  );
}

function download(filename: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function Account({ me, onDeleted }: { me: MeResponse; onDeleted: () => void }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const logout = useLogout(false);
  const logoutAll = useLogout(true);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const { user, features } = me;

  const exportData = useMutation({
    mutationFn: () => api.get<ExportResponse>("/me/export"),
    onSuccess: (data) =>
      download(`stopwatch-export-${new Date().toISOString().slice(0, 10)}.json`, data),
  });
  const deleteAccount = useMutation({
    mutationFn: () => api.delete("/me"),
    onSuccess: () => {
      setConfirmDelete(false);
      onDeleted();
      clearSession(qc);
    },
  });

  return (
    <div className={styles.page}>
      <h1>Account</h1>

      <section className="section" aria-labelledby="profile-heading">
        <h2 id="profile-heading">Profile</h2>
        <dl className={`card ${styles.profile}`}>
          <div>
            <dt>Name</dt>
            <dd>{user.display_name ?? "—"}</dd>
          </div>
          <div>
            <dt>Email</dt>
            <dd>{user.email ?? "—"}</dd>
          </div>
          <div>
            <dt>Account type</dt>
            <dd>
              {user.is_demo ? (
                <>
                  <span className="badge">Demo</span>{" "}
                  {user.demo_expires_at && (
                    <>deleted automatically {formatDateTime(user.demo_expires_at)}</>
                  )}
                </>
              ) : (
                "Google"
              )}
            </dd>
          </div>
          <div>
            <dt>Member since</dt>
            <dd>{formatDateTime(user.created_at)}</dd>
          </div>
        </dl>
      </section>

      {user.is_demo && (features.alerts || features.ask) && (
        <section className="section" aria-labelledby="demo-limits-heading">
          <h2 id="demo-limits-heading">Demo account limits</h2>
          <div className="notice">
            <p>
              Demo accounts are temporary and shared-nothing, so a few features are switched off:
            </p>
            <ul>
              {features.alerts && (
                <li>
                  <strong>Push alerts</strong> need a long-lived account to deliver notifications to
                  your device; a demo account is deleted after 24 hours.
                </li>
              )}
              {features.ask && (
                <li>
                  <strong>Ask Stopwatch</strong> uses a paid language model with a strict monthly
                  budget, reserved for signed-in riders.
                </li>
              )}
            </ul>
            <p>Sign in with Google to use them. Your demo commutes aren’t carried over.</p>
          </div>
        </section>
      )}

      {features.alerts && !user.is_demo && <PushAlerts />}

      <section className="section" aria-labelledby="data-heading">
        <h2 id="data-heading">Your data</h2>
        <div className="card stack">
          <div>
            <h3>Export</h3>
            <p className="muted">
              Download everything we store about you — profile, commutes, alert settings, sessions
              and security log — as a JSON file.
            </p>
            <button
              type="button"
              className="btn"
              onClick={() => exportData.mutate()}
              disabled={exportData.isPending}
            >
              {exportData.isPending ? "Preparing…" : "Export my data"}
            </button>
            {exportData.error && (
              <p className="notice notice-error small" role="alert">
                {errorMessage(exportData.error)}
              </p>
            )}
          </div>
          <div>
            <h3>Delete account</h3>
            <p className="muted">
              Permanently deletes your account, commutes and alerts right away.
            </p>
            <button type="button" className="btn btn-danger" onClick={() => setConfirmDelete(true)}>
              Delete my account
            </button>
          </div>
        </div>
      </section>

      <section className="section" aria-labelledby="sessions-heading">
        <h2 id="sessions-heading">Sessions</h2>
        <div className="row">
          <button
            type="button"
            className="btn"
            disabled={logout.isPending}
            onClick={() => logout.mutate(undefined, { onSettled: () => void navigate("/") })}
          >
            Sign out
          </button>
          <button
            type="button"
            className="btn"
            disabled={logoutAll.isPending}
            onClick={() => logoutAll.mutate(undefined, { onSettled: () => void navigate("/") })}
          >
            Sign out everywhere
          </button>
        </div>
        <p className="small muted">“Sign out everywhere” ends your sessions on every device.</p>
      </section>

      <ConfirmDialog
        open={confirmDelete}
        title="Delete your account?"
        confirmLabel="Delete account"
        destructive
        busy={deleteAccount.isPending}
        onCancel={() => {
          setConfirmDelete(false);
          deleteAccount.reset();
        }}
        onConfirm={() => deleteAccount.mutate()}
      >
        <p>
          Your profile, saved commutes, alerts and sessions will be deleted immediately. This can’t
          be undone.
        </p>
        {deleteAccount.error && (
          <p className="notice notice-error">{errorMessage(deleteAccount.error)}</p>
        )}
      </ConfirmDialog>
    </div>
  );
}

function PushAlerts() {
  const { config, isLoading } = useConfig();
  const manifest = useManifest();
  const commutes = useCommutes(true);
  const supported = pushSupported();
  const [subscribed, setSubscribed] = useState(() => storedSubscriptionId() != null);
  const [status, setStatus] = useState<string | null>(null);
  const toggle = useMutation({
    mutationFn: async (on: boolean) => {
      if (on) {
        if (!config.vapid_public_key) throw new Error("Alerts aren't configured on this server.");
        await enablePush(config.vapid_public_key);
      } else {
        await disablePush();
      }
      return on;
    },
    onSuccess: (on) => {
      setSubscribed(on);
      setStatus(
        on ? "Alerts will be sent to this device." : "This device will no longer get alerts.",
      );
    },
  });

  return (
    <section className="section" aria-labelledby="alerts-heading">
      <h2 id="alerts-heading">Delay alerts</h2>
      <div className="card stack">
        <p className="muted">
          Get a notification when the next bus or train in one of your commute windows is predicted
          to be late by your threshold, or is canceled.
        </p>
        {!supported ? (
          <p className="notice">This browser doesn’t support push notifications.</p>
        ) : isLoading ? (
          <Loading label="Loading alert settings…" />
        ) : (
          <div>
            <p>
              This device:{" "}
              <strong>{subscribed ? "receiving alerts" : "not receiving alerts"}</strong>
            </p>
            <button
              type="button"
              className={`btn ${subscribed ? "" : "btn-primary"}`}
              disabled={toggle.isPending}
              onClick={() => toggle.mutate(!subscribed)}
            >
              {toggle.isPending
                ? "Working…"
                : subscribed
                  ? "Stop alerts on this device"
                  : "Enable alerts on this device"}
            </button>
            <p className="small" role="status">
              {status}
            </p>
            {toggle.error && (
              <p className="notice notice-error small" role="alert">
                {errorMessage(toggle.error)}
              </p>
            )}
          </div>
        )}
        <div>
          <h3>Per-commute alerts</h3>
          {commutes.isPending && <Loading label="Loading your commutes…" />}
          {commutes.error && (
            <ErrorState title="Couldn't load your commutes" error={commutes.error} />
          )}
          {commutes.data?.length === 0 && (
            <p className="muted">
              <Link to="/commutes">Save a commute</Link> to set up alerts for it.
            </p>
          )}
          <div className={styles.alerts}>
            {commutes.data?.map((c) => {
              const agency = manifest.data?.agencies.find((a) => a.id === c.agency_id);
              return agency ? <AlertSettings key={c.id} commute={c} agency={agency} /> : null;
            })}
          </div>
        </div>
      </div>
    </section>
  );
}
