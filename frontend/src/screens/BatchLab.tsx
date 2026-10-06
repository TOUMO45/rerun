import { useQuery } from "@tanstack/react-query";
import { api, ApiError, type PreregisteredSet, type Verdict } from "../api";
import { VerdictBadge } from "../components/VerdictBadge";

const REPO = "https://github.com/TOUMO45/rerun/blob/main/";
const VERDICTS: readonly string[] = [
  "RUNS_CLEAN", "RUNS_AFTER_REPAIR", "BLOCKED", "INDETERMINATE", "NOT_ATTEMPTABLE", "TIMEOUT", "INVALID_HARNESS", "INFRA_ERROR", "UPLOAD_TOO_LARGE",
];

/** The Batch Lab: RERUN's held-out results (never tuned on), each set as its own count. Read from the committed result files (GET /batch/preregistered). */
export function BatchLab() {
  const query = useQuery({ queryKey: ["batch-preregistered"], queryFn: api.getPreregistered, retry: false });

  if (query.isLoading) {
    return <p className="font-mono text-sm text-text-secondary">Loading Batch Lab…</p>;
  }

  if (query.isError || !query.data) {
    return (
      <div className="rounded-sm border-2 border-alarm bg-alarm-dim/15 px-6 py-8 text-center">
        <p className="font-mono text-sm font-semibold text-alarm">Batch Lab unavailable</p>
        <p className="mt-2 font-mono text-xs text-text-secondary">
          {query.error instanceof ApiError ? query.error.message : "The pre-registered results could not be loaded."}
        </p>
        <p className="mt-3 font-mono text-[11px] text-text-secondary">
          This is shown loudly on purpose — a missing result set is never rendered as a silent 0%.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div>
        <p className="font-mono text-xs uppercase tracking-wide text-text-secondary">Batch Lab</p>
        <h1 className="mt-1 font-display text-2xl font-semibold tracking-tight text-text-primary sm:text-3xl">Held-out results</h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-secondary">
          Each set below was chosen by a rule written down before it was picked, run once, and never used to tune RERUN. They are shown as
          they came out, each on its own: different sets, different harness versions, never added together. {query.data.note}
        </p>
      </div>
      {query.data.sets.map((set) => (
        <SetCard key={set.key} set={set} />
      ))}
    </div>
  );
}

function SetCard({ set }: { set: PreregisteredSet }) {
  return (
    <section aria-labelledby={`set-${set.key}`} className="rounded-sm border border-border bg-surface shadow-card">
      <div className="flex flex-col gap-4 border-b border-border px-5 py-5 sm:flex-row sm:items-start sm:justify-between">
        <div className="max-w-xl">
          <div className="flex flex-wrap items-center gap-2">
            <h2 id={`set-${set.key}`} className="font-display text-lg font-semibold text-text-primary">
              {set.title}
            </h2>
            <span className="rounded-full bg-surface-raised px-2.5 py-0.5 font-mono text-[11px] text-text-secondary">{set.harness}</span>
          </div>
          <p className="mt-1.5 text-sm leading-relaxed text-text-secondary">{set.what}</p>
          <a href={REPO + set.source} target="_blank" rel="noreferrer" className="mt-2 inline-block font-mono text-[11px] text-ember-deep hover:underline">
            {set.source}
          </a>
        </div>
        <div className="shrink-0 sm:text-right">
          <p className="font-display text-4xl font-bold tracking-tight text-text-primary">
            {set.count} <span className="text-2xl font-semibold text-text-secondary">of {set.of}</span>
          </p>
          <p className="mt-0.5 text-xs text-text-secondary">{set.measure}</p>
          {set.preregistered_count !== undefined && (
            <p className="mt-1 text-xs text-warn">
              {set.preregistered_count} of {set.of} {set.preregistered_measure}
            </p>
          )}
          <p className="mt-1 font-mono text-[11px] text-text-secondary">
            ${set.spend_usd.toFixed(2)} <span className="text-text-secondary/70">[{set.spend_tag}]</span>
          </p>
        </div>
      </div>
      <ul className="divide-y divide-border">
        {set.rows.map((row) => (
          <li key={row.entry} className="grid gap-2 px-5 py-3 sm:grid-cols-[2.5rem_minmax(0,14rem)_minmax(0,1fr)_4.5rem] sm:items-start sm:gap-4">
            <span className="font-mono text-xs text-text-secondary">#{String(row.entry).padStart(2, "0")}</span>
            <div className="min-w-0">
              <p className="break-all font-mono text-xs text-text-primary">{row.name}</p>
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                {row.verdict && VERDICTS.includes(row.verdict) ? (
                  <VerdictBadge verdict={row.verdict as Verdict} size="sm" />
                ) : (
                  <span className="font-mono text-[11px] text-text-secondary">{row.verdict ?? "—"}</span>
                )}
                {row.code && <span className="font-mono text-[11px] text-text-secondary">{row.code}</span>}
              </div>
            </div>
            <p className="text-xs leading-relaxed text-text-secondary [overflow-wrap:anywhere]">
              {row.note}
              {row.note_source && row.note_source !== set.source && (
                <>
                  {" "}
                  <a href={REPO + row.note_source} target="_blank" rel="noreferrer" className="text-ember-deep hover:underline">
                    (audit)
                  </a>
                </>
              )}
            </p>
            <span
              className={`justify-self-start rounded-full px-2.5 py-0.5 text-[11px] font-semibold sm:justify-self-end ${
                row.counts ? "bg-signal-dim/30 text-signal" : "bg-surface-raised text-text-secondary"
              }`}
            >
              {row.counts ? "ran" : "did not"}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
