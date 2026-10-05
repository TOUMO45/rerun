import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError, type RunListItem } from "../api";
import { VerdictBadge, notesOfLabel } from "../components/VerdictBadge";
import { DemoBanner, useDemoMode } from "../components/DemoBanner";

/** `runs/corpus_v2_batch/<tag>/<arm>/NN_<owner>__<repo>.json` -> its parts; null for a live (non-demo) run. */
export function parseDemoSource(source: string | null): { tag: string; arm: string; entry: string; name: string } | null {
  if (!source) return null;
  const match = source.match(/^runs\/corpus_v2_batch\/([^/]+)\/([^/]+)\/(\d{2})_(.+)\.json$/);
  if (!match) return null;
  return { tag: match[1], arm: match[2], entry: match[3], name: match[4] };
}

/** "https://github.com/owner/repo" -> "owner/repo". */
export function repoName(url: string): string {
  return url.replace(/^https?:\/\/github\.com\//, "").replace(/\/+$/, "").replace(/\.git$/, "");
}

export function Gallery() {
  const demoMode = useDemoMode();
  const query = useQuery({ queryKey: ["runs"], queryFn: api.listRuns });

  if (query.isLoading) {
    return <p className="font-mono text-sm text-text-secondary">Loading gallery…</p>;
  }
  if (query.isError || !query.data) {
    return (
      <div className="rounded-sm border border-alarm-dim bg-alarm-dim/10 px-4 py-3 font-mono text-sm text-alarm">
        {query.error instanceof ApiError ? query.error.message : "The run list could not be loaded."}
      </div>
    );
  }

  const runs = query.data.runs;
  // Recorded audits read best in corpus order (entry number, then tag); live runs keep the API's newest-first order.
  const recorded = runs
    .filter((r) => r.demo_source)
    .sort((a, b) => (a.demo_source!.split("/").pop()! < b.demo_source!.split("/").pop()! ? -1 : 1));
  const live = runs.filter((r) => !r.demo_source);

  return (
    <div className="space-y-6">
      <div>
        <p className="font-mono text-xs uppercase tracking-wide text-text-secondary">Gallery</p>
        <h1 className="mt-1 font-display text-2xl font-semibold tracking-tight text-text-primary sm:text-3xl">
          Recorded audits
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-secondary">
          Every row is a real RERUN run, served from the committed record of that run — the verdict, the error chain and the
          signed certificate are shown exactly as they were written. DEV and gate entries of the corpus only: the pre-registered
          TEST entries ran once each at the freeze and are reported on their own, not replayed here.
        </p>
      </div>

      {demoMode && <DemoBanner />}

      {runs.length === 0 ? (
        <p className="rounded-sm border border-border bg-surface shadow-card px-5 py-6 text-center font-mono text-sm text-text-secondary">
          No runs yet.
        </p>
      ) : (
        <>
          {recorded.length > 0 && <RunTable title="Recorded audits" runs={recorded} />}
          {live.length > 0 && <RunTable title="Live runs" runs={live} />}
        </>
      )}
    </div>
  );
}

function RunTable({ title, runs }: { title: string; runs: RunListItem[] }) {
  return (
    <div className="overflow-hidden rounded-sm border border-border">
      <table className="w-full text-left font-mono text-xs">
        <caption className="bg-surface px-4 py-2 text-left text-[11px] uppercase tracking-wide text-text-secondary">
          {title} ({runs.length})
        </caption>
        <thead className="bg-surface-raised text-text-secondary">
          <tr>
            <th className="px-4 py-2 font-normal">Entry</th>
            <th className="px-4 py-2 font-normal">Repository</th>
            <th className="px-4 py-2 font-normal">Harness</th>
            <th className="px-4 py-2 font-normal">Verdict</th>
            <th className="px-4 py-2 font-normal">Blocker class</th>
            <th className="px-4 py-2 font-normal"></th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => {
            const source = parseDemoSource(run.demo_source);
            const blocked = run.verdict !== "RUNS_CLEAN" && run.verdict !== "RUNS_AFTER_REPAIR";
            return (
              <tr key={run.id} className="border-t border-border bg-surface" data-testid="gallery-row">
                <td className="px-4 py-2.5 text-text-secondary">{source ? `#${source.entry}` : "—"}</td>
                <td className="px-4 py-2.5 text-text-primary">
                  <span className="break-all">{repoName(run.repo_url)}</span>
                  {run.commit_sha && (
                    <span className="ml-2 text-text-secondary">{run.commit_sha.slice(0, 7)}</span>
                  )}
                </td>
                <td className="px-4 py-2.5 text-text-secondary">
                  {source ? (
                    <>
                      {source.tag}
                      <span className="ml-1 text-text-secondary/70">{source.arm}</span>
                    </>
                  ) : (
                    "live"
                  )}
                </td>
                <td className="px-4 py-2.5">
                  {run.verdict ? (
                    <VerdictBadge verdict={run.verdict} size="sm" notes={notesOfLabel(run.verdict_label)} />
                  ) : (
                    <span className="text-text-secondary">{run.status.toLowerCase()}</span>
                  )}
                </td>
                <td className="px-4 py-2.5 text-text-secondary">{blocked && run.taxonomy_code ? run.taxonomy_code : "—"}</td>
                <td className="px-4 py-2.5 text-right">
                  {run.status === "DONE" ? (
                    <Link to={`/runs/${run.id}/certificate`} className="text-signal hover:underline">
                      Certificate →
                    </Link>
                  ) : (
                    <Link to={`/runs/${run.id}`} className="text-text-secondary hover:underline">
                      Open →
                    </Link>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
