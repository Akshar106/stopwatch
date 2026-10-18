import { isRouteErrorResponse, Link, useRouteError } from "react-router";

/** Last-resort error boundary for a route (render errors, failed lazy chunk loads). */
export function RouteError() {
  const error = useRouteError();
  const chunkFailed =
    error instanceof TypeError &&
    /dynamically imported module|Importing a module script failed/i.test(error.message);
  let message = "An unexpected error occurred while showing this page.";
  if (isRouteErrorResponse(error)) message = `${error.status} ${error.statusText}`;
  else if (chunkFailed)
    message = "A new version of Stopwatch was deployed. Reload the page to continue.";

  return (
    <div className="notice notice-error" role="alert">
      <h1>Something went wrong</h1>
      <p>{message}</p>
      <p className="row">
        <button type="button" className="btn" onClick={() => window.location.reload()}>
          Reload
        </button>
        <Link to="/" className="btn">
          Go home
        </Link>
      </p>
    </div>
  );
}
