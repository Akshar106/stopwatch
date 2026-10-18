import type {
  Coverage,
  Health,
  Manifest,
  RouteDetail,
  RoutesList,
  StopsIndex,
  Validation,
} from "../../lib/types";
import coverage from "./mbta-coverage.json";
import health from "./mbta-health.json";
import route1 from "./mbta-route-1.json";
import routeRed from "./mbta-route-Red.json";
import routes from "./mbta-routes.json";
import stops from "./mbta-stops.json";
import validation from "./mbta-validation.json";
import manifest from "./manifest.json";

/** JSON imports are typed structurally; pin them to the contract types. */
const as = <T>(value: unknown): T => value as T;

/** Typed fixture access for unit tests (contracts §3 shapes). */
export const fixtures = {
  manifest: as<Manifest>(manifest),
  stops: as<StopsIndex>(stops),
  routes: as<RoutesList>(routes),
  route1: as<RouteDetail>(route1),
  routeRed: as<RouteDetail>(routeRed),
  coverage: as<Coverage>(coverage),
  health: as<Health>(health),
  validation: as<Validation>(validation),
};

export const agency = fixtures.manifest.agencies[0]!;
