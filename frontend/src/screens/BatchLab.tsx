import { Fragment, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError, type BatchRepoResult } from "../api";
import { VerdictBadge } from "../components/VerdictBadge";

const HOURS_PER_REPAIR_ASSUMPTION = 3; // midpoint of the directive's 2-4 hr/repo range

export function BatchLab() {
  const query = useQuery({ queryKey: ["batch-results"], queryFn: api.getBatchResults, retry: false });

  if (query.isLoading) {
    return <p className="font-mono text-sm text-text-secondary">Loading Batch Lab…</p>;
  }

  if (query.isError || !query.data) {
    return (
      <div className="rounded-sm border-2 border-alarm bg-alarm-dim/15 px-6 py-8 text-center">
        <p className="font-mono text-sm font-semibold text-alarm">Batch Lab unavailable</p>
        <p className="mt-2 font-mono text-xs text-text-secondary">
          {query.error instanceof ApiError
            ? query.error.message
            : "batch_results.json could not be loaded."}
        </p>
        <p className="mt-3 font-mono text-[11px] text-text-secondary">
          This is shown loudly on purpose — a missing result set is never rendered as a
          silent 0%.
        </p>
      </div>
    );
  }

  const data = query.data;
  const runsClean = data.runs_clean ?? data.repos.filter((r) => r.verdict === "RUNS_CLEAN").length;
  const runsAfterRepair =
    data.runs_after_repair ?? data.repos.filter((r) => r.verdict === "RUNS_AFTER_REPAIR").length;
  const blocked = data.blocked ?? data.repos.filter((r) => r.verdict === "BLOCKED").length;
  const indeterminate = data.indeterminate ?? data.repos.filter((r) => r.verdict === "INDETERMINATE").length;
  const estimatedHours =
    data.estimated_researcher_hours_saved ?? runsAfterRepair * HOURS_PER_REPAIR_ASSUMPTION;

  const breakdown =
    data.failure_breakdown ??
    data.repos.reduce<Record<string, number>>((acc, r) => {
      if (r.taxonomy_code) acc[r.taxonomy_code] = (acc[r.taxonomy_code] ?? 0) + 1;
      return acc;
    }, {});
  const maxCount = Math.max(1, ...Object.values(breakdown));

  return (
    <div className="space-y-8">
      <div>
        <p className="font-mono text-xs uppercase tracking-wide text-text-secondary">Batch Lab</p>
        <div className="mt-2 flex flex-wrap items-end gap-4">
          <span className="font-display text-5xl font-bold tracking-tight text-signal">
            {(data.recovery_rate * 100).toFixed(0)}%
          </span>
          <span className="pb-1 font-mono text-sm text-text-secondary">
            Reproducibility Recovery Rate (N = {data.n_measured ?? data.n})
          </span>
        </div>
        {(data.excluded_our_fault ?? 0) > 0 && (
          <p className="mt-2 font-mono text-xs text-warn">
            {data.excluded_our_fault} of {data.n} run(s) excluded: RERUN's own errors, not verdicts on the repos
            {data.our_fault_breakdown
              ? ` (${Object.entries(data.our_fault_breakdown).map(([k, v]) => `${k} ×${v}`).join(", ")})`
              : ""}
            .
          </p>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Ran clean" value={runsClean} />
        <Stat label="Ran after repair" value={runsAfterRepair} />
        <Stat label="Blocked" value={blocked} tone="alarm" />
        <Stat label="Indeterminate" value={indeterminate} tone="warn" />
      </div>

      <div className="rounded-sm border border-border bg-surface px-5 py-4">
        <div className="flex items-baseline justify-between">
          <span className="font-mono text-2xl font-semibold text-text-primary">
            ≈{estimatedHours.toFixed(0)} hrs
          </span>
          <span className="rounded-sm bg-warn/15 px-2 py-0.5 font-mono text-[11px] font-semibold uppercase tracking-wide text-warn">
            Estimate — not measured
          </span>
        </div>
        <p className="mt-1 font-mono text-[11px] text-text-secondary">
          Researcher-hours saved ≈ (repos that only ran after repair) × {HOURS_PER_REPAIR_ASSUMPTION} hrs/repo
          assumed manual debug time.
        </p>
        {data.median_time_to_first_failure_seconds !== undefined && (
          <p className="mt-2 font-mono text-[11px] text-text-secondary">
            Median time-to-first-failure: {data.median_time_to_first_failure_seconds}s
          </p>
        )}
      </div>

      {Object.keys(breakdown).length > 0 && (
        <div className="rounded-sm border border-border bg-surface px-5 py-4">
          <h2 className="mb-3 font-mono text-xs uppercase tracking-wide text-text-secondary">
            Failure breakdown by taxonomy code
          </h2>
          <div className="space-y-2">
            {Object.entries(breakdown)
              .sort(([, a], [, b]) => b - a)
              .map(([code, count]) => (
                <div key={code} className="flex items-center gap-3">
                  <span className="w-40 shrink-0 truncate font-mono text-xs text-text-secondary">{code}</span>
                  <div className="h-3 flex-1 overflow-hidden rounded-sm bg-bg">
                    <div className="h-full bg-alarm-dim" style={{ width: `${(count / maxCount) * 100}%` }} />
                  </div>
                  <span className="w-6 shrink-0 text-right font-mono text-xs text-text-primary">{count}</span>
                </div>
              ))}
          </div>
        </div>
      )}

      <RepoTable repos={data.repos} />
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: "alarm" | "warn" }) {
  const color = tone === "alarm" ? "text-alarm" : tone === "warn" ? "text-warn" : "text-text-primary";
  return (
    <div className="rounded-sm border border-border bg-surface px-4 py-3">
      <p className={`font-mono text-2xl font-semibold ${color}`}>{value}</p>
      <p className="mt-1 font-mono text-[11px] text-text-secondary">{label}</p>
    </div>
  );
}

function RepoTable({ repos }: { repos: BatchRepoResult[] }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  return (
    <div className="overflow-hidden rounded-sm border border-border">
      <table className="w-full text-left font-mono text-xs">
        <thead className="bg-surface-raised text-text-secondary">
          <tr>
            <th className="px-3 py-2 font-medium">Repo</th>
            <th className="px-3 py-2 font-medium">Verdict</th>
            <th className="px-3 py-2 font-medium">Taxonomy</th>
            <th className="px-3 py-2 font-medium">Attempts</th>
          </tr>
        </thead>
        <tbody>
          {repos.map((repo) => (
            <Fragment key={repo.name}>
              <tr
                onClick={() => setExpanded(expanded === repo.name ? null : repo.name)}
                className="cursor-pointer border-t border-border hover:bg-surface"
              >
                <td className="px-3 py-2 text-text-primary">{repo.name}</td>
                <td className="px-3 py-2">
                  <VerdictBadge verdict={repo.verdict} size="sm" />
                </td>
                <td className="px-3 py-2 text-text-secondary">{repo.taxonomy_code ?? "—"}</td>
                <td className="px-3 py-2 text-text-secondary">{repo.attempts_used ?? 0}</td>
              </tr>
              {expanded === repo.name && (
                <tr className="border-t border-border bg-bg">
                  <td colSpan={4} className="px-3 py-3 text-text-secondary">
                    {repo.repo_url && <p className="break-all">{repo.repo_url}</p>}
                    {repo.duration_seconds !== undefined && <p>duration: {repo.duration_seconds}s</p>}
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}
