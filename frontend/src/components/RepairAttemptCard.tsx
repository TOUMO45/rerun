import type { RepairAttemptDiff } from "../api";
import { DiffView } from "./DiffView";

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
