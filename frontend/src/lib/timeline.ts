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
