import { Link } from "react-router";
import { usePageTitle } from "../../lib/hooks";
import styles from "./StaticPage.module.css";

export default function PrivacyPage() {
  usePageTitle("Privacy");
  return (
    <article className={styles.prose}>
      <p className="eyebrow">Privacy</p>
      <h1>Privacy, in plain language</h1>
      <p>
        You can use Stopwatch without an account, and nothing about your browsing is tracked. There
        are no analytics tools, ads or third-party trackers.
      </p>

      <h2>Your location stays on your device</h2>
      <p>
        “Near me” asks your browser for your location and works out the nearest stops right on your
        phone or computer, using the stop list it already downloaded. Your location is never sent to
        Stopwatch or anyone else.
      </p>

      <h2>Live arrivals</h2>
      <p>
        The “Right now” panel asks the MBTA’s public API directly from your browser for the stop
        you’re viewing. That request goes to the MBTA, not to us, and carries no cookies.
      </p>

      <h2>If you sign in</h2>
      <p>We store only what’s needed to run your account:</p>
      <table className="data-table">
        <thead>
          <tr>
            <th scope="col">What</th>
            <th scope="col">Why</th>
            <th scope="col">How long</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <th scope="row">Your name and email from Google</th>
            <td>To identify your account</td>
            <td>Until you delete your account</td>
          </tr>
          <tr>
            <th scope="row">Saved commutes and alert settings</th>
            <td>Personal summaries and alerts</td>
            <td>Until you delete them or your account</td>
          </tr>
          <tr>
            <th scope="row">Sessions (browser type, partial IP address)</th>
            <td>Keeping you signed in securely</td>
            <td>30 days at most</td>
          </tr>
          <tr>
            <th scope="row">Push notification address (if you turn on alerts)</th>
            <td>Delivering alerts to your device</td>
            <td>Until you turn alerts off</td>
          </tr>
          <tr>
            <th scope="row">Security log (account ID and partial IP, no email)</th>
            <td>Investigating abuse</td>
            <td>365 days</td>
          </tr>
        </tbody>
      </table>
      <p>
        Saved commutes reveal where and when you travel, so only you can see them. Your personal
        reliability summaries are calculated in your browser from public data; the server never
        analyses your trips. We don’t store passwords — sign-in is handled by Google — and the only
        cookie is the one that keeps you signed in, so there’s no cookie banner.
      </p>
      <p>
        Demo accounts are deleted automatically after 24 hours. Questions you type into Ask
        Stopwatch are not stored and are never sent with your identity.
      </p>

      <h2>Your rights</h2>
      <p>
        On your <Link to="/account">account page</Link> you can download everything we store about
        you as a file, or delete your account. Deletion is immediate; only a pseudonymous security
        record of the deletion remains, and backups age out within 30 days.
      </p>

      <h2>Unofficial estimates</h2>
      <p>
        Stopwatch is an independent project and is not affiliated with any transit agency. See the{" "}
        <Link to="/about/methodology">methodology</Link> for how the numbers are produced.
      </p>
    </article>
  );
}
