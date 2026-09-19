import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { VerdictBadge } from "../components/VerdictBadge";
import { RepairAttemptCard } from "../components/RepairAttemptCard";
import { buildTimelineItems } from "../lib/timeline";

export function RunTimeline() {
  const { runId } = useParams<{ runId: string }>();
  const queryClient = useQueryClient();
  const [elapsed, setElapsed] = useState(0);

  const runQuery = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.getRun(runId!),
    enabled: !!runId,
  });

  const isDone = runQuery.data?.stage === "DONE";

  const certificateQuery = useQuery({
    queryKey: ["certificate", runId],
    queryFn: () => api.getCertificate(runId!),
    enabled: !!runId && isDone,
  });

  const executeMutation = useMutation({
    mutationFn: () => api.executeRun(runId!),
    onMutate: () => {
      setElapsed(0);
      const timer = setInterval(() => setElapsed((s) => s + 1), 1000);
      return { timer };
    },
    onSettled: (_data, _err, _vars, context) => {
      if (context?.timer) clearInterval(context.timer);
      queryClient.invalidateQueries({ queryKey: ["run", runId] });
      queryClient.invalidateQueries({ queryKey: ["certificate", runId] });
    },
  });

  if (runQuery.isLoading) {
    return <p className="font-mono text-sm text-text-secondary">Loading run…</p>;
  }
  if (runQuery.isError || !runQuery.data) {
    return (
      <ErrorPanel message={runQuery.error instanceof ApiError ? runQuery.error.message : "Run not found."} />
    );
  }

  const run = runQuery.data;
  const items = certificateQuery.data
    ? buildTimelineItems(certificateQuery.data.full_log, certificateQuery.data.diffs)
    : [];

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <p className="font-mono text-xs text-text-secondary">Run</p>
          <h1 className="mt-1 break-all font-mono text-lg font-medium text-text-primary">{run.repo_url}</h1>
          {run.commit_sha && (
            <p className="mt-1 font-mono text-xs text-text-secondary">commit {run.commit_sha.slice(0, 12)}</p>
          )}
        </div>
        {run.verdict && <VerdictBadge verdict={run.verdict} size="lg" />}
      </div>

      {!isDone && !executeMutation.isPending && (
        <div className="rounded-sm border border-border bg-surface px-5 py-6 text-center">
          <p className="mb-4 font-mono text-sm text-text-secondary">
            Intake complete. Ready to build the environment and execute.
          </p>
          <button
            onClick={() => executeMutation.mutate()}
            className="rounded-sm bg-signal px-5 py-2.5 font-mono text-sm font-medium text-bg transition-opacity hover:opacity-90"
          >
            Start reproduction run
          </button>
        </div>
      )}

      {executeMutation.isPending && (
        <div className="flex items-center gap-3 rounded-sm border border-border bg-surface px-5 py-6">
          <span className="h-2 w-2 animate-pulse rounded-full bg-signal" />
          <p className="font-mono text-sm text-text-secondary">
            Running — building the sandbox, executing, repairing if needed… ({elapsed}s elapsed)
          </p>
        </div>
      )}

      {executeMutation.isError && (
        <div className="mt-4 rounded-sm border border-alarm-dim bg-alarm-dim/10 px-4 py-3 font-mono text-xs text-alarm">
          {executeMutation.error instanceof ApiError
            ? executeMutation.error.message
            : "The run failed to execute."}
        </div>
      )}

      {isDone && certificateQuery.isLoading && (
        <p className="font-mono text-sm text-text-secondary">Loading certificate…</p>
      )}

      {isDone && certificateQuery.data && (
        <>
          {run.verdict === "INDETERMINATE" && run.indeterminate_reason && (
            <div className="mb-4 rounded-sm border border-warn/40 bg-warn/10 px-4 py-3 font-mono text-xs text-warn">
              <span className="font-semibold">Indeterminate: </span>
              {run.indeterminate_reason}
            </div>
          )}

          <ol className="space-y-3 border-l border-border pl-5">
            {items.map((item) =>
              item.type === "attempt" ? (
                <li key={item.key} className="-ml-[1.65rem]">
                  <RepairAttemptCard attempt={item.attempt} />
                </li>
              ) : (
                <li key={item.key} className="relative">
                  <span className="absolute -left-[1.4rem] top-1.5 h-1.5 w-1.5 rounded-full bg-border" />
                  <p className="font-mono text-xs">
                    {item.stage && <span className="text-text-secondary">[{item.stage}]</span>}{" "}
                    <span className="text-text-primary/90">{item.message}</span>
                  </p>
                </li>
              ),
            )}
          </ol>

          <div className="mt-6">
            <Link
              to={`/runs/${run.id}/certificate`}
              className="inline-block rounded-sm border border-signal-dim bg-signal-dim/10 px-4 py-2 font-mono text-sm text-signal transition-opacity hover:opacity-90"
            >
              View full certificate →
            </Link>
          </div>
        </>
      )}
    </div>
  );
}

function ErrorPanel({ message }: { message: string }) {
  return (
    <div className="rounded-sm border border-alarm-dim bg-alarm-dim/10 px-4 py-3 font-mono text-sm text-alarm">
      {message}
    </div>
  );
}
