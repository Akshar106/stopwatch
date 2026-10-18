import { useRef, useState } from "react";
import { Link } from "react-router";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { EmptyState, ErrorState, Loading } from "../../components/States";
import { errorMessage } from "../../lib/apiClient";
import { usePageTitle } from "../../lib/hooks";
import { useDefaultAgency, useManifest } from "../../lib/queries";
import type { Commute, MeResponse } from "../../lib/types";
import { RequireAuth } from "../auth/RequireAuth";
import { commuteLimit, useCommutes, useDeleteCommute } from "./api";
import { CommuteCard } from "./CommuteCard";
import { CommuteForm } from "./CommuteForm";
import styles from "./Commutes.module.css";

export default function CommutesPage() {
  usePageTitle("Your commutes");
  return <RequireAuth>{(me) => <Commutes me={me} />}</RequireAuth>;
}

type Mode = { kind: "list" } | { kind: "create" } | { kind: "edit"; commute: Commute };

function Commutes({ me }: { me: MeResponse }) {
  const { agency, isLoading: agencyLoading, error: agencyError } = useDefaultAgency();
  const manifest = useManifest();
  const commutes = useCommutes(true);
  const remove = useDeleteCommute();
  const [mode, setMode] = useState<Mode>({ kind: "list" });
  const [toDelete, setToDelete] = useState<Commute | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const addButton = useRef<HTMLButtonElement>(null);
  const limit = commuteLimit(me);
  const count = commutes.data?.length ?? 0;
  const atLimit = count >= limit;

  const agencyFor = (c: Commute) =>
    manifest.data?.agencies.find((a) => a.id === c.agency_id) ?? null;

  const finish = (text: string) => {
    setMode({ kind: "list" });
    setMessage(text);
    requestAnimationFrame(() => addButton.current?.focus());
  };

  return (
    <>
      <div className="section-header">
        <h1>Your commutes</h1>
        <p className={`small muted ${styles.usage}`}>
          {count} of {limit} commutes used{me.user.is_demo && " (demo account)"}
        </p>
      </div>
      <p className="muted">
        Save the trips you take regularly to see how reliable they are in your time window.
        Summaries are computed in your browser from the public data.
      </p>

      <p
        role="status"
        aria-live="polite"
        className={message ? "notice notice-success" : "visually-hidden"}
      >
        {message}
      </p>

      {mode.kind === "list" && (
        <div className="row">
          <button
            ref={addButton}
            type="button"
            className="btn btn-primary"
            onClick={() => {
              setMessage(null);
              setMode({ kind: "create" });
            }}
            disabled={atLimit || !agency}
            aria-describedby={atLimit ? "limit-note" : undefined}
          >
            Add a commute
          </button>
          {atLimit && (
            <span id="limit-note" className="small muted">
              You’ve reached the limit of {limit}
              {me.user.is_demo ? " for demo accounts" : ""}. Delete one to add another.
            </span>
          )}
        </div>
      )}

      {agencyLoading && <Loading label="Loading transit data…" />}
      {agencyError && <ErrorState title="Couldn't load transit data" error={agencyError} />}

      {agency && mode.kind === "create" && (
        <CommuteForm
          agency={agency}
          onDone={() => finish("Commute saved.")}
          onCancel={() => setMode({ kind: "list" })}
        />
      )}
      {mode.kind === "edit" && agencyFor(mode.commute) && (
        <CommuteForm
          agency={agencyFor(mode.commute)!}
          commute={mode.commute}
          onDone={() => finish("Changes saved.")}
          onCancel={() => setMode({ kind: "list" })}
        />
      )}

      <section className="section" aria-label="Saved commutes">
        {commutes.isPending && <Loading label="Loading your commutes…" />}
        {commutes.error && (
          <ErrorState
            title="Couldn't load your commutes"
            error={commutes.error}
            onRetry={() => void commutes.refetch()}
          />
        )}
        {commutes.data?.length === 0 && mode.kind === "list" && (
          <EmptyState title="No commutes yet">
            <p>
              Add your usual stop and time, or <Link to="/">look up a stop</Link> first.
            </p>
          </EmptyState>
        )}
        {commutes.data && commutes.data.length > 0 && (
          <ul className={styles.list}>
            {commutes.data.map((c) => {
              const a = agencyFor(c);
              return (
                <li key={c.id}>
                  {a ? (
                    <CommuteCard
                      commute={c}
                      agency={a}
                      headingLevel={2}
                      actions={
                        <>
                          <button
                            type="button"
                            className="btn btn-small"
                            onClick={() => {
                              setMessage(null);
                              setMode({ kind: "edit", commute: c });
                            }}
                          >
                            Edit<span className="visually-hidden"> {c.label ?? "commute"}</span>
                          </button>
                          <button
                            type="button"
                            className="btn btn-small"
                            onClick={() => setToDelete(c)}
                          >
                            Delete<span className="visually-hidden"> {c.label ?? "commute"}</span>
                          </button>
                        </>
                      }
                    />
                  ) : (
                    <p className="notice">
                      A commute for an agency that is no longer published ({c.agency_id}).
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <ConfirmDialog
        open={!!toDelete}
        title="Delete this commute?"
        confirmLabel="Delete commute"
        destructive
        busy={remove.isPending}
        onCancel={() => {
          setToDelete(null);
          remove.reset();
        }}
        onConfirm={() => {
          if (!toDelete) return;
          remove.mutate(toDelete.id, {
            onSuccess: () => {
              setToDelete(null);
              finish("Commute deleted.");
            },
          });
        }}
      >
        <p>
          {toDelete?.label ? `“${toDelete.label}” ` : "This commute "}
          and any alert set on it will be removed. This can’t be undone.
        </p>
        {remove.error && <p className="notice notice-error">{errorMessage(remove.error)}</p>}
      </ConfirmDialog>
    </>
  );
}
