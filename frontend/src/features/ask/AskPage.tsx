import { useMutation } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { Loading } from "../../components/States";
import { api, errorMessage, hasSlug } from "../../lib/apiClient";
import { usePageTitle } from "../../lib/hooks";
import type { AskResponse } from "../../lib/types";
import { useConfig, useSession } from "../auth/session";
import { GuidedForm } from "./GuidedForm";
import styles from "./AskPage.module.css";

const MAX = 300;

const REASONS: Record<string, string> = {
  disabled: "Ask Stopwatch is turned off right now.",
  cap_reached: "Ask Stopwatch has reached its budget for this month.",
  ungrounded:
    "We couldn’t back an answer with published numbers, so here’s the guided lookup instead.",
  refused: "That question is outside what Stopwatch can answer from transit reliability data.",
  error: "Something went wrong answering that question.",
};

/** Only same-site relative links from the API are rendered as links. */
function isInternal(href: string): boolean {
  return href.startsWith("/") && !href.startsWith("//");
}

export default function AskPage() {
  usePageTitle("Ask Stopwatch");
  const { me, isLoading } = useSession();
  const { config, isLoading: configLoading } = useConfig();
  const enabled = me ? me.features.ask : config.features.ask;

  if (isLoading || (!me && configLoading)) return <Loading label="Loading…" />;

  let unavailable: React.ReactNode = null;
  if (!enabled)
    unavailable = (
      <p>Ask Stopwatch isn’t enabled on this server. You can still look things up below.</p>
    );
  else if (!me)
    unavailable = (
      <p>
        <Link to="/signin?next=%2Fask">Sign in</Link> to ask questions in plain English. You can
        still look things up below.
      </p>
    );
  else if (me.user.is_demo)
    unavailable = (
      <p>
        Ask isn’t available for demo accounts: it uses a paid language model with a strict monthly
        budget reserved for signed-in riders. The guided lookup below uses the same published data.
      </p>
    );

  return (
    <div className={styles.page}>
      <h1>Ask Stopwatch</h1>
      <p className="muted">
        Questions are answered only from published reliability data, with the numbers shown so you
        can check them.
      </p>
      {unavailable ? (
        <>
          <div className="notice">{unavailable}</div>
          <h2 className={styles.guidedHeading}>Guided lookup</h2>
          <GuidedForm />
        </>
      ) : (
        <AskForm />
      )}
    </div>
  );
}

function AskForm() {
  const id = useId();
  const [question, setQuestion] = useState("");
  const [validation, setValidation] = useState<string | null>(null);
  const ask = useMutation({
    mutationFn: (q: string) => api.post<AskResponse>("/ask", { question: q }),
  });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const q = question.trim();
    if (q.length < 3) {
      setValidation("Type a question first.");
      return;
    }
    setValidation(null);
    ask.mutate(q);
  };

  const result = ask.data;
  const errorText = hasSlug(ask.error, "ask-quota")
    ? "You’ve used today’s questions. Try again tomorrow, or use the guided lookup."
    : hasSlug(ask.error, "ask-disabled")
      ? REASONS.disabled
      : ask.error
        ? errorMessage(ask.error)
        : null;

  return (
    <>
      <form onSubmit={onSubmit} className={`card ${styles.form}`}>
        <div className="field">
          <label htmlFor={`${id}-q`}>Your question</label>
          <textarea
            id={`${id}-q`}
            rows={3}
            maxLength={MAX}
            value={question}
            placeholder="Which is more reliable at 8 am on weekdays, the 1 or the CT1 at Mass Ave @ Vassar St?"
            aria-describedby={`${id}-count${validation ? ` ${id}-err` : ""}`}
            aria-invalid={validation ? true : undefined}
            onChange={(e) => setQuestion(e.target.value)}
          />
          <span id={`${id}-count`} className="hint">
            {question.length}/{MAX} characters
          </span>
          {validation && (
            <span id={`${id}-err`} className="error">
              {validation}
            </span>
          )}
        </div>
        <button type="submit" className="btn btn-primary" disabled={ask.isPending}>
          {ask.isPending ? "Thinking…" : "Ask"}
        </button>
      </form>

      <div aria-live="polite">
        {errorText && (
          <p className="notice notice-error" role="alert">
            {errorText}
          </p>
        )}
        {result && !result.fallback && result.answer && (
          <section className={`card ${styles.answer}`} aria-labelledby={`${id}-answer`}>
            <h2 id={`${id}-answer`}>Answer</h2>
            <p>{result.answer}</p>
            {result.facts.length > 0 && (
              <table className="data-table">
                <caption className={styles.caption}>Numbers behind this answer</caption>
                <thead>
                  <tr>
                    <th scope="col">Fact</th>
                    <th scope="col">Value</th>
                    <th scope="col">Source</th>
                  </tr>
                </thead>
                <tbody>
                  {result.facts.map((f, i) => (
                    <tr key={i}>
                      <th scope="row">{f.label}</th>
                      <td>{f.value}</td>
                      <td className="small muted">{f.source}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {result.links.length > 0 && (
              <ul className={styles.links}>
                {result.links.map((l) => (
                  <li key={l.href}>
                    {isInternal(l.href) ? <Link to={l.href}>{l.label}</Link> : l.label}
                  </li>
                ))}
              </ul>
            )}
            <p className="small muted">
              Generated from published data; numbers are checked against the source before display.
            </p>
          </section>
        )}
      </div>
      {(result?.fallback || ask.error) && (
        <section className={styles.fallback} aria-labelledby={`${id}-guided`}>
          {result?.fallback && (
            <p className="notice">{REASONS[result.reason ?? "error"] ?? REASONS.error}</p>
          )}
          <h2 id={`${id}-guided`} className={styles.guidedHeading}>
            Guided lookup
          </h2>
          <GuidedForm />
        </section>
      )}
    </>
  );
}
