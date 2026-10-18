import { Link } from "react-router";
import { bucketLabels } from "../../lib/cells";
import { formatCount, formatDate, formatDelay, formatDuration } from "../../lib/format";
import { usePageTitle } from "../../lib/hooks";
import { useDefaultAgency, useValidation } from "../../lib/queries";
import type { AgencyManifest } from "../../lib/types";
import styles from "./StaticPage.module.css";

export default function MethodologyPage() {
  usePageTitle("Methodology");
  const { agency } = useDefaultAgency();
  const onTime = agency?.on_time_definition_s ?? [-60, 300];
  const minSamples = agency?.min_samples ?? 8;

  return (
    <article className={styles.prose}>
      <p className="eyebrow">About</p>
      <h1>How Stopwatch measures reliability</h1>
      <p className="notice">
        <strong>Independent, unofficial estimates.</strong> Stopwatch is not affiliated with any
        transit agency. These numbers are inferred from public real-time data and may differ from
        official performance reports.
      </p>

      <h2 id="inference">Where arrivals come from</h2>
      <p>
        Agencies publish real-time <em>predictions</em>, but a stop’s prediction disappears from the
        feed as soon as the vehicle has served it. Stopwatch saves the feed every minute and
        compares consecutive snapshots. When a stop drops out of a trip’s predictions, we record an
        arrival at the last predicted time — or at the moment a vehicle was reported stopped at that
        stop, which is more precise.
      </p>
      <p>
        Each inferred arrival carries a <strong>confidence</strong>: high when the last prediction
        was made within 90 seconds of arrival (or the vehicle was seen stopped), medium within 5
        minutes, and low otherwise — for example after a gap in collection. Gaps are never
        back-filled with guesses.
      </p>

      <h2 id="delay">Delay</h2>
      <p>
        <strong>Delay = estimated arrival − scheduled arrival</strong>, using the schedule that was
        valid on that service day. Times after midnight belong to the previous service day, and
        daylight-saving days are handled the way the GTFS standard specifies. Positive numbers are
        late; negative numbers are early.
      </p>

      <h2 id="on-time">On time</h2>
      <p>
        An arrival is <strong>on time</strong> when it is between {formatDelay(onTime[0])} and{" "}
        {formatDelay(onTime[1])} of schedule (a common US convention; configurable per agency and
        stated wherever on-time rates appear). “Early” means more than{" "}
        {formatDuration(Math.abs(onTime[0]))} ahead of schedule — at a stop, an early bus can be as
        bad as a late one. Canceled trips and skipped stops are counted separately and never as on
        time.
      </p>

      <h2 id="percentiles">Typical and worst-case delay</h2>
      <p>
        We report the <strong>median (p50)</strong> as the typical delay and the{" "}
        <strong>90th percentile (p90)</strong> as the worst case you should plan for: 9 out of 10
        arrivals were no later than that. We never report an average on its own, because averages
        hide the bad days that riders remember.
      </p>
      <p>
        Each hour also has a delay histogram with buckets of{" "}
        {(agency ? bucketLabels(agency.histogram_edges_s) : []).join(", ")} minutes.
      </p>

      <h2 id="min-samples">“Not enough data”</h2>
      <p>
        An hour needs at least <strong>{minSamples} observed arrivals</strong> in the data window
        before we show statistics for it; below that, a couple of unusual trips would dominate.
        Those cells are hatched and labelled “not enough data”.
      </p>

      <h2 id="ewt">Excess wait time</h2>
      <p>
        On frequent service (scheduled at least every 12 minutes) riders don’t consult a timetable,
        so what matters is how long they actually wait. The average wait for a rider arriving at
        random is Σh² / (2·Σh) over the gaps h between consecutive vehicles.{" "}
        <strong>Excess wait time</strong> is that average for the actual gaps minus the same figure
        for the scheduled gaps. Bunching — two buses together, then a long gap — shows up here even
        when each bus is “on time”.
      </p>

      <h2 id="coverage">Coverage and confidence</h2>
      <p>
        <strong>Coverage</strong> is the share of scheduled trips we actually observed on a service
        day. When it is below 80% we label the numbers <strong>low confidence</strong>. Daily
        coverage and collection gaps are public on the <Link to="/health">data health</Link> page.
      </p>

      <h2 id="commutes">Personal commute summaries</h2>
      <p>
        A saved commute covers several hourly cells (for example weekdays, 7:30–8:30 AM touches the
        7 AM and 8 AM hours). Your browser combines those cells: arrival counts and on-time rates
        are added up weighted by arrivals, and the typical and worst-case delay are{" "}
        <strong>approximated</strong> from the combined histogram, because percentiles can’t be
        averaged. The weekly trend shown with a commute is for the whole route, not just your stop.
      </p>

      {agency && <ValidationStats agency={agency} />}
    </article>
  );
}

function ValidationStats({ agency }: { agency: AgencyManifest }) {
  const validation = useValidation(agency);
  if (!agency.paths.validation) return null;
  const v = validation.data;
  return (
    <section aria-labelledby="validation-heading">
      <h2 id="validation-heading">How accurate are the inferred arrivals?</h2>
      {validation.isPending && <p className="muted">Loading the latest validation report…</p>}
      {validation.error && <p className="muted">The validation report couldn’t be loaded.</p>}
      {validation.isSuccess && !v && (
        <p className="muted">No validation report has been published yet.</p>
      )}
      {v && (
        <>
          <p>
            Each week we compare our inferred subway arrivals with {agency.name}’s official arrival
            records. For the week of {formatDate(v.week)}, across {formatCount(v.sample)} matched
            arrivals:
          </p>
          <dl className="stat-grid">
            <div className="stat">
              <dt>Median error</dt>
              <dd>{formatDuration(v.median_abs_error_s)}</dd>
            </div>
            <div className="stat">
              <dt>90th-percentile error</dt>
              <dd>{formatDuration(v.p90_abs_error_s)}</dd>
            </div>
          </dl>
          {Object.keys(v.by_route).length > 0 && (
            <div className="table-scroll">
              <table className="data-table">
                <caption className="visually-hidden">Validation error by route</caption>
                <thead>
                  <tr>
                    <th scope="col">Route</th>
                    <th scope="col">Arrivals compared</th>
                    <th scope="col">Median error</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(v.by_route).map(([route, r]) => (
                    <tr key={route}>
                      <th scope="row">{route}</th>
                      <td>{formatCount(r.n)}</td>
                      <td>{formatDuration(r.median_abs_error_s)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}
