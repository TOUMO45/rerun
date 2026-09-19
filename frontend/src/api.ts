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

export interface RepairAttemptDiff {
  attempt_number: number;
  diff_text: string;
  gate_decision: "PASS" | "REJECT" | "DECLINED";
  gate_violations: { rule: string; reason: string; file?: string }[];
  exit_code: number | null;
  stdout_tail?: string;
  stderr_tail?: string;
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
};
