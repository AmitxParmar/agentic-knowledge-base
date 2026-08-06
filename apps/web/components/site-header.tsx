/**
 * components/site-header.tsx
 * --------------------------
 * Purpose:    Top navigation header with app logo and route links.
 * Dependencies: next/link, nav-link.module.css
 * Scope:      Global shell.
 */

import Link from "next/link";
import styles from "./site-header.module.css";
import navStyles from "./nav-link.module.css";

const NAV_ITEMS = [
  { href: "/research", label: "Research" },
  { href: "/library", label: "Library" },
  { href: "/runs", label: "Runs" },
];

export function SiteHeader() {
  return (
    <header className={styles.header}>
      <Link href="/research" className={styles.logo}>
        Research Workspace
      </Link>
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
    </header>
  );
}
