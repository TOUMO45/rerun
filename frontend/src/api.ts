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
  | "TIMEOUT";

export interface RunOut {
  id: string;
  repo_url: string;
  commit_sha: string | null;
  stage: string;
  verdict: Verdict | null;
  taxonomy_code: string | null;
  indeterminate_reason: string | null;
  attempts_used: number;
  created_at: string;
  updated_at: string;
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
  time_machine?: TimeMachineRecord | null;
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

export interface CertificateOut {
  run_id: string;
  verdict: Verdict;
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
