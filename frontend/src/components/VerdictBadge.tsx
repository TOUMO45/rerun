import type { Verdict } from "../api";

const STYLES: Record<Verdict, { label: string; classes: string }> = {
  RUNS_CLEAN: { label: "RUNS CLEAN", classes: "bg-signal-dim/30 text-signal border-signal-dim" },
  RUNS_AFTER_REPAIR: { label: "RUNS AFTER REPAIR", classes: "bg-signal-dim/30 text-signal border-signal-dim" },
  BLOCKED: { label: "BLOCKED", classes: "bg-alarm-dim/30 text-alarm border-alarm-dim" },
  INDETERMINATE: { label: "INDETERMINATE", classes: "bg-warn/10 text-warn border-warn/40" },
  NOT_ATTEMPTABLE: { label: "NOT ATTEMPTABLE", classes: "bg-warn/10 text-warn border-warn/40" },
  TIMEOUT: { label: "TIMEOUT", classes: "bg-warn/10 text-warn border-warn/40" },
};

export function VerdictBadge({ verdict, size = "md" }: { verdict: Verdict; size?: "sm" | "md" | "lg" }) {
  const style = STYLES[verdict];
  const sizeClasses = size === "lg" ? "text-sm px-4 py-2" : size === "sm" ? "text-[11px] px-2 py-0.5" : "text-xs px-3 py-1";
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-sm border font-mono font-medium tracking-wide ${sizeClasses} ${style.classes}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
      {style.label}
    </span>
  );
}
