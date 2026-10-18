import { useEffect, useRef } from "react";
import { Link, NavLink, Outlet, ScrollRestoration, useLocation, useNavigation } from "react-router";
import { useSession } from "../features/auth/session";
import { StaleBanner } from "../features/health/StaleBanner";
import styles from "./Layout.module.css";

function Logo() {
  return (
    <svg viewBox="0 0 32 32" width="28" height="28" aria-hidden="true" focusable="false">
      <circle cx="16" cy="18" r="11" fill="none" stroke="currentColor" strokeWidth="3" />
      <path d="M16 18 L16 11" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
      <path d="M12 3 h8" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
      <circle cx="16" cy="18" r="2" fill="currentColor" />
    </svg>
  );
}

/** Moves focus to the new page's <h1> after client-side navigation so screen readers announce it. */
function useRouteFocus() {
  const location = useLocation();
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    const target =
      document.querySelector<HTMLElement>("main h1") ?? document.getElementById("main");
    if (target) {
      if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
      target.focus({ preventScroll: true });
    }
  }, [location.pathname]);
}

export function Layout() {
  const { me } = useSession();
  const navigation = useNavigation();
  useRouteFocus();
  const navClass = ({ isActive }: { isActive: boolean }) =>
    isActive ? `${styles.navLink} ${styles.active}` : styles.navLink;

  return (
    <div className={styles.shell}>
      <a href="#main" className={styles.skip}>
        Skip to main content
      </a>
      {navigation.state === "loading" && <div className={styles.progress} aria-hidden="true" />}
      <header className={styles.header}>
        <div className={styles.headerInner}>
          <Link to="/" className={styles.brand}>
            <Logo />
            <span>Stopwatch</span>
          </Link>
          <nav aria-label="Main" className={styles.nav}>
            <ul>
              {me && (
                <li>
                  <NavLink to="/commutes" className={navClass}>
                    Commutes
                  </NavLink>
                </li>
              )}
              {me?.features.ask && (
                <li>
                  <NavLink to="/ask" className={navClass}>
                    Ask
                  </NavLink>
                </li>
              )}
              <li>
                <NavLink to="/health" className={navClass}>
                  Data health
                </NavLink>
              </li>
              <li>
                {me ? (
                  <NavLink to="/account" className={navClass}>
                    Account
                  </NavLink>
                ) : (
                  <NavLink to="/signin" className={navClass}>
                    Sign in
                  </NavLink>
                )}
              </li>
            </ul>
          </nav>
        </div>
      </header>
      <StaleBanner />
      <main id="main" tabIndex={-1} className={styles.main}>
        <Outlet />
      </main>
      <footer className={styles.footer}>
        <div className={styles.footerInner}>
          <p className={styles.disclaimer}>
            <strong>Independent, unofficial estimates.</strong> Stopwatch is not affiliated with or
            endorsed by any transit agency. Numbers are inferred from public real-time feeds.
          </p>
          <nav aria-label="Footer">
            <ul className={styles.footerLinks}>
              <li>
                <Link to="/about/methodology">Methodology</Link>
              </li>
              <li>
                <Link to="/privacy">Privacy</Link>
              </li>
              <li>
                <Link to="/health">Data health</Link>
              </li>
            </ul>
          </nav>
        </div>
      </footer>
      <ScrollRestoration />
    </div>
  );
}
