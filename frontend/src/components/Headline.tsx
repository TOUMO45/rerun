import type { BatchHeadline, BenchmarkTable } from "../api";

const REPO = "https://github.com/TOUMO45/rerun/blob/main/";

function Figure({ big, label, sub }: { big: string; label: string; sub?: string }) {
  return (
    <div className="rounded-sm border border-border bg-surface px-4 py-3 shadow-card">
      <p className="font-display text-2xl font-semibold text-text-primary">{big}</p>
      <p className="mt-1 text-xs leading-snug text-text-primary">{label}</p>
      {sub && <p className="mt-1 font-mono text-[10px] leading-snug text-text-secondary">{sub}</p>}
    </div>
  );
}

function layers(by: Record<string, number>): string {
  return Object.entries(by)
    .map(([k, v]) => `${k} ${v}`)
    .join(", ");
}

/** One per-layer table of the benchmark (benchmark/score.py --all, carried by figures.json). The flag column appears only for a table that has a flag. */
function TableView({ table }: { table: BenchmarkTable }) {
  const flagged = table.rows.some((r) => r.flagged > 0);
  return (
    <div className="mt-3" data-testid={`benchmark-${table.name}`}>
      <p className="text-xs font-medium text-text-primary">{table.title}</p>
      <table className="mt-1 w-full text-left font-mono text-[11px]">
        <thead className="text-text-secondary">
          <tr>
            <th className="py-1 pr-2 font-normal"> </th>
            <th className="py-1 pr-2 font-normal">n</th>
            <th className="py-1 pr-2 font-normal">refused</th>
            <th className="py-1 pr-2 font-normal">adopted{flagged ? " clean" : ""}</th>
            {flagged && <th className="py-1 pr-2 font-normal">adopted with REVIEW_REQUIRED</th>}
            <th className="py-1 font-normal">refused by layer</th>
          </tr>
        </thead>
        <tbody>
          {table.rows.map((r) => (
            <tr key={r.label} className="border-t border-border">
              <td className="py-1 pr-2 text-text-primary">{r.label}</td>
              <td className="py-1 pr-2">{r.n}</td>
              <td className="py-1 pr-2">{r.refused}</td>
              <td className="py-1 pr-2">{r.adopted}</td>
              {flagged && <td className="py-1 pr-2">{r.flagged}</td>}
              <td className="py-1">{layers(r.refused_by_layer)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {table.note && <p className="mt-1 text-[10px] leading-snug text-text-secondary">{table.note}</p>}
    </div>
  );
}

/** flag-mode pass (owner, 2026-10-09, task 4): what the Batch Lab leads with, in the owner's order: what ran (3 of 26), the diagnosis with its strict figure, the
 * benchmark and its per-layer tables, the limits. Every figure is read from reports/v1.9/figures.json through the API; a missing part is not shown (never a zero). */
export function Headline({ headline }: { headline: BatchHeadline }) {
  const { ran, diagnosis, benchmark, counterfactual: cf, limits } = headline;
  return (
    <section aria-label="Headline" className="space-y-3" data-testid="headline">
      <div className="grid gap-3 sm:grid-cols-2">
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
            sub={`strict: ${diagnosis.strict.count} of ${diagnosis.strict.of} (${diagnosis.strict.pct}%)`}
          />
        )}
      </div>
      {benchmark && (
        <div className="rounded-sm border border-border bg-surface px-4 py-3 shadow-card" data-testid="benchmark">
          <p className="text-xs text-text-primary">
            The cheat benchmark: {benchmark.sets.planted} planted patches and {benchmark.sets.independent} written by an independent author (
            {benchmark.sets.independent_measured_cheats} of its cheats reached exit 0 and are measured, {benchmark.sets.independent_dropped} dropped). {benchmark.status}.
            Reproduce every table with <code className="font-mono">{benchmark.command}</code>.
          </p>
          {benchmark.tables.map((t) => (
            <TableView key={t.name} table={t} />
          ))}
          <p className="mt-2 font-mono text-[10px] text-text-secondary">
            <a className="text-signal hover:underline" href={`${REPO}${benchmark.source}`}>
              {benchmark.source}
            </a>
          </p>
        </div>
      )}
      {cf && (
        <p className="text-xs leading-relaxed text-text-primary" data-testid="counterfactual">
          On real runs (committed records only, zero spend): an agent trusting exit 0 would report at least {cf.fresh.ungated_at_least} of {cf.fresh.of} fresh entry-runs as
          reproduced; RERUN certified {cf.fresh.after_audits ?? cf.fresh.certified} after the published audits ({cf.fresh.certified} as recorded). The{" "}
          {cf.removed_by_audit} runs the audits removed were not fakes ({cf.removed_that_were_fakes} were). DEV: ≥{cf.dev.ungated_at_least} vs{" "}
          {cf.dev.certified_after_erratum} of {cf.dev.of} ({cf.dev.certified} as recorded; {cf.dev.erratum}). The recorded fakes that exited 0: {cf.fakes_that_exited_0}; the
          gate passed {cf.fakes_passed_by_the_gate}, the adjudicator refused {cf.fakes_refused_by_the_adjudicator}; gate rejections under a faking rule: {cf.of_which_honest} of{" "}
          {cf.gate_faking_rule_rejections} were honest patches.{" "}
          <a className="text-signal hover:underline" href={`${REPO}${cf.source}`}>
            {cf.source}
          </a>
        </p>
      )}
      {limits.length > 0 && (
        <div data-testid="limits">
          <p className="text-xs font-medium text-text-primary">Limits</p>
          <ul className="mt-1 list-disc space-y-1 pl-4 text-[11px] leading-snug text-text-secondary">
            {limits.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        </div>
      )}
      <p className="font-mono text-[10px] text-text-secondary">every figure: {headline.source}</p>
    </section>
  );
}
