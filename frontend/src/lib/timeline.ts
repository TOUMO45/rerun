import type { RepairAttemptDiff } from "../api";

export type TimelineItem =
  | { type: "log"; stage: string; message: string; key: string }
  | { type: "attempt"; attempt: RepairAttemptDiff; key: string };

const REPAIR_LINE = /^\[repair (\d+)\]/;
const GENERIC_LINE = /^\[(.+?)\]\s*(.*)$/;

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

    const genericMatch = line.match(GENERIC_LINE);
    if (genericMatch) {
      items.push({ type: "log", stage: genericMatch[1], message: genericMatch[2], key: `log-${index}` });
    } else {
      items.push({ type: "log", stage: "", message: line, key: `log-${index}` });
    }
  }

  return items;
}
