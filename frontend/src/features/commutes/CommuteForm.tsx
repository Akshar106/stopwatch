import { useId, useMemo, useRef, useState, type FormEvent } from "react";
import { ApiError, errorMessage } from "../../lib/apiClient";
import { formatHHMM, routeFullLabel, WEEKDAY_LABEL } from "../../lib/format";
import { useRouteDetail, useRoutesList } from "../../lib/queries";
import { isValidWindow } from "../../lib/schedule";
import {
  WEEKDAYS,
  type AgencyManifest,
  type Commute,
  type CommuteInput,
  type DirectionId,
  type Weekday,
} from "../../lib/types";
import { makeIdempotencyKey, useCreateCommute, useUpdateCommute } from "./api";
import styles from "./Commutes.module.css";

interface Values {
  route_id: string;
  direction_id: DirectionId | null;
  stop_id: string;
  days: Weekday[];
  window_start: string;
  window_end: string;
  label: string;
}

type Errors = Partial<Record<keyof Values | "form", string>>;

const WEEKDAYS_ONLY: Weekday[] = ["mon", "tue", "wed", "thu", "fri"];

function validateCommute(v: Values): Errors {
  const errors: Errors = {};
  if (!v.route_id) errors.route_id = "Choose a route.";
  if (v.direction_id == null) errors.direction_id = "Choose a direction.";
  if (!v.stop_id) errors.stop_id = "Choose a stop.";
  if (v.days.length === 0) errors.days = "Pick at least one day.";
  if (!v.window_start || !v.window_end) errors.window_end = "Enter a start and end time.";
  else if (!isValidWindow(v.window_start, v.window_end))
    errors.window_end = "The end time must be after the start time.";
  if (v.label.length > 60) errors.label = "Keep the name under 60 characters.";
  return errors;
}

/**
 * Create / edit a commute: route → direction → stop (from that route's published file),
 * days and a time window. A create retries with the same Idempotency-Key, so a double submit
 * or a flaky network can't create duplicates (US-8).
 */
export function CommuteForm({
  agency,
  commute,
  onDone,
  onCancel,
}: {
  agency: AgencyManifest;
  commute?: Commute;
  onDone: (saved: Commute) => void;
  onCancel: () => void;
}) {
  const id = useId();
  const editing = !!commute;
  const [values, setValues] = useState<Values>(() => ({
    route_id: commute?.route_id ?? "",
    direction_id: commute?.direction_id ?? null,
    stop_id: commute?.stop_id ?? "",
    days: commute?.days ?? WEEKDAYS_ONLY,
    window_start: commute?.window_start ?? "07:30",
    window_end: commute?.window_end ?? "08:30",
    label: commute?.label ?? "",
  }));
  const [errors, setErrors] = useState<Errors>({});
  const idempotencyKey = useRef(makeIdempotencyKey());
  const create = useCreateCommute();
  const update = useUpdateCommute();
  const saving = create.isPending || update.isPending;

  const routes = useRoutesList(agency);
  const sortedRoutes = useMemo(
    () =>
      [...(routes.data?.routes ?? [])].sort(
        (a, b) => (a.sort_order ?? 1e9) - (b.sort_order ?? 1e9),
      ),
    [routes.data],
  );
  const detail = useRouteDetail(agency, values.route_id || null);
  const direction = detail.data?.directions.find((d) => d.direction_id === values.direction_id);

  const set = <K extends keyof Values>(key: K, value: Values[K]) => {
    setValues((v) => ({ ...v, [key]: value }));
    setErrors((e) => ({ ...e, [key]: undefined, form: undefined }));
  };

  const toggleDay = (day: Weekday) =>
    set(
      "days",
      values.days.includes(day) ? values.days.filter((d) => d !== day) : [...values.days, day],
    );

  const fieldProps = (name: keyof Values) => ({
    id: `${id}-${name}`,
    "aria-invalid": errors[name] ? true : undefined,
    "aria-describedby": errors[name] ? `${id}-${name}-error` : undefined,
  });

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const found = validateCommute(values);
    if (Object.values(found).some(Boolean)) {
      setErrors(found);
      const first = (Object.keys(found) as (keyof Values)[]).find((k) => found[k]);
      document.getElementById(`${id}-${first}`)?.focus();
      return;
    }
    const input: CommuteInput = {
      agency_id: agency.id,
      route_id: values.route_id,
      direction_id: values.direction_id!,
      stop_id: values.stop_id,
      label: values.label.trim() || null,
      days: WEEKDAYS.filter((d) => values.days.includes(d)),
      window_start: values.window_start,
      window_end: values.window_end,
    };
    try {
      const saved = editing
        ? await update.mutateAsync({ id: commute.id, patch: input })
        : await create.mutateAsync({ input, idempotencyKey: idempotencyKey.current });
      idempotencyKey.current = makeIdempotencyKey();
      onDone(saved);
    } catch (err) {
      if (err instanceof ApiError && (err.slug === "commute-limit" || err.status === 409)) {
        setErrors({
          form:
            err.problem?.detail ?? "You've reached your commute limit. Delete one to add another.",
        });
      } else if (err instanceof ApiError && (err.slug === "validation" || err.status === 422)) {
        const fields = err.fieldErrors;
        const mapped: Errors = {
          form: err.problem?.detail ?? "Please fix the highlighted fields.",
        };
        for (const [field, message] of Object.entries(fields)) {
          const key = (field.split(".").pop() ?? field) as keyof Values;
          if (key in values) mapped[key] = message;
        }
        setErrors(mapped);
      } else {
        setErrors({ form: errorMessage(err, "Couldn't save the commute. Please try again.") });
      }
    }
  };

  const errorText = (name: keyof Values) =>
    errors[name] ? (
      <span id={`${id}-${name}-error`} className="error">
        {errors[name]}
      </span>
    ) : null;

  return (
    <form
      className={`card ${styles.form}`}
      onSubmit={(e) => void onSubmit(e)}
      noValidate
      aria-labelledby={`${id}-title`}
    >
      <h2 id={`${id}-title`}>{editing ? "Edit commute" : "Add a commute"}</h2>
      {errors.form && (
        <p className="notice notice-error" role="alert">
          {errors.form}
        </p>
      )}
      <div className={styles.formGrid}>
        <div className="field">
          <label htmlFor={`${id}-route_id`}>Route</label>
          <select
            {...fieldProps("route_id")}
            value={values.route_id}
            onChange={(e) => {
              setValues((v) => ({
                ...v,
                route_id: e.target.value,
                direction_id: null,
                stop_id: "",
              }));
              setErrors({});
            }}
            disabled={routes.isPending}
          >
            <option value="">{routes.isPending ? "Loading routes…" : "Choose a route"}</option>
            {sortedRoutes.map((r) => (
              <option key={r.id} value={r.id}>
                {routeFullLabel(r)}
              </option>
            ))}
          </select>
          {routes.error && <span className="error">Couldn't load routes.</span>}
          {errorText("route_id")}
        </div>

        <div className="field">
          <label htmlFor={`${id}-direction_id`}>Direction</label>
          <select
            {...fieldProps("direction_id")}
            value={values.direction_id ?? ""}
            onChange={(e) => {
              const dir = e.target.value === "" ? null : (Number(e.target.value) as DirectionId);
              setValues((v) => ({ ...v, direction_id: dir, stop_id: "" }));
              setErrors((er) => ({ ...er, direction_id: undefined }));
            }}
            disabled={!values.route_id || detail.isPending}
          >
            <option value="">
              {values.route_id && detail.isPending ? "Loading directions…" : "Choose a direction"}
            </option>
            {detail.data?.directions.map((d) => (
              <option key={d.direction_id} value={d.direction_id}>
                {d.headsign ? `Toward ${d.headsign}` : `Direction ${d.direction_id}`}
              </option>
            ))}
          </select>
          {detail.error && <span className="error">Couldn't load this route's stops.</span>}
          {errorText("direction_id")}
        </div>

        <div className="field">
          <label htmlFor={`${id}-stop_id`}>Stop</label>
          <select
            {...fieldProps("stop_id")}
            value={values.stop_id}
            onChange={(e) => set("stop_id", e.target.value)}
            disabled={!direction}
          >
            <option value="">Choose a stop</option>
            {direction?.stops.map((s) => (
              <option key={s.stop_id} value={s.stop_id}>
                {s.name}
              </option>
            ))}
          </select>
          {errorText("stop_id")}
        </div>
      </div>

      <fieldset aria-describedby={errors.days ? `${id}-days-error` : undefined}>
        <legend className="label">Days</legend>
        <div className={styles.days} id={`${id}-days`} tabIndex={-1}>
          {WEEKDAYS.map((day) => (
            <label key={day} className="check">
              <input
                type="checkbox"
                checked={values.days.includes(day)}
                onChange={() => toggleDay(day)}
              />
              {WEEKDAY_LABEL[day]}
            </label>
          ))}
        </div>
        <div className={styles.presets}>
          <button type="button" className="btn-link" onClick={() => set("days", WEEKDAYS_ONLY)}>
            Weekdays
          </button>
          <button type="button" className="btn-link" onClick={() => set("days", ["sat", "sun"])}>
            Weekends
          </button>
          <button type="button" className="btn-link" onClick={() => set("days", [...WEEKDAYS])}>
            Every day
          </button>
        </div>
        {errorText("days")}
      </fieldset>

      <div className={styles.formGrid}>
        <div className="field">
          <label htmlFor={`${id}-window_start`}>From</label>
          <input
            type="time"
            {...fieldProps("window_start")}
            value={values.window_start}
            step={300}
            onChange={(e) => set("window_start", e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor={`${id}-window_end`}>To</label>
          <input
            type="time"
            {...fieldProps("window_end")}
            value={values.window_end}
            step={300}
            onChange={(e) => set("window_end", e.target.value)}
          />
          <span className="hint">
            {agency.name} local time
            {isValidWindow(values.window_start, values.window_end) &&
              ` · ${formatHHMM(values.window_start)} to ${formatHHMM(values.window_end)}`}
          </span>
          {errorText("window_end")}
        </div>
        <div className="field">
          <label htmlFor={`${id}-label`}>Name (optional)</label>
          <input
            type="text"
            {...fieldProps("label")}
            value={values.label}
            maxLength={60}
            placeholder="e.g. Morning to work"
            onChange={(e) => set("label", e.target.value)}
          />
          {errorText("label")}
        </div>
      </div>

      <div className="row">
        <button type="submit" className="btn btn-primary" disabled={saving}>
          {saving ? "Saving…" : editing ? "Save changes" : "Save commute"}
        </button>
        <button type="button" className="btn" onClick={onCancel} disabled={saving}>
          Cancel
        </button>
      </div>
    </form>
  );
}
