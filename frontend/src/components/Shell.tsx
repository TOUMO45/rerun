import { Link, useLocation } from "react-router-dom";
import type { ReactNode } from "react";

/** The burnt-orange gradient panel (header everywhere; header + hero on the intake page). */
export function EmberFrame({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`ember-frame ${className}`}>{children}</div>;
}

/** RERUN mark: a loop arrow (re-run) around a dot (the executed entrypoint). */
export function RerunMark({ className = "h-7 w-7" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" fill="none" className={className} aria-hidden="true">
      <path
        d="M25.5 12.5A10 10 0 1 0 26 19"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
      <path d="M26.5 6.5v6.5H20" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="16" cy="16" r="3" fill="currentColor" />
    </svg>
  );
}

/** Top navigation, laid out like the reference: links left, centred wordmark, pill CTA right. */
export function TopNav() {
  const { pathname } = useLocation();
  return (
    <header className="relative z-10 grid grid-cols-[1fr_auto] items-center gap-3 px-4 py-4 sm:grid-cols-[1fr_auto_1fr] sm:px-6">
      <nav aria-label="Primary" className="order-2 flex items-center gap-1 text-[13px] font-medium sm:order-1">
        <Link
          to="/"
          aria-label="Home"
          className="glass mr-1 hidden h-9 w-9 items-center justify-center rounded-full text-white sm:flex"
        >
          <span className="h-2 w-2 rounded-full bg-white" />
        </Link>
        <NavLink to="/gallery" active={pathname === "/gallery"}>
          Gallery
        </NavLink>
        <NavLink to="/batch" active={pathname === "/batch"}>
          Batch Lab
        </NavLink>
      </nav>

      <Link to="/" className="order-1 flex items-center gap-2 text-white sm:order-2 sm:flex-col sm:gap-1">
        <RerunMark className="h-7 w-7" />
        <span className="flex flex-col leading-none sm:items-center">
          <span className="text-sm font-bold tracking-[0.32em]">RERUN</span>
          <span className="mt-1 hidden text-[9px] font-medium tracking-[0.28em] text-white/75 sm:block">
            EXECUTION AUDIT
          </span>
        </span>
      </Link>

      <div className="order-3 hidden justify-end sm:flex">
        <Link
          to="/"
          className={`rounded-full px-4 py-2 text-[13px] font-semibold transition ${
            pathname === "/" ? "bg-white text-ember-deep" : "bg-white/90 text-ember-deep hover:bg-white"
          }`}
        >
          New run
        </Link>
      </div>
    </header>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  // The intake page draws its own frame (nav + hero in one panel); every other page gets the compact header.
  const isHome = pathname === "/";
  return (
    <div className="min-h-screen bg-canvas">
      <div className="mx-auto max-w-6xl px-3 pt-3 sm:px-4 sm:pt-4">
        {!isHome && (
          <EmberFrame className="rounded-[22px]">
            <TopNav />
          </EmberFrame>
        )}
      </div>
      <main className={`mx-auto max-w-6xl px-3 pb-16 sm:px-4 ${isHome ? "" : "pt-8 sm:px-6"}`}>{children}</main>
      <footer className="mx-auto max-w-6xl px-4 pb-8 text-center text-xs text-text-secondary sm:px-6">
        Every RERUN verdict is backed by the run&apos;s own logs.
      </footer>
    </div>
  );
}

function NavLink({ to, active, children }: { to: string; active: boolean; children: ReactNode }) {
  return (
    <Link
      to={to}
      aria-current={active ? "page" : undefined}
      className={`rounded-full px-3 py-1.5 transition-colors ${
        active ? "bg-white/20 text-white" : "text-white/85 hover:bg-white/10 hover:text-white"
      }`}
    >
      {children}
    </Link>
  );
}
