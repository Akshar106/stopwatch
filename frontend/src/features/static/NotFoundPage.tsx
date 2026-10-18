import { Link } from "react-router";
import { usePageTitle } from "../../lib/hooks";

export default function NotFoundPage() {
  usePageTitle("Page not found");
  return (
    <>
      <h1>Page not found</h1>
      <p>That page doesn’t exist. It may have moved.</p>
      <p>
        <Link to="/">Search for a stop</Link> or check <Link to="/health">data health</Link>.
      </p>
    </>
  );
}
