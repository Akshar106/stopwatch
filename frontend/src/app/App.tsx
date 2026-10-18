import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { createBrowserRouter } from "react-router";
// The DOM RouterProvider wires react-dom's flushSync for `flushSync: true` navigations.
import { RouterProvider } from "react-router/dom";
import { onUnauthorized } from "../lib/apiClient";
import { clearSession } from "../features/auth/session";
import { createQueryClient } from "./queryClient";
import { routes } from "./router";

/** A 401 from any API call means the session ended (expired, revoked, deleted elsewhere). */
function SessionExpiryListener({ client }: { client: QueryClient }) {
  useEffect(() => onUnauthorized(() => clearSession(client)), [client]);
  return null;
}

export function App() {
  const [client] = useState(createQueryClient);
  const [router] = useState(() => createBrowserRouter(routes));
  return (
    <QueryClientProvider client={client}>
      <SessionExpiryListener client={client} />
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
