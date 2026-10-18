import { useId, useMemo, useState } from "react";
import { Link } from "react-router";
import { ErrorState, Loading } from "../../components/States";
import { formatCellKey, hasEnoughData } from "../../lib/cells";
import {
  DAY_TYPE_LABEL,
  formatCount,
  formatDelay,
  formatPct,
  hourRangeLabel,
  routeFullLabel,
  routeName,
} from "../../lib/format";
import { useDefaultAgency, useRouteDetail, useRoutesById, useSearchIndex } from "../../lib/queries";
import { serviceHourOrder } from "../../lib/schedule";
import type { Place } from "../../lib/search";
import { DAY_TYPES, type AgencyManifest, type DayType } from "../../lib/types";
import { StopSearch } from "../search/StopSearch";
import styles from "./AskPage.module.css";

/**
 * No-LLM fallback for Ask: stop → route → day type → hour, answered straight from the
 * published route file.
 */
export function GuidedForm() {
  const { agency, isLoading, error } = useDefaultAgency();
  if (isLoading) return <Loading label="Loading stops…" />;
  if (error || !agency) return <ErrorState title="Couldn't load transit data" error={error} />;
  return <Guided agency={agency} />;
}

function Guided({ agency }: { agency: AgencyManifest }) {
  const id = useId();
  const { index, query } = useSearchIndex(agency);
  const routesById = useRoutesById(agency);
  const [place, setPlace] = useState<Place | null>(null);
  const [routeId, setRouteId] = useState("");
  const [dirId, setDirId] = useState<number | null>(null);
  const [day, setDay] = useState<DayType>("wkd");
  const [hour, setHour] = useState<number | null>(null);
  const detail = useRouteDetail(agency, routeId || null);

  const options = useMemo(
    () =>
      (detail.data?.directions ?? []).flatMap((d) => {
        const stop = place ? d.stops.find((s) => place.stopIds.includes(s.stop_id)) : undefined;
        return stop ? [{ direction: d, stop }] : [];
      }),
    [detail.data, place],
  );
  const current = options.find((o) => o.direction.direction_id === dirId) ?? options[0];
  const hours = useMemo(
    () =>
      [...new Set(current?.stop.cells.filter((c) => c.day === day).map((c) => c.hour) ?? [])].sort(
        (a, b) => serviceHourOrder(a) - serviceHourOrder(b),
      ),
    [current, day],
  );
  const cell = current?.stop.cells.find((c) => c.day === day && c.hour === hour) ?? null;
  const minSamples = detail.data?.min_samples ?? agency.min_samples;

  return (
    <div className={`card ${styles.guided}`}>
      <StopSearch
        agencyId={agency.id}
        index={index}
        routesById={routesById}
        loading={query.isPending}
        label="1. Stop"
        onSelect={(p) => {
          setPlace(p);
          setRouteId(p.routes[0] ?? "");
          setDirId(null);
          setHour(null);
        }}
      />
      {place && (
        <div className={styles.guidedGrid}>
          <div className="field">
            <label htmlFor={`${id}-route`}>2. Route</label>
            <select
              id={`${id}-route`}
              value={routeId}
              onChange={(e) => {
                setRouteId(e.target.value);
                setDirId(null);
                setHour(null);
              }}
            >
              {place.routes.map((r) => {
                const route = routesById.get(r);
                return (
                  <option key={r} value={r}>
                    {route ? routeFullLabel(route) : r}
                  </option>
                );
              })}
            </select>
          </div>
          {options.length > 1 && (
            <div className="field">
              <label htmlFor={`${id}-dir`}>Direction</label>
              <select
                id={`${id}-dir`}
                value={current?.direction.direction_id ?? ""}
                onChange={(e) => setDirId(Number(e.target.value))}
              >
                {options.map((o) => (
                  <option key={o.direction.direction_id} value={o.direction.direction_id}>
                    Toward {o.direction.headsign ?? o.direction.direction_id}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="field">
            <label htmlFor={`${id}-day`}>3. Day</label>
            <select
              id={`${id}-day`}
              value={day}
              onChange={(e) => setDay(e.target.value as DayType)}
            >
              {DAY_TYPES.map((d) => (
                <option key={d} value={d}>
                  {DAY_TYPE_LABEL[d]}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor={`${id}-hour`}>4. Hour</label>
            <select
              id={`${id}-hour`}
              value={hour ?? ""}
              onChange={(e) => setHour(e.target.value === "" ? null : Number(e.target.value))}
              disabled={hours.length === 0}
            >
              <option value="">Choose an hour</option>
              {hours.map((h) => (
                <option key={h} value={h}>
                  {hourRangeLabel(h)}
                </option>
              ))}
            </select>
          </div>
        </div>
      )}
      {detail.isPending && routeId && <Loading label="Loading route data…" />}
      {detail.error && <ErrorState title="Couldn't load this route" error={detail.error} />}
      <div aria-live="polite">
        {place && current && cell && hour != null && (
          <div className="notice">
            {hasEnoughData(cell, minSamples) ? (
              <p>
                On <strong>{DAY_TYPE_LABEL[day].toLowerCase()}</strong> between{" "}
                <strong>{hourRangeLabel(hour)}</strong>,{" "}
                {routesById.get(routeId) ? routeName(routesById.get(routeId)!) : routeId}
                {current.direction.headsign && ` toward ${current.direction.headsign}`} at{" "}
                {current.stop.name} typically arrives <strong>{formatDelay(cell.p50_s)}</strong> vs
                schedule; 1 in 10 arrivals is <strong>{formatDelay(cell.p90_s)}</strong> or later.{" "}
                {formatPct(cell.on_time_pct)} were on time ({formatCount(cell.n)} arrivals).
              </p>
            ) : (
              <p>
                Not enough data for that hour yet ({formatCount(cell.n)} observed arrivals; we need{" "}
                {minSamples}).
              </p>
            )}
            <Link
              to={`/s/${encodeURIComponent(agency.id)}/${encodeURIComponent(current.stop.stop_id)}?route=${encodeURIComponent(routeId)}&dir=${current.direction.direction_id}&cell=${formatCellKey(cell)}`}
            >
              See the full hour-by-hour view
            </Link>
          </div>
        )}
        {place && detail.data && !current && (
          <p className="muted">That route’s published data doesn’t include this stop.</p>
        )}
      </div>
    </div>
  );
}
