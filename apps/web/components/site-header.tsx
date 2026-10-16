"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import styles from "./site-header.module.css";
import navStyles from "./nav-link.module.css";
import { ModelBadge } from "./model-badge";

const NAV_ITEMS = [
  { href: "/research", label: "Research" },
  { href: "/library", label: "Library" },
  { href: "/runs", label: "Runs" },
  { href: "/usage", label: "Usage" },
];

export function SiteHeader() {
  const pathname = usePathname();

  return (
    <header className={styles.header}>
      <div className={styles.brand}>
        <Link href="/research" className={styles.logo}>
          [ RESEARCH WORKSPACE ]
        </Link>
        <span className={styles.unit}>UNIT / D-01</span>
      </div>

      <nav className={styles.nav} aria-label="Main">
        {NAV_ITEMS.map((item) => {
          const isActive = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
          return (
            <Link
              key={item.href}
              href={item.href}
              className={navStyles.link}
              aria-current={isActive ? "page" : undefined}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className={styles.rightSection}>
        <ModelBadge />
        <div className={styles.status}>
          <span className={styles.statusDot} aria-hidden="true" />
          <samp>SYS.READY</samp>
        </div>
      </div>
    </header>
  );
}
