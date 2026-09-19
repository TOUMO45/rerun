import { Link, useLocation } from "react-router-dom";
import type { ReactNode } from "react";

export function Shell({ children }: { children: ReactNode }) {
  const location = useLocation();
  return (
    <div className="min-h-screen bg-bg">
      <header className="sticky top-0 z-10 border-b border-border bg-bg/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3 sm:px-6">
          <Link to="/" className="flex items-center gap-2">
            <span className="flex h-6 w-6 items-center justify-center rounded-sm border border-signal-dim text-signal">
              <span className="h-2 w-2 rounded-full bg-signal" />
            </span>
            <span className="font-mono text-sm font-semibold tracking-[0.15em] text-text-primary">RERUN</span>
          </Link>
          <nav className="flex items-center gap-1 font-mono text-xs">
            <NavLink to="/" active={location.pathname === "/"}>
              New run
            </NavLink>
            <NavLink to="/batch" active={location.pathname === "/batch"}>
              Batch Lab
            </NavLink>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6">{children}</main>
    </div>
  );
}

function NavLink({ to, active, children }: { to: string; active: boolean; children: ReactNode }) {
  return (
    <Link
      to={to}
      className={`rounded-sm px-3 py-1.5 transition-colors ${
        active ? "bg-surface-raised text-text-primary" : "text-text-secondary hover:text-text-primary"
      }`}
    >
      {children}
    </Link>
  );
}
