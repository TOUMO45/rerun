import type { RepairAttemptDiff, TavilySource } from "../api";
import { DiffView } from "./DiffView";

/** Defense in depth: `source.url` comes from a real Tavily search result,
 * not directly attacker-controlled, but nothing between that API response
 * and this render validates it's actually an http(s) link before it
 * becomes a clickable `href` — a `javascript:` (or other) URL scheme
 * would execute on click rather than navigate. Cheap and zero-cost to
 * guard regardless of how the URL got here. */
function isSafeHttpUrl(url: string): boolean {
  try {
    return ["http:", "https:"].includes(new URL(url).protocol);
  } catch {
    return false;
  }
}

function TavilySources({ sources }: { sources?: TavilySource[] }) {
  if (!sources || sources.length === 0) return null;
  return (
    <div className="mt-3 border-t border-border/60 pt-2">
      <p className="font-mono text-[11px] uppercase tracking-wide text-text-secondary">
        Cited sources (Tavily)
      </p>
      <ul className="mt-1 space-y-1">
        {sources.map((source, i) =>
          isSafeHttpUrl(source.url) ? (
            <li key={i} className="font-mono text-[11px]">
              <a
                href={source.url}
                target="_blank"
                rel="noreferrer"
                className="text-signal underline decoration-signal-dim underline-offset-2 hover:opacity-80"
              >
                [{i + 1}] {source.title || source.url}
              </a>
            </li>
          ) : (
            <li key={i} className="font-mono text-[11px] text-text-secondary">
              [{i + 1}] {source.title || "(source with an unrecognized URL scheme, not linked)"}
            </li>
          ),
        )}
      </ul>
    </div>
  );
}

/**
 * The tamper-gate REJECT state is the project's differentiator (see
 * RERUN_BUILD_DIRECTIVE.md §8 S2) — it must be visually loud, distinct,
 * and impossible to mistake for a routine log line. This is the one
 * deliberately animated moment in the whole UI (a single strobe pulse on
 * mount), everywhere else stays quiet by design.
 */
export function RepairAttemptCard({ attempt }: { attempt: RepairAttemptDiff }) {
  if (attempt.gate_decision === "DECLINED") {
    return (
      <div className="rounded-sm border border-border bg-surface px-4 py-3">
        <Header label={`Repair attempt ${attempt.attempt_number} — model declined`} tone="neutral" />
        <p className="mt-2 font-mono text-xs text-text-secondary">
          The repair model did not propose a fix it was confident about for this attempt.
        </p>
        <TavilySources sources={attempt.tavily_sources} />
      </div>
    );
  }

  if (attempt.gate_decision === "REJECT") {
    return (
      <div className="animate-alarm-strobe rounded-sm border-2 border-alarm bg-alarm-dim/15 px-4 py-3">
        <Header label={`Repair attempt ${attempt.attempt_number} — tamper gate REJECTED`} tone="alarm" />
        <ul className="mt-2 space-y-1">
          {attempt.gate_violations.map((v, i) => (
            <li key={i} className="font-mono text-xs text-alarm">
              <span className="font-semibold">{v.rule}</span> — {v.reason}
            </li>
          ))}
        </ul>
        <details className="mt-3">
          <summary className="cursor-pointer font-mono text-[11px] text-text-secondary">
            View the rejected diff (never applied)
          </summary>
          <div className="mt-2">
            <DiffView diff={attempt.diff_text} />
          </div>
        </details>
        <TavilySources sources={attempt.tavily_sources} />
      </div>
    );
  }

  // PASS
  return (
    <div className="rounded-sm border border-signal-dim bg-signal-dim/10 px-4 py-3">
      <Header label={`Repair attempt ${attempt.attempt_number} — tamper gate PASSED`} tone="signal" />
      {attempt.exit_code !== null && attempt.exit_code !== undefined && (
        <p className="mt-1 font-mono text-xs text-text-secondary">
          Re-execution exit code: <span className="text-text-primary">{attempt.exit_code}</span>
        </p>
      )}
      <details className="mt-3" open>
        <summary className="cursor-pointer font-mono text-[11px] text-text-secondary">Applied diff</summary>
        <div className="mt-2">
          <DiffView diff={attempt.diff_text} />
        </div>
      </details>
      <TavilySources sources={attempt.tavily_sources} />
    </div>
  );
}

function Header({ label, tone }: { label: string; tone: "alarm" | "signal" | "neutral" }) {
  const dot = tone === "alarm" ? "bg-alarm" : tone === "signal" ? "bg-signal" : "bg-text-secondary";
  const text = tone === "alarm" ? "text-alarm" : tone === "signal" ? "text-signal" : "text-text-secondary";
  return (
    <div className={`flex items-center gap-2 font-mono text-xs font-semibold uppercase tracking-wide ${text}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
      {label}
    </div>
  );
}
