/** harness-v1.9 (task 5): every scene and every certificate says on screen whether it is a REPLAY of a committed record (nothing executes) or a REAL run
 * made by this server. */
export function ModeBadge({ mode }: { mode: "REAL" | "REPLAY" }) {
  const cls =
    mode === "REPLAY"
      ? "border-warn/50 bg-warn/10 text-warn"
      : "border-signal/50 bg-signal/10 text-signal";
  return (
    <span
      data-testid="mode-badge"
      title={mode === "REPLAY" ? "Replayed from a committed record: nothing is executed" : "A run this server executed"}
      className={`inline-block rounded-sm border px-2 py-0.5 font-mono text-[11px] font-semibold tracking-wide ${cls}`}
    >
      {mode}
    </span>
  );
}
