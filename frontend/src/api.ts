const API_BASE = "/api";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      // response had no JSON body; fall back to statusText
    }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

export type Verdict =
  | "RUNS_CLEAN"
  | "RUNS_AFTER_REPAIR"
  | "BLOCKED"
  | "INDETERMINATE"
  | "NOT_ATTEMPTABLE"
  | "TIMEOUT"
  /** RERUN's own harness failed its integrity check — not a verdict on the repository. */
  | "INVALID_HARNESS"
  /** An external service (sandbox, model API, GitHub, package index) failed — not a verdict on the repository. */
  | "INFRA_ERROR"
  /** The repository exceeds RERUN's pre-declared upload cap — a harness limitation, not a verdict. */
  | "UPLOAD_TOO_LARGE";

export interface RunOut {
  id: string;
  repo_url: string;
  commit_sha: string | null;
  stage: string;
  verdict: Verdict | null;
  taxonomy_code: string | null;
  indeterminate_reason: string | null;
  attempts_used: number;
  /** DEMO mode: the committed record this run replays (repo-relative path); null for a live run. */
  demo_source?: string | null;
  created_at: string;
  updated_at: string;
}

/** One row of `GET /runs` — cheap, no certificate body. */
export interface RunListItem {
  id: string;
  repo_url: string;
  commit_sha: string | null;
  status: string;
  verdict: Verdict | null;
  taxonomy_code: string | null;
  demo_source: string | null;
  created_at: string;
  /** harness-v1.7: the verdict with its labels (semantic change, RESOURCE-ADAPTED, memory hook, dependency change); absent on older servers. */
  verdict_label?: string | null;
}

export interface RunListOut {
  runs: RunListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface TavilySource {
  title: string;
  url: string;
  content: string;
}

export interface EnvChange {
  op: string;
  package: string | null;
  version: string | null;
  git_url: string | null;
  commit: string | null;
  justification: string;
  evidence: string;
  /** New execute command (op "command"); the documented command is ground truth and only non-scale flags may change. */
  command?: string | null;
}

export interface RepairAttemptDiff {
  attempt_number: number;
  diff_text: string;
  gate_decision: "PASS" | "REJECT" | "DECLINED";
  gate_violations: { rule: string; reason: string; file?: string }[];
  exit_code: number | null;
  stdout_tail?: string;
  stderr_tail?: string;
  tavily_sources?: TavilySource[];
  /** Structured build-plan edits (environment layer); diff_text is the code layer. */
  env_delta?: EnvChange[];
  /** Sources RERUN itself verified for this attempt (git repo pinned to a real commit, PyPI history). */
  resolved_sources?: ResolvedSource[];
  /** "time_machine" = RERUN's deterministic era environment (attempt 0); "model" = a repairer proposal. */
  origin?: "model" | "time_machine";
  time_machine?: TimeMachineRecord | DeterministicStepRecord | null;
}

/** A deterministic time-machine step taken after the era run (no model), e.g.
 * building one locked package with --no-build-isolation. */
export interface DeterministicStepRecord {
  step: string;
  package: string;
  module: string;
  evidence: string;
}

export function isDeterministicStep(
  record: TimeMachineRecord | DeterministicStepRecord | null | undefined,
): record is DeterministicStepRecord {
  return !!record && "step" in record;
}

export interface TimeMachineRecord {
  era: { date: string; source: "dependency-files" | "pinned-commit"; detail: Record<string, string> };
  python: { version: string; reason: string; source: string };
  undeclared_imports: string[];
  apt_added: string[];
  apt_reason: string;
  lock: { ok: boolean; lock: string[]; inputs: string[]; not_on_index: string[]; command: string; error: string };
}

export interface ResolvedSource {
  kind: "git" | "pypi";
  url: string;
  commit?: string;
  committed_at?: string;
  commit_url?: string;
  cited_by?: string;
  note?: string;
  package?: string;
  version?: string;
  uploaded?: string;
  cpython_tags?: string[];
}

/** harness-v1.6 outcome ladder: how far the run got, read off the stored
 * record (verdict, error_chain, attempts) — never from a model. */
export interface OutcomeLevels {
  /** The chain's first failure was cleared by some attempt. */
  first_error_cleared: boolean;
  /** The `origin` of the attempt that cleared it ("time_machine", "model", a rule name), or null when unexplained. */
  first_error_cleared_by: string | null;
  /** The run got past the environment (dependencies, system libraries, the interpreter, the mirrors). */
  env_resolved: boolean;
  /** The verdict says the repository's command completed. */
  entrypoint_runs: boolean;
  /** harness-v1.7 (R6, D-44): present only when a gated model patch the passing run carried touches a call whose replacement changes a
   * result (torch.lu, linalg.*, solve, a seed, a dtype cast, a loss, ...): the names of those calls. */
  semantic_change?: string[];
  /** harness-v1.7 (R1 d): present only when the run halved the documented command's batch size after a memory kill ("RESOURCE-ADAPTED: --batch_size 256->128"). */
  resource_adapted?: string;
  /** harness-v1.7 (R1 c): what the memory hook changed in a DataLoader ("memory hook: DataLoader num_workers 2->0"). */
  memory_adapted?: string;
  /** harness-v1.7 (R5): the companion pin RERUN replaced ("dependency change: torchvision 0.5.0->0.4.0"). */
  dependency_change?: string;
}

/** One Tavily hit for a blocker's "where to get it" lookup. */
export interface BlockerSourceHit {
  title: string;
  url: string;
}

/** The Tavily lookup for what a human must supply: `sources` is null when the
 * lookup ran but found nothing (or was skipped); `reason` says why. */
export interface BlockerSources {
  query: string;
  sources: BlockerSourceHit[] | null;
  reason: string | null;
}

/** Who can remove a blocker: RERUN's own rules, a model proposal (gated),
 * a human, or the platform. */
export type BlockerFixableBy = "deterministic" | "model" | "human" | "platform";

/** harness-v1.6 blocker report: what is in the way of the repository running,
 * derived from the LAST link of the error chain. Null when nothing blocks
 * (RUNS_* verdicts) or nothing was classified. */
export interface Blocker {
  /** A TaxonomyCode, e.g. "DATA_MISSING". */
  class: string;
  /** The taxonomy family of the class ("Dependencies", "Data", ...), or null. */
  family: string | null;
  phase: string;
  attribution: "REPO" | "ENV" | "SANDBOX_QUOTA" | "PLATFORM" | string;
  /** The link's error line, at most 300 characters. */
  evidence: string;
  fixable_by: BlockerFixableBy | null;
  what_a_human_must_supply: string | null;
  sources: BlockerSources | null;
}

export interface CertificateOut {
  run_id: string;
  verdict: Verdict;
  /** harness-v1.7 (R6): the verdict as printed, "RUNS_AFTER_REPAIR (semantic change)" when D-44 applies; absent on older servers. */
  verdict_label?: string;
  certificate_prose: string;
  full_log: string;
  build_plan: Record<string, unknown>;
  diffs: RepairAttemptDiff[];
  reproduction_passport_hash: string;
  timestamp: string;
  /** Passport bundle version; 1 (or absent) = certificates created before 2026-09-24. */
  bundle_version?: number | null;
  /** The as-is run before RERUN changed anything. */
  baseline?: Baseline | null;
  /** True iff the baseline failed and RERUN's final run completed. */
  recovery?: boolean | null;
  /** v3: proof the uploaded files were the committed tree. */
  tree_integrity?: { status: string; tree_sha?: string; files_checked?: number; mismatched?: string[]; not_in_commit?: string[] } | null;
  corpus_hash?: string | null;
  /** harness-v1.6; absent on certificates served before it. */
  outcome_levels?: OutcomeLevels | null;
  /** harness-v1.6; absent on certificates served before it, null when nothing blocks. */
  blocker?: Blocker | null;
}

export interface Baseline {
  result: "RUNS_CLEAN" | "FAILS" | "NOT_RUN";
  exit_code?: number | null;
  taxonomy_code?: string | null;
  evidence?: string;
  base_image?: string;
  install_commands?: string[];
  execute_command?: string;
}

export interface HealthOut {
  status: string;
  nebius_configured: boolean;
  tavily_configured: boolean;
  demo_mode: boolean;
}

export interface BatchRepoResult {
  name: string;
  repo_url?: string;
  verdict: Verdict;
  taxonomy_code?: string | null;
  attempts_used?: number;
  duration_seconds?: number;
}

export interface BatchResults {
  n: number;
  /** Denominator of recovery_rate: n minus runs that ended in RERUN's own errors. */
  n_measured?: number;
  excluded_our_fault?: number;
  our_fault_breakdown?: Record<string, number>;
  recovery_rate: number;
  repos: BatchRepoResult[];
  runs_clean?: number;
  runs_after_repair?: number;
  blocked?: number;
  indeterminate?: number;
  median_time_to_first_failure_seconds?: number;
  estimated_researcher_hours_saved?: number;
  failure_breakdown?: Record<string, number>;
}

export const api = {
  health: () => request<HealthOut>("/healthz"),
  createRun: (repo_url: string) =>
    request<RunOut>("/runs", { method: "POST", body: JSON.stringify({ repo_url }) }),
  getRun: (id: string) => request<RunOut>(`/runs/${id}`),
  listRuns: () => request<RunListOut>("/runs"),
  executeRun: (id: string) => request<RunOut>(`/runs/${id}/execute`, { method: "POST" }),
  getCertificate: (id: string) => request<CertificateOut>(`/runs/${id}/certificate`),
  getBatchResults: () => request<BatchResults>("/batch/results"),
  streamRunUrl: (id: string) => `${API_BASE}/runs/${id}/stream`,
};

/** One event from `GET /runs/{id}/stream` (§4's named SSE endpoint):
 * either a log line as it's produced, or the terminal `done` event —
 * mirrors exactly the two shapes `backend/app/routers/runs.py::_sse_event`
 * emits. */
export type RunStreamEvent = { line: string } | { done: true; verdict?: Verdict };

/**
 * Opens the live SSE connection for a run and starts it executing on the
 * backend if it hasn't run yet (the route itself starts execution — this
 * is not a passive subscription). Returns a close function; the caller
 * must call it on unmount/completion to stop the underlying EventSource.
 * Uses the native EventSource API rather than a manual fetch+reader since
 * this is a plain unauthenticated GET, which is exactly what EventSource
 * is for.
 *
 * Deliberately closes the connection itself on any error rather than
 * letting EventSource use its default auto-reconnect behavior: a
 * reconnect here means the backend starts executing the *entire pipeline
 * again* (it isn't a passive subscription), so silently retrying would
 * silently re-run — and re-bill — a real reproduction attempt. Also closes
 * itself the moment the `done` event arrives and suppresses the error
 * callback for the `onerror` that otherwise inevitably follows: a normal
 * server-side stream close is indistinguishable, from EventSource's point
 * of view, from a dropped connection.
 */
export function streamRun(id: string, onEvent: (event: RunStreamEvent) => void, onError: () => void): () => void {
  const source = new EventSource(api.streamRunUrl(id));
  let finished = false;
  source.onmessage = (message) => {
    const event = JSON.parse(message.data) as RunStreamEvent;
    if ("done" in event) {
      finished = true;
      source.close();
    }
    onEvent(event);
  };
  source.onerror = () => {
    source.close();
    if (!finished) onError();
  };
  return () => source.close();
}
