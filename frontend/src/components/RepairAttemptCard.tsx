import type { RepairAttemptDiff, ResolvedSource, TavilySource, TimeMachineRecord } from "../api";
import { DiffView } from "./DiffView";
import { EnvDeltaView } from "./EnvDeltaView";

/** Defense in depth: `source.url` comes from a real Tavily search result,
 * not directly attacker-controlled, but nothing between that API response
 * and this render validates it's actually an http(s) link before it
 * becomes a clickable `href` — a `javascript:` (or other) URL scheme
 * would execute on click rather than navigate. Cheap and zero-cost to
 * guard regardless of how the URL got here. */
function isSafeHttpUrl(url: string): boolean {
  try {
    return ["http:", "https:"].includes(new URL(url).protocol);
  } catch {
    return false;
  }
}

function TavilySources({ sources }: { sources?: TavilySource[] }) {
  if (!sources || sources.length === 0) return null;
  return (
    <div className="mt-3 border-t border-border/60 pt-2">
      <p className="font-mono text-[11px] uppercase tracking-wide text-text-secondary">
        Cited sources (Tavily)
      </p>
      <ul className="mt-1 space-y-1">
        {sources.map((source, i) =>
          isSafeHttpUrl(source.url) ? (
            <li key={i} className="font-mono text-[11px]">
              <a
                href={source.url}
                target="_blank"
                rel="noreferrer"
                className="text-signal underline decoration-signal-dim underline-offset-2 hover:opacity-80"
              >
                [{i + 1}] {source.title || source.url}
              </a>
            </li>
          ) : (
            <li key={i} className="font-mono text-[11px] text-text-secondary">
              [{i + 1}] {source.title || "(source with an unrecognized URL scheme, not linked)"}
            </li>
          ),
        )}
      </ul>
    </div>
  );
}

function ResolvedSources({ sources }: { sources?: ResolvedSource[] }) {
  if (!sources || sources.length === 0) return null;
  return (
    <div className="mt-3 border-t border-border/60 pt-2">
      <p className="font-mono text-[11px] uppercase tracking-wide text-text-secondary">Verified sources (RERUN)</p>
      <ul className="mt-1 space-y-1">
        {sources.map((s, i) => {
          const href = s.kind === "git" ? s.commit_url ?? s.url : s.url;
          const label =
            s.kind === "git"
              ? `git ${s.url} @ ${s.commit?.slice(0, 12)} (committed ${s.committed_at})${s.note ? ` ${s.note}` : ""}`
              : `PyPI ${s.package} ${s.version} (uploaded ${s.uploaded}; ${s.cpython_tags?.join(",") || "sdist/any"})`;
          return (
            <li key={i} className="font-mono text-[11px]">
              {isSafeHttpUrl(href) ? (
                <a href={href} target="_blank" rel="noreferrer" className="text-signal underline decoration-signal-dim underline-offset-2 hover:opacity-80">
                  {label}
                </a>
              ) : (
                <span className="text-text-secondary">{label}</span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function TimeMachineView({ record }: { record: TimeMachineRecord }) {
  const eraSource =
    record.era.source === "dependency-files"
      ? `latest change to dependency files (${Object.entries(record.era.detail).map(([k, v]) => `${k} ${v}`).join(", ")})`
      : `pinned commit date — fallback${record.era.detail.note ? `: ${record.era.detail.note}` : ""}`;
  return (
    <dl className="mt-2 space-y-1 font-mono text-[11px] text-text-secondary">
      <div>
        <dt className="inline text-text-primary">Era: </dt>
        <dd className="inline">
          {record.era.date} — {eraSource}
        </dd>
      </div>
      <div>
        <dt className="inline text-text-primary">Python: </dt>
        <dd className="inline">
          {record.python.version} — {record.python.reason}
        </dd>
      </div>
      {record.apt_added.length > 0 && (
        <div>
          <dt className="inline text-text-primary">System packages: </dt>
          <dd className="inline">
            {record.apt_added.join(", ")} (evidence: {record.apt_reason})
          </dd>
        </div>
      )}
      <div>
        <dt className="inline text-text-primary">Lock: </dt>
        <dd className="inline">
          {record.lock.ok
            ? `${record.lock.lock.length} package(s) resolved together, nothing newer than the era`
            : `could not be resolved — ${record.lock.error.slice(-200)}`}
        </dd>
      </div>
      {record.lock.not_on_index.length > 0 && (
        <div>
          <dt className="inline text-text-primary">Not on PyPI: </dt>
          <dd className="inline">{record.lock.not_on_index.join(", ")}</dd>
        </div>
      )}
      {record.lock.ok && (
        <details>
          <summary className="cursor-pointer">Locked packages</summary>
          <pre className="mt-1 max-h-48 overflow-auto rounded-sm bg-bg px-3 py-2">{record.lock.lock.join("\n")}</pre>
        </details>
      )}
    </dl>
  );
}

/**
 * The tamper-gate REJECT state is the project's differentiator (see
 * RERUN_BUILD_DIRECTIVE.md §8 S2) — it must be visually loud, distinct,
 * and impossible to mistake for a routine log line. This is the one
 * deliberately animated moment in the whole UI (a single strobe pulse on
 * mount), everywhere else stays quiet by design.
 */
export function RepairAttemptCard({ attempt }: { attempt: RepairAttemptDiff }) {
  const envChanges = attempt.env_delta ?? [];
  if (attempt.origin === "time_machine" && attempt.time_machine) {
    const ran = attempt.exit_code !== null && attempt.exit_code !== undefined;
    return (
      <div className="rounded-sm border border-signal-dim bg-signal-dim/10 px-4 py-3">
        <Header
          label={`Time machine — era environment${ran ? `, re-execution exit code ${attempt.exit_code}` : " (not applied)"}`}
          tone={ran ? "signal" : "neutral"}
        />
        <TimeMachineView record={attempt.time_machine} />
      </div>
    );
  }
  if (attempt.gate_decision === "DECLINED") {
    return (
      <div className="rounded-sm border border-border bg-surface px-4 py-3">
        <Header label={`Repair attempt ${attempt.attempt_number} — model declined`} tone="neutral" />
        <p className="mt-2 font-mono text-xs text-text-secondary">
          The repair model did not propose a fix it was confident about for this attempt.
        </p>
        <TavilySources sources={attempt.tavily_sources} />
        <ResolvedSources sources={attempt.resolved_sources} />
      </div>
    );
  }

  if (attempt.gate_decision === "REJECT") {
    return (
      <div className="animate-alarm-strobe rounded-sm border-2 border-alarm bg-alarm-dim/15 px-4 py-3">
        <Header label={`Repair attempt ${attempt.attempt_number} — tamper gate REJECTED`} tone="alarm" />
        <ul className="mt-2 space-y-1">
          {attempt.gate_violations.map((v, i) => (
            <li key={i} className="font-mono text-xs text-alarm">
              <span className="font-semibold">{v.rule}</span> — {v.reason}
            </li>
          ))}
        </ul>
        {envChanges.length > 0 && (
          <details className="mt-3">
            <summary className="cursor-pointer font-mono text-[11px] text-text-secondary">
              View the rejected environment delta (never applied)
            </summary>
            <div className="mt-2">
              <EnvDeltaView changes={envChanges} />
            </div>
          </details>
        )}
        {(attempt.diff_text || envChanges.length === 0) && (
          <details className="mt-3">
            <summary className="cursor-pointer font-mono text-[11px] text-text-secondary">
              View the rejected diff (never applied)
            </summary>
            <div className="mt-2">
              <DiffView diff={attempt.diff_text} />
            </div>
          </details>
        )}
        <TavilySources sources={attempt.tavily_sources} />
        <ResolvedSources sources={attempt.resolved_sources} />
      </div>
    );
  }

  // PASS
  return (
    <div className="rounded-sm border border-signal-dim bg-signal-dim/10 px-4 py-3">
      <Header label={`Repair attempt ${attempt.attempt_number} — tamper gate PASSED`} tone="signal" />
      {attempt.exit_code !== null && attempt.exit_code !== undefined && (
        <p className="mt-1 font-mono text-xs text-text-secondary">
          Re-execution exit code: <span className="text-text-primary">{attempt.exit_code}</span>
        </p>
      )}
      {envChanges.length > 0 && (
        <details className="mt-3" open>
          <summary className="cursor-pointer font-mono text-[11px] text-text-secondary">Applied environment delta</summary>
          <div className="mt-2">
            <EnvDeltaView changes={envChanges} />
          </div>
        </details>
      )}
      {(attempt.diff_text || envChanges.length === 0) && (
        <details className="mt-3" open>
          <summary className="cursor-pointer font-mono text-[11px] text-text-secondary">Applied diff</summary>
          <div className="mt-2">
            <DiffView diff={attempt.diff_text} />
          </div>
        </details>
      )}
      <TavilySources sources={attempt.tavily_sources} />
      <ResolvedSources sources={attempt.resolved_sources} />
    </div>
  );
}

function Header({ label, tone }: { label: string; tone: "alarm" | "signal" | "neutral" }) {
  const dot = tone === "alarm" ? "bg-alarm" : tone === "signal" ? "bg-signal" : "bg-text-secondary";
  const text = tone === "alarm" ? "text-alarm" : tone === "signal" ? "text-signal" : "text-text-secondary";
  return (
    <div className={`flex items-center gap-2 font-mono text-xs font-semibold uppercase tracking-wide ${text}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
      {label}
    </div>
  );
}
