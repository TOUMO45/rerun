import type { RepairAttemptDiff } from "../api";

export type TimelineItem =
  | { type: "log"; stage: string; message: string; key: string }
  | { type: "attempt"; attempt: RepairAttemptDiff; key: string };

const REPAIR_LINE = /^\[repair (\d+)\]/;
const GENERIC_LINE = /^\[(.+?)\]\s*(.*)$/;

/** Splits one orchestrator log line into its `[stage]` tag and message, the
 * same parsing `buildTimelineItems` uses for the finished full_log — shared
 * so a live-streamed line and its replay after the run finishes render
 * identically. */
export function parseLogLine(line: string): { stage: string; message: string } {
  const match = line.match(GENERIC_LINE);
  return match ? { stage: match[1], message: match[2] } : { stage: "", message: line };
}

const WALL_CLOCK_LINE = /wall_clock_seconds=(\d+)/;
const SANDBOX_ID_LINE = /(?:\[sandbox\] id=|re-execution id=)(\S+)/;

/** §8 S2: "Live sandbox badge (id, elapsed time, wall-clock remaining)".
 * orchestrator.py logs the configured ceiling once, right before the
 * (blocking) sandbox call starts, specifically so this is knowable from
 * the very first live event rather than only after the whole step
 * finishes. Returns null until that line has streamed in. */
export function extractWallClockSeconds(lines: string[]): number | null {
  for (const line of lines) {
    const match = line.match(WALL_CLOCK_LINE);
    if (match) return Number(match[1]);
  }
  return null;
}

/** The real contree_sdk sandbox's own id, once a step has actually run —
 * takes the LATEST match, since a repair loop's re-execution runs in a
 * new sandbox with its own id. `"None"` (the Python string for an SDK
 * that never set one — see sandbox.py) is treated as "no id available",
 * not a literal identifier to display. */
export function extractLatestSandboxId(lines: string[]): string | null {
  let found: string | null = null;
  for (const line of lines) {
    const match = line.match(SANDBOX_ID_LINE);
    if (match && match[1] !== "None") found = match[1];
  }
  return found;
}

/**
 * Turns orchestrator.py's real, ordered full_log lines into renderable
 * timeline items. Every "[repair N] ..." line is collapsed into a single
 * structured attempt card (backed by the certificate's own `diffs` array,
 * not re-parsed text) the first time attempt N is seen, then suppressed —
 * so a REJECT-then-PASS attempt doesn't render as two disconnected lines
 * plus a duplicate card. Everything else renders as a plain stage line,
 * in the real order the pipeline actually ran in.
 */
export function buildTimelineItems(fullLog: string, diffs: RepairAttemptDiff[]): TimelineItem[] {
  const items: TimelineItem[] = [];
  const seenAttempts = new Set<number>();

  for (const [index, rawLine] of fullLog.split("\n").entries()) {
    const line = rawLine.trim();
    if (!line) continue;

    const repairMatch = line.match(REPAIR_LINE);
    if (repairMatch) {
      const attemptNumber = Number(repairMatch[1]);
      if (seenAttempts.has(attemptNumber)) continue;
      seenAttempts.add(attemptNumber);
      const attempt = diffs.find((d) => d.attempt_number === attemptNumber);
      if (attempt) {
        items.push({ type: "attempt", attempt, key: `attempt-${attemptNumber}` });
      }
      continue;
    }

    const { stage, message } = parseLogLine(line);
    items.push({ type: "log", stage, message, key: `log-${index}` });
  }

  return items;
}
