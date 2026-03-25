import Link from "next/link";
import { ReactNode } from "react";

const navItems = [
  { href: "/", label: "Dashboard" },
  { href: "/companies", label: "Companies" },
  { href: "/news", label: "News" },
  { href: "/digests", label: "Digests" }
];

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-kicker">Life Sciences</span>
          <h1>Intel Grid</h1>
          <p>Filings, market context, and news ranked by what matters now.</p>
        </div>
        <nav className="nav">
          {navItems.map((item) => (
            <Link href={item.href} key={item.href} className="nav-link">
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="sidebar-footer">
          <p>Core SEC issuer universe</p>
          <p>Weekly digest every Monday at 8:00 AM ET</p>
        </div>
      </aside>
      <main className="main-content">{children}</main>
    </div>
  );
}

