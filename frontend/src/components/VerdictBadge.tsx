import type { Verdict } from "../api";

const STYLES: Record<Verdict, { label: string; classes: string }> = {
  RUNS_CLEAN: { label: "RUNS CLEAN", classes: "bg-signal-dim/30 text-signal border-signal-dim" },
  RUNS_AFTER_REPAIR: { label: "RUNS AFTER REPAIR", classes: "bg-signal-dim/30 text-signal border-signal-dim" },
  BLOCKED: { label: "BLOCKED", classes: "bg-alarm-dim/30 text-alarm border-alarm-dim" },
  INDETERMINATE: { label: "INDETERMINATE", classes: "bg-warn/10 text-warn border-warn/40" },
  NOT_ATTEMPTABLE: { label: "NOT ATTEMPTABLE", classes: "bg-warn/10 text-warn border-warn/40" },
  TIMEOUT: { label: "TIMEOUT", classes: "bg-warn/10 text-warn border-warn/40" },
  INVALID_HARNESS: { label: "INVALID (HARNESS)", classes: "bg-surface text-text-secondary border-border" },
  INFRA_ERROR: { label: "INFRA ERROR", classes: "bg-surface text-text-secondary border-border" },
  UPLOAD_TOO_LARGE: { label: "TOO LARGE (HARNESS)", classes: "bg-surface text-text-secondary border-border" },
};

/** harness-v1.7 (R6, D-44): a RUNS_AFTER_REPAIR whose passing code carries a model patch that changes what the code computes. */
const SEMANTIC_CHANGE = { label: "RUNS AFTER REPAIR (SEMANTIC CHANGE)", classes: "bg-warn/10 text-warn border-warn/40" };

/** harness-v1.7: the labels inside a server-side `verdict_label` ("RUNS_AFTER_REPAIR (semantic change; RESOURCE-ADAPTED: ...)"), as short badge tags. */
export function notesOfLabel(label?: string | null): string[] {
  const inner = label?.match(/\((.*)\)\s*$/)?.[1];
  if (!inner) return [];
  return inner.split("; ").map((note) =>
    note.startsWith("RESOURCE-ADAPTED")
      ? "RESOURCE-ADAPTED"
      : note.startsWith("memory hook")
        ? "MEMORY HOOK"
        : note.startsWith("dependency change")
          ? "DEPENDENCY CHANGE"
          : note.toUpperCase(),
  );
}

export function VerdictBadge({
  verdict,
  size = "md",
  semanticChange = false,
  resourceAdapted = false,
  notes: extra = [],
}: {
  verdict: Verdict;
  size?: "sm" | "md" | "lg";
  semanticChange?: boolean;
  /** harness-v1.7 (R1 d): the documented command ran with a smaller batch after a memory kill. */
  resourceAdapted?: boolean;
  /** harness-v1.7: further labels (MEMORY HOOK, DEPENDENCY CHANGE, ...), e.g. from notesOfLabel(verdict_label). */
  notes?: string[];
}) {
  const runs = verdict === "RUNS_AFTER_REPAIR" || verdict === "RUNS_CLEAN";
  const notes = [...new Set([semanticChange && runs ? "SEMANTIC CHANGE" : "", resourceAdapted && runs ? "RESOURCE-ADAPTED" : "", ...extra])].filter(Boolean);
  const style = notes.length
    ? { label: `${STYLES[verdict].label} (${notes.join("; ")})`, classes: SEMANTIC_CHANGE.classes }
    : STYLES[verdict];
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
