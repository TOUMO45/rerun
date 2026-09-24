import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import type { Baseline } from "../api";
import { VerdictBadge } from "../components/VerdictBadge";
import { RepairAttemptCard, TimeMachineView } from "../components/RepairAttemptCard";
import { DiffView } from "../components/DiffView";
import { EnvDeltaView } from "../components/EnvDeltaView";
import { ScopeLine } from "../components/ScopeLine";

export function Certificate() {
  const { runId } = useParams<{ runId: string }>();

  const runQuery = useQuery({ queryKey: ["run", runId], queryFn: () => api.getRun(runId!), enabled: !!runId });
  const certQuery = useQuery({
    queryKey: ["certificate", runId],
    queryFn: () => api.getCertificate(runId!),
    enabled: !!runId,
  });

  if (runQuery.isLoading || certQuery.isLoading) {
    return <p className="font-mono text-sm text-text-secondary">Loading certificate…</p>;
  }
  if (certQuery.isError || !certQuery.data || !runQuery.data) {
    return (
      <div className="rounded-sm border border-alarm-dim bg-alarm-dim/10 px-4 py-3 font-mono text-sm text-alarm">
        {certQuery.error instanceof ApiError ? certQuery.error.message : "Certificate unavailable."}
      </div>
    );
  }

  const run = runQuery.data;
  const cert = certQuery.data;
  // "Applied" = gate PASS and actually re-executed (a PASS whose git apply
  // failed has no exit code and changed nothing).
  const applied = cert.diffs.filter(
    (a) => a.gate_decision === "PASS" && a.exit_code !== null && a.exit_code !== undefined,
  );
  const appliedEnvChanges = applied.flatMap((a) => a.env_delta ?? []);
  const timeMachine = applied.find((a) => a.origin === "time_machine")?.time_machine ?? null;
  const appliedCodeDiff = applied
    .map((a) => a.diff_text)
    .filter((d) => d.trim())
    .join("");

  const downloadCertificate = () => {
    const payload = {
      repo_url: run.repo_url,
      commit_sha: run.commit_sha,
      build_plan: cert.build_plan,
      full_log: cert.full_log,
      diffs: cert.diffs,
      verdict: cert.verdict,
      timestamp: cert.timestamp,
      reproduction_passport_hash: cert.reproduction_passport_hash,
      // Bundle v2+ fields are part of the hash; v1 certificates omit them.
      ...(cert.bundle_version && cert.bundle_version >= 2
        ? { bundle_version: cert.bundle_version, baseline: cert.baseline, recovery: cert.recovery }
        : {}),
    };
    triggerDownload(`rerun-certificate-${run.id}.json`, JSON.stringify(payload, null, 2));
  };

  const exportPatch = () => {
    if (!appliedCodeDiff) return;
    triggerDownload(`rerun-patch-${run.id}.patch`, appliedCodeDiff);
  };

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="font-mono text-xs text-text-secondary">Execution Certificate</p>
          <h1 className="mt-1 break-all font-mono text-lg font-medium text-text-primary">{run.repo_url}</h1>
          <p className="mt-1 font-mono text-xs text-text-secondary">
            commit {run.commit_sha?.slice(0, 12) ?? "unknown"} · {new Date(cert.timestamp).toLocaleString()}
          </p>
        </div>
        <VerdictBadge verdict={cert.verdict} size="lg" />
      </div>

      {run.taxonomy_code && (
        <span className="inline-block rounded-sm border border-border bg-surface px-2.5 py-1 font-mono text-[11px] text-text-secondary">
          taxonomy: {run.taxonomy_code}
        </span>
      )}
      {run.indeterminate_reason && (
        <div className="rounded-sm border border-warn/40 bg-warn/10 px-4 py-3 font-mono text-xs text-warn">
          {run.indeterminate_reason}
        </div>
      )}

      {cert.baseline && <BaselineSection baseline={cert.baseline} verdict={cert.verdict} recovery={!!cert.recovery} />}

      <section className="rounded-sm border border-border bg-surface px-5 py-4">
        <h2 className="font-mono text-xs uppercase tracking-wide text-text-secondary">Summary</h2>
        <p className="mt-2 text-sm leading-relaxed text-text-primary">{cert.certificate_prose}</p>
      </section>

      <section className="rounded-sm border border-border bg-surface px-5 py-4">
        <h2 className="font-mono text-xs uppercase tracking-wide text-text-secondary">Build plan</h2>
        <pre className="mt-2 overflow-auto font-mono text-[11px] leading-relaxed text-text-primary/90">
          {JSON.stringify(cert.build_plan, null, 2)}
        </pre>
      </section>

      {cert.diffs.length > 0 && (
        <section className="rounded-sm border border-border bg-surface px-5 py-4">
          <h2 className="font-mono text-xs uppercase tracking-wide text-text-secondary">Environment Delta</h2>
          <p className="mt-1 font-mono text-[11px] text-text-secondary">
            Build-plan changes that were applied and re-executed (the repository's files are not edited).
          </p>
          <div className="mt-2">
            {timeMachine && <TimeMachineView record={timeMachine} />}
            <EnvDeltaView changes={appliedEnvChanges} />
          </div>
        </section>
      )}

      {cert.diffs.length > 0 && (
        <section className="rounded-sm border border-border bg-surface px-5 py-4">
          <h2 className="font-mono text-xs uppercase tracking-wide text-text-secondary">Code Diff</h2>
          <p className="mt-1 font-mono text-[11px] text-text-secondary">
            Changes to the repository's own files that were applied and re-executed.
          </p>
          <div className="mt-2">
            <DiffView diff={appliedCodeDiff} />
          </div>
        </section>
      )}

      {cert.diffs.length > 0 && (
        <section>
          <h2 className="mb-2 font-mono text-xs uppercase tracking-wide text-text-secondary">Repair attempts</h2>
          <div className="space-y-3">
            {cert.diffs.map((attempt) => (
              <RepairAttemptCard key={attempt.attempt_number} attempt={attempt} />
            ))}
          </div>
        </section>
      )}

      <section className="rounded-sm border border-signal-dim bg-signal-dim/10 px-5 py-4">
        <h2 className="font-mono text-xs uppercase tracking-wide text-signal">Reproduction Passport</h2>
        <p className="mt-2 break-all font-mono text-xs text-text-primary">{cert.reproduction_passport_hash}</p>
        <p className="mt-2 font-mono text-[11px] leading-relaxed text-text-secondary">
          Download the certificate below, then verify it independently — this does not
          require trusting RERUN's own UI:
        </p>
        <code className="mt-1 block font-mono text-[11px] text-text-secondary">
          python scripts/verify_passport.py rerun-certificate-{run.id}.json
        </code>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            onClick={downloadCertificate}
            className="rounded-sm border border-signal-dim px-3 py-1.5 font-mono text-xs text-signal transition-opacity hover:opacity-90"
          >
            Download certificate JSON
          </button>
          {appliedCodeDiff && (
            <button
              onClick={exportPatch}
              className="rounded-sm border border-border px-3 py-1.5 font-mono text-xs text-text-secondary transition-opacity hover:opacity-90"
            >
              Export patch (.patch)
            </button>
          )}
          <button
            onClick={() => triggerDownload(`rerun-full-log-${run.id}.txt`, cert.full_log)}
            className="rounded-sm border border-border px-3 py-1.5 font-mono text-xs text-text-secondary transition-opacity hover:opacity-90"
          >
            Download full log
          </button>
        </div>
      </section>

      <ScopeLine />
    </div>
  );
}

const COMPLETED = new Set(["RUNS_CLEAN", "RUNS_AFTER_REPAIR"]);

/** Baseline (the repo exactly as published) vs RERUN's final run. Wording is
 * deliberately about execution only — RERUN never checks a paper's results. */
function BaselineSection({ baseline, verdict, recovery }: { baseline: Baseline; verdict: string; recovery: boolean }) {
  const baselineText =
    baseline.result === "RUNS_CLEAN"
      ? "ran to completion"
      : baseline.result === "FAILS"
        ? `did not run to completion (exit code ${baseline.exit_code}${baseline.taxonomy_code ? `, ${baseline.taxonomy_code}` : ""})`
        : "was not run";
  const finalText = COMPLETED.has(verdict) ? "ran to completion" : `did not run to completion (${verdict})`;
  return (
    <section className="rounded-sm border border-border bg-surface px-5 py-4">
      <h2 className="font-mono text-xs uppercase tracking-wide text-text-secondary">Baseline vs RERUN</h2>
      <dl className="mt-2 space-y-1 font-mono text-xs">
        <div>
          <dt className="inline text-text-secondary">As published (baseline): </dt>
          <dd className="inline text-text-primary">{baselineText}</dd>
        </div>
        <div>
          <dt className="inline text-text-secondary">After RERUN: </dt>
          <dd className="inline text-text-primary">{finalText}</dd>
        </div>
      </dl>
      {recovery && (
        <p className="mt-2 font-mono text-xs text-signal">Recovered: failed as published, ran to completion after RERUN.</p>
      )}
      {baseline.evidence && (
        <p className="mt-1 break-all font-mono text-[11px] text-text-secondary">baseline evidence: {baseline.evidence}</p>
      )}
    </section>
  );
}

function triggerDownload(filename: string, content: string) {
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
