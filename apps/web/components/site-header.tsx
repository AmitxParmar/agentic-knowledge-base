const NAV_ITEMS = [
  { href: "/research", label: "Research" },
  { href: "/library", label: "Library" },
  { href: "/runs", label: "Runs" },
];

import styles from "./site-header.module.css";
import navStyles from "./nav-link.module.css";
import Link from "next/link";

export function SiteHeader() {
  return (
    <header className={styles.header}>
      <div className={styles.brand}>
        <Link href="/research" className={styles.logo}>
          [ Research Workspace ]
        </Link>
        <span className={styles.unit}>UNIT / D-01</span>
      </div>

      <nav className={styles.nav} aria-label="Main">
        {NAV_ITEMS.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={navStyles.link}
            aria-current="page"
          >
            {item.label}
          </Link>
        ))}
      </nav>

      <div className={styles.status}>
        <span className={styles.statusDot} aria-hidden="true" />
        <samp>SYS.READY</samp>
      </div>
    </header>
  );
}
