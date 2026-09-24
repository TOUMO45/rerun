import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, streamRun } from "../api";
import { VerdictBadge } from "../components/VerdictBadge";
import { RepairAttemptCard } from "../components/RepairAttemptCard";
import { buildTimelineItems, extractLatestSandboxId, extractWallClockSeconds, parseLogLine } from "../lib/timeline";

export function RunTimeline() {
  const { runId } = useParams<{ runId: string }>();
  const queryClient = useQueryClient();
  const [hasStarted, setHasStarted] = useState(false);
  const [liveLines, setLiveLines] = useState<string[]>([]);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const logEndRef = useRef<HTMLDivElement>(null);

  const runQuery = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.getRun(runId!),
    enabled: !!runId,
    // If a reload lands on a run some other tab/session already kicked
    // off (stage === "EXECUTING" — see the backend's duplicate-execution
    // guard), poll instead of leaving the user stuck on a dead page with
    // no way to find out when it finishes short of manually refreshing.
    refetchInterval: (query) => (query.state.data?.stage === "EXECUTING" ? 3000 : false),
  });

  const isDone = runQuery.data?.stage === "DONE";
  const isExecutingElsewhere = runQuery.data?.stage === "EXECUTING" && !hasStarted;

  const certificateQuery = useQuery({
    queryKey: ["certificate", runId],
    queryFn: () => api.getCertificate(runId!),
    enabled: !!runId && isDone,
  });

  // Opens the real SSE connection (§4: `GET /runs/{id}/stream`) the moment
  // the user starts the run, rendering each log line the instant the
  // backend produces it rather than only after the whole pipeline finishes.
  // The effect's own cleanup closes the EventSource, so navigating away
  // mid-run never leaves a dangling connection.
  useEffect(() => {
    if (!hasStarted || !runId || isDone) return;

    setLiveLines([]);
    setStreamError(null);
    setElapsed(0);
    const timer = setInterval(() => setElapsed((s) => s + 1), 1000);

    const close = streamRun(
      runId,
      (event) => {
        if ("line" in event) {
          setLiveLines((lines) => [...lines, event.line]);
        } else {
          clearInterval(timer);
          queryClient.invalidateQueries({ queryKey: ["run", runId] });
          queryClient.invalidateQueries({ queryKey: ["certificate", runId] });
        }
      },
      () => {
        clearInterval(timer);
        setStreamError("Lost connection to the run stream.");
      },
    );

    return () => {
      clearInterval(timer);
      close();
    };
  }, [hasStarted, runId, isDone, queryClient]);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ block: "nearest" });
  }, [liveLines]);

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

      {!isDone && !hasStarted && isExecutingElsewhere && (
        <div className="rounded-sm border border-border bg-surface px-5 py-6 text-center">
          <span className="mb-2 inline-block h-2 w-2 animate-pulse rounded-full bg-signal" />
          <p className="font-mono text-sm text-text-secondary">
            An execution run is already in progress for this run — started from another
            tab, or from before this page was reloaded. Checking back automatically…
          </p>
        </div>
      )}

      {!isDone && !hasStarted && !isExecutingElsewhere && (
        <div className="rounded-sm border border-border bg-surface px-5 py-6 text-center">
          <p className="mb-4 font-mono text-sm text-text-secondary">
            Intake complete. Ready to build the environment and execute.
          </p>
          <button
            onClick={() => setHasStarted(true)}
            className="rounded-sm bg-signal px-5 py-2.5 font-mono text-sm font-medium text-bg transition-opacity hover:opacity-90"
          >
            Start execution run
          </button>
        </div>
      )}

      {!isDone && hasStarted && (
        <div className="rounded-sm border border-border bg-surface">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-3">
            <div className="flex items-center gap-3">
              <span className="h-2 w-2 animate-pulse rounded-full bg-signal" />
              <p className="font-mono text-sm text-text-secondary">
                Running — building the sandbox, executing, repairing if needed…
              </p>
            </div>
            <SandboxBadge liveLines={liveLines} elapsed={elapsed} />
          </div>
          <div className="max-h-96 overflow-y-auto px-5 py-4">
            {liveLines.length === 0 ? (
              <p className="font-mono text-xs text-text-secondary">Waiting for the first event…</p>
            ) : (
              <ol className="space-y-1.5">
                {liveLines.map((rawLine, index) => {
                  const { stage, message } = parseLogLine(rawLine);
                  const isError = rawLine.startsWith("[error]");
                  return (
                    <li key={index} className={`font-mono text-xs ${isError ? "text-alarm" : ""}`}>
                      {stage && <span className="text-text-secondary">[{stage}]</span>}{" "}
                      <span className={isError ? "" : "text-text-primary/90"}>{message}</span>
                    </li>
                  );
                })}
              </ol>
            )}
            <div ref={logEndRef} />
          </div>
        </div>
      )}

      {streamError && (
        <div className="mt-4 rounded-sm border border-alarm-dim bg-alarm-dim/10 px-4 py-3 font-mono text-xs text-alarm">
          {streamError}
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

/** §8 S2: "Live sandbox badge (id, elapsed time, wall-clock remaining)".
 * `id` and the wall-clock ceiling only become knowable once specific log
 * lines have streamed in (see lib/timeline.ts) — each shows "…" until
 * then rather than a fabricated placeholder, since this badge's whole
 * point is showing real sandbox state, not a guess. Wall-clock remaining
 * counts down using the same client-side `elapsed` ticker already driving
 * the "Running… (Ns elapsed)" text, so it moves smoothly between log
 * lines rather than only updating when a new one arrives.
 */
function SandboxBadge({ liveLines, elapsed }: { liveLines: string[]; elapsed: number }) {
  const wallClockSeconds = extractWallClockSeconds(liveLines);
  const sandboxId = extractLatestSandboxId(liveLines);
  const remaining = wallClockSeconds !== null ? Math.max(wallClockSeconds - elapsed, 0) : null;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-sm border border-border bg-bg px-3 py-1.5 font-mono text-[11px] text-text-secondary">
      <span>
        sandbox: <span className="text-text-primary">{sandboxId ? sandboxId.slice(0, 8) : "…"}</span>
      </span>
      <span>
        elapsed: <span className="text-text-primary">{elapsed}s</span>
      </span>
      <span>
        wall-clock remaining:{" "}
        <span className={remaining === 0 ? "text-alarm" : "text-text-primary"}>
          {remaining !== null ? `${remaining}s` : "…"}
        </span>
      </span>
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
