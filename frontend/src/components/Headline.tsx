import type { BatchHeadline, PlantedRun } from "../api";

const REPO = "https://github.com/TOUMO45/rerun/blob/main/";

function pct(n: number, of: number): string {
  return of ? `${Math.round((100 * n) / of)}%` : "n/a";
}

function Figure({ big, label, sub }: { big: string; label: string; sub?: string }) {
  return (
    <div className="rounded-sm border border-border bg-surface px-4 py-3 shadow-card">
      <p className="font-display text-2xl font-semibold text-text-primary">{big}</p>
      <p className="mt-1 text-xs leading-snug text-text-primary">{label}</p>
      {sub && <p className="mt-1 font-mono text-[10px] leading-snug text-text-secondary">{sub}</p>}
    </div>
  );
}

function PlantedTable({ before, after }: { before: PlantedRun; after: PlantedRun | null }) {
  const fams = Object.entries(before.families);
  return (
    <table className="mt-2 w-full text-left font-mono text-[11px]" data-testid="planted-table">
      <thead className="text-text-secondary">
        <tr>
          <th className="py-1 pr-2 font-normal">family (held-out half)</th>
          <th className="py-1 pr-2 font-normal">n</th>
          <th className="py-1 pr-2 font-normal">caught before (by a semantic rule)</th>
          <th className="py-1 font-normal">caught after (by a semantic rule)</th>
        </tr>
      </thead>
      <tbody>
        {fams.map(([key, f]) => {
          const a = after?.families[key];
          return (
            <tr key={key} className="border-t border-border">
              <td className="py-1 pr-2 text-text-primary">{key} {f.name}</td>
              <td className="py-1 pr-2">{f.n}</td>
              <td className="py-1 pr-2">{f.rejected} ({f.by_semantic_rule})</td>
              <td className="py-1">{a ? `${a.rejected} (${a.by_semantic_rule})` : "not run yet"}</td>
            </tr>
          );
        })}
        <tr className="border-t border-border text-text-primary">
          <td className="py-1 pr-2">honest controls rejected (false rejects)</td>
          <td className="py-1 pr-2">{before.controls.n}</td>
          <td className="py-1 pr-2">{before.controls.rejected}</td>
          <td className="py-1">{after ? after.controls.rejected : "not run yet"}</td>
        </tr>
      </tbody>
    </table>
  );
}

/** harness-v1.9 (task 6): what the Batch Lab leads with — the run count, the diagnosis rate with its strict figure, the ungated counterfactual and the
 * planted-cheat benchmark. Every figure comes from a committed file through the API; a missing one is not shown (never a zero). */
export function Headline({ headline }: { headline: BatchHeadline }) {
  const { ran, diagnosis, counterfactual: cf, planted } = headline;
  return (
    <section aria-label="Headline" className="space-y-3" data-testid="headline">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {ran && (
          <Figure
            big={`${ran.count} of ${ran.of}`}
            label="held-out repositories ran their documented command"
            sub={ran.parts.map((p) => `${p.set} ${p.count}/${p.of}`).join(" · ") + " · ran ≠ reproduced"}
          />
        )}
        {diagnosis && (
          <Figure
            big={`${diagnosis.count} of ${diagnosis.of}`}
            label={`${diagnosis.set} non-running entries with an actionable diagnosis`}
            sub={`strict: ${diagnosis.strict.count} of ${diagnosis.strict.of} (${pct(diagnosis.strict.count, diagnosis.strict.of)})`}
          />
        )}
        {cf && (
          <Figure
            big={`≥${cf.fresh.ungated_at_least} vs ${cf.fresh.after_audits ?? cf.fresh.certified}`}
            label={`of ${cf.fresh.of}: an agent trusting exit 0 would report at least ${cf.fresh.ungated_at_least} reproduced; RERUN certified ${cf.fresh.after_audits ?? cf.fresh.certified} after the published audits (${cf.fresh.certified} as recorded; the two removed were not fakes)`}
            sub={`DEV: ≥${cf.dev.ungated_at_least} vs ${cf.dev.certified_after_erratum} of ${cf.dev.of} (${cf.dev.certified} as recorded; ${cf.dev.erratum})`}
          />
        )}
        {cf && (
          <Figure
            big={`${cf.fakes_refused_by_the_adjudicator} of ${cf.fakes_that_exited_0}`}
            label="recorded fakes that exited 0 were refused by the adjudicator; the gate passed all of them"
            sub={`gate rejections under a faking rule: ${cf.of_which_honest} of ${cf.gate_faking_rule_rejections} were honest patches`}
          />
        )}
      </div>
      {planted && (
        <div className="rounded-sm border border-border bg-surface px-4 py-3 shadow-card">
          <p className="text-xs text-text-primary">
            Planted-cheat benchmark, tamper gate only: {planted.before.cheats.rejected} of {planted.before.cheats.n} cheats caught before the v1.9 fixes
            {planted.after ? `, ${planted.after.cheats.rejected} of ${planted.after.cheats.n} after` : ""}; honest controls rejected{" "}
            {planted.before.controls.rejected} of {planted.before.controls.n} before{planted.after ? `, ${planted.after.controls.rejected} after` : ""}.
          </p>
          <PlantedTable before={planted.before} after={planted.after} />
          <p className="mt-2 font-mono text-[10px] text-text-secondary">
            {planted.note}{" "}
            <a className="text-signal hover:underline" href={`${REPO}${planted.source}`}>
              {planted.source}
            </a>
          </p>
        </div>
      )}
      {cf && (
        <p className="font-mono text-[10px] text-text-secondary">
          Counterfactual: committed records only, zero spend; &quot;at least&quot; because a gate-rejected patch was never executed.{" "}
          <a className="text-signal hover:underline" href={`${REPO}${cf.source}`}>
            {cf.source}
          </a>
        </p>
      )}
    </section>
  );
}
