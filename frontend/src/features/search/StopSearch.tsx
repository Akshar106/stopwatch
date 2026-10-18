import { useDeferredValue, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useNavigate } from "react-router";
import { RouteBadge, UnknownRouteBadge } from "../../components/RouteBadge";
import { searchStops, type Place, type SearchIndex } from "../../lib/search";
import type { RouteSummary } from "../../lib/types";
import styles from "./StopSearch.module.css";

export function RouteChips({
  ids,
  routesById,
  max = 6,
}: {
  ids: string[];
  routesById: Map<string, RouteSummary>;
  max?: number;
}) {
  const sorted = [...ids].sort(
    (a, b) => (routesById.get(a)?.sort_order ?? 1e9) - (routesById.get(b)?.sort_order ?? 1e9),
  );
  const shown = sorted.slice(0, max);
  return (
    <span className={styles.chips}>
      {shown.map((id) => {
        const route = routesById.get(id);
        return route ? (
          <RouteBadge key={id} route={route} size="sm" />
        ) : (
          <UnknownRouteBadge key={id} id={id} />
        );
      })}
      {sorted.length > max && <span className="small muted">+{sorted.length - max}</span>}
    </span>
  );
}

/**
 * Stop search combobox (WAI-ARIA 1.2 combobox + listbox). Search runs locally over the
 * published stop index; nothing typed here leaves the browser.
 */
export function StopSearch({
  agencyId,
  index,
  routesById,
  loading = false,
  label = "Find a stop",
  onSelect,
}: {
  agencyId: string;
  index: SearchIndex | null;
  routesById: Map<string, RouteSummary>;
  loading?: boolean;
  label?: string;
  onSelect?: (place: Place) => void;
}) {
  const id = useId();
  const listId = `${id}-list`;
  const hintId = `${id}-hint`;
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const deferred = useDeferredValue(query);

  const trimmed = deferred.trim();
  const searchable = trimmed.length >= 2 || /^\d+$/.test(trimmed);
  const results = useMemo(
    () => (index && searchable ? searchStops(index, trimmed, 8) : []),
    [index, trimmed, searchable],
  );
  const expanded = open && searchable && !!index;

  const choose = (place: Place) => {
    setOpen(false);
    setActive(-1);
    if (onSelect) {
      setQuery(place.name);
      onSelect(place);
    } else {
      void navigate(`/s/${encodeURIComponent(agencyId)}/${encodeURIComponent(place.id)}`);
    }
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      if (results.length) setActive((a) => (a + 1) % results.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (results.length) setActive((a) => (a <= 0 ? results.length - 1 : a - 1));
    } else if (e.key === "Enter") {
      const pick = results[active] ?? (results.length === 1 ? results[0] : undefined);
      if (expanded && pick) {
        e.preventDefault();
        choose(pick.place);
      }
    } else if (e.key === "Escape") {
      if (expanded) {
        e.preventDefault();
        setOpen(false);
        setActive(-1);
      } else if (query) {
        e.preventDefault();
        setQuery("");
      }
    }
  };

  const statusText = !searchable
    ? ""
    : loading || !index
      ? "Loading the stop list…"
      : results.length === 0
        ? `No stops match “${trimmed}”.`
        : `${results.length} ${results.length === 1 ? "stop" : "stops"} found. Use up and down arrows to choose.`;

  return (
    <div className={styles.search}>
      <label htmlFor={`${id}-input`} className={styles.label}>
        {label}
      </label>
      <p id={hintId} className="small muted">
        Search by stop or station name, cross street, or the stop number on the sign.
      </p>
      <div className={styles.inputWrap}>
        <svg
          className={styles.icon}
          viewBox="0 0 24 24"
          width="20"
          height="20"
          aria-hidden="true"
          focusable="false"
        >
          <circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" strokeWidth="2" />
          <path d="M20 20l-4-4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
        <input
          ref={inputRef}
          id={`${id}-input`}
          type="search"
          role="combobox"
          aria-expanded={expanded}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-describedby={hintId}
          aria-activedescendant={expanded && active >= 0 ? `${id}-opt-${active}` : undefined}
          autoComplete="off"
          autoCorrect="off"
          spellCheck={false}
          placeholder="e.g. Harvard, Mass Ave @ Newbury"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
            setActive(-1);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={onKeyDown}
          className={styles.input}
        />
      </div>
      <ul
        id={listId}
        role="listbox"
        aria-label="Matching stops"
        className={styles.list}
        hidden={!expanded || results.length === 0}
      >
        {results.map((r, i) => (
          <li
            key={r.place.id}
            id={`${id}-opt-${i}`}
            role="option"
            aria-selected={i === active}
            className={`${styles.option} ${i === active ? styles.activeOption : ""}`}
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => choose(r.place)}
            onMouseEnter={() => setActive(i)}
          >
            <span className={styles.name}>{r.place.name}</span>
            <span className={styles.meta}>
              <RouteChips ids={r.place.routes} routesById={routesById} />
              <span className="small muted">
                {r.place.stopIds.length > 1 ? "Station" : `Stop ${r.place.id}`}
              </span>
            </span>
          </li>
        ))}
      </ul>
      <p className="visually-hidden" role="status" aria-live="polite">
        {open ? statusText : ""}
      </p>
      {expanded && results.length === 0 && !loading && (
        <p className={`small ${styles.noResults}`}>
          No stops match “{trimmed}”. Try a cross street or a station name.
        </p>
      )}
    </div>
  );
}
