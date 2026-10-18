import { Link, useNavigate, useSearchParams } from "react-router";
import { Loading } from "../../components/States";
import { ApiError, errorMessage } from "../../lib/apiClient";
import { usePageTitle } from "../../lib/hooks";
import {
  googleLoginUrl,
  safeNextPath,
  setSessionHint,
  useConfig,
  useDemoLogin,
  useSession,
} from "./session";
import styles from "./SignInPage.module.css";

/** Messages for /signin?error=<code> set by GET /auth/callback. Unknown codes are shown as-is. */
const ERROR_MESSAGES: Record<string, string> = {
  invalid_state:
    "Your sign-in attempt expired or was started in another tab. Please try again from this page.",
  access_denied: "Google sign-in was cancelled.",
  login_failed: "We couldn’t complete sign-in with Google. Please try again.",
  login_disabled: "Google sign-in isn’t available right now.",
};

function demoError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.slug === "demo-capacity")
      return "Too many demo accounts are active right now. Please try again later.";
    if (err.slug === "rate-limited" || err.status === 429) {
      return `Too many demo accounts were created from your network recently. ${errorMessage(err)}`;
    }
    if (err.status === 404) return "Demo accounts are turned off on this server.";
  }
  return errorMessage(err, "Couldn't create a demo account.");
}

export default function SignInPage() {
  usePageTitle("Sign in");
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const next = safeNextPath(params.get("next"), "/commutes");
  const errorCode = params.get("error");
  const { me, isLoading: sessionLoading } = useSession();
  const { config, isLoading: configLoading, error: configError } = useConfig();
  const demo = useDemoLogin();

  if (sessionLoading) return <Loading label="Checking your session…" />;
  if (demo.isSuccess) return <Loading label="Signing you in…" />;

  if (me) {
    return (
      <div className={styles.wrap}>
        <h1>You’re signed in</h1>
        <p>
          Signed in as <strong>{me.user.display_name ?? me.user.email ?? "demo user"}</strong>.
        </p>
        <p className="row">
          <Link className="btn btn-primary" to={next}>
            Continue
          </Link>
          <Link className="btn" to="/account">
            Account
          </Link>
        </p>
      </div>
    );
  }

  const { features } = config;
  return (
    <div className={styles.wrap}>
      <h1>Sign in</h1>
      <p className="muted">
        Save your commutes to see personal reliability summaries. Browsing stops and routes never
        needs an account.
      </p>

      {errorCode && (
        <p className="notice notice-error" role="alert">
          {ERROR_MESSAGES[errorCode] ?? `Sign-in failed (error: ${errorCode}). Please try again.`}
        </p>
      )}

      {configLoading && <Loading label="Loading sign-in options…" />}
      {configError && (
        <p className="notice notice-warning">
          Sign-in is temporarily unavailable. Please try again later.
        </p>
      )}

      {!configLoading && (
        <div className={`card ${styles.options}`}>
          {features.google_login && (
            <a
              className={`btn btn-primary ${styles.full}`}
              href={googleLoginUrl(next)}
              onClick={() => setSessionHint(true)}
            >
              <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
                <path
                  fill="currentColor"
                  d="M21.6 12.2c0-.7-.1-1.4-.2-2H12v3.8h5.4a4.6 4.6 0 0 1-2 3v2.5h3.2c1.9-1.7 3-4.3 3-7.3zM12 22c2.7 0 5-.9 6.6-2.4l-3.2-2.5c-.9.6-2 1-3.4 1-2.6 0-4.8-1.8-5.6-4.1H3.1v2.6A10 10 0 0 0 12 22zM6.4 14c-.2-.6-.3-1.3-.3-2s.1-1.4.3-2V7.4H3.1a10 10 0 0 0 0 9.2L6.4 14zM12 5.9c1.5 0 2.8.5 3.8 1.5l2.9-2.9A10 10 0 0 0 3.1 7.4L6.4 10c.8-2.4 3-4.1 5.6-4.1z"
                />
              </svg>
              Continue with Google
            </a>
          )}
          {features.demo && (
            <>
              {features.google_login && <p className={styles.or}>or</p>}
              <button
                type="button"
                className={`btn ${features.google_login ? "" : "btn-primary"} ${styles.full}`}
                disabled={demo.isPending}
                onClick={() =>
                  demo.mutate(undefined, {
                    onSuccess: () => void navigate(next, { replace: true }),
                  })
                }
              >
                {demo.isPending ? "Creating demo account…" : "Try a demo account"}
              </button>
              <p className="small muted">
                A temporary account that’s deleted after 24 hours. Limited to 3 commutes; push
                alerts and Ask aren’t available.
              </p>
            </>
          )}
          {demo.error && (
            <p className="notice notice-error" role="alert">
              {demoError(demo.error)}
            </p>
          )}
          {!features.google_login && !features.demo && !configError && (
            <p className="muted">Sign-in isn’t enabled on this server.</p>
          )}
        </div>
      )}
      <p className="small muted">
        We store only what’s needed to run your account. <Link to="/privacy">Privacy</Link>
      </p>
    </div>
  );
}
