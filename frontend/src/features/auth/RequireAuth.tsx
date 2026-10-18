import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";
import { ErrorState, Loading } from "../../components/States";
import type { MeResponse } from "../../lib/types";
import { useSession } from "./session";

/** Gate for signed-in pages: redirects to /signin?next=… when there is no session. */
export function RequireAuth({ children }: { children: (me: MeResponse) => ReactNode }) {
  const { me, isLoading, error } = useSession();
  const location = useLocation();
  if (isLoading) return <Loading label="Checking your session…" />;
  if (error) return <ErrorState title="Couldn't check your session" error={error} />;
  if (!me) {
    const next = `${location.pathname}${location.search}`;
    return <Navigate to={`/signin?next=${encodeURIComponent(next)}`} replace />;
  }
  return <>{children(me)}</>;
}
