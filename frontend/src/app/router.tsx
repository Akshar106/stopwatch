import type { RouteObject } from "react-router";
import HomePage from "../features/home/HomePage";
import NotFoundPage from "../features/static/NotFoundPage";
import { Layout } from "./Layout";
import { RouteError } from "./RouteError";

type PageModule = { default: React.ComponentType };
const page = (load: () => Promise<PageModule>) => async () => ({
  Component: (await load()).default,
});

/**
 * Home is bundled eagerly (it's the LCP page); everything else is a lazy chunk so the initial
 * JS stays small. Errors render inside the layout so navigation keeps working.
 */
export const routes: RouteObject[] = [
  {
    path: "/",
    Component: Layout,
    HydrateFallback: () => null,
    children: [
      {
        errorElement: <RouteError />,
        children: [
          { index: true, Component: HomePage },
          { path: "s/:agency/:stopId", lazy: page(() => import("../features/stop/StopPage")) },
          { path: "r/:agency/:routeId", lazy: page(() => import("../features/route/RoutePage")) },
          { path: "signin", lazy: page(() => import("../features/auth/SignInPage")) },
          { path: "commutes", lazy: page(() => import("../features/commutes/CommutesPage")) },
          { path: "account", lazy: page(() => import("../features/account/AccountPage")) },
          { path: "health", lazy: page(() => import("../features/health/HealthPage")) },
          { path: "ask", lazy: page(() => import("../features/ask/AskPage")) },
          {
            path: "about/methodology",
            lazy: page(() => import("../features/static/MethodologyPage")),
          },
          { path: "privacy", lazy: page(() => import("../features/static/PrivacyPage")) },
          { path: "*", Component: NotFoundPage },
        ],
      },
    ],
  },
];
