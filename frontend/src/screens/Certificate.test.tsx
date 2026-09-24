import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { CertificateOut, RepairAttemptDiff, RunOut } from "../api";

// Only the network layer is replaced; Certificate, RepairAttemptCard and
// DiffView all render for real.
const getRun = vi.fn<(id: string) => Promise<RunOut>>();
const getCertificate = vi.fn<(id: string) => Promise<CertificateOut>>();
vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return { ...actual, api: { ...actual.api, getRun: (id: string) => getRun(id), getCertificate: (id: string) => getCertificate(id) } };
});

import { Certificate } from "./Certificate";

const REJECTED_DIFF = [
  "--- a/train.py",
  "+++ b/train.py",
  "@@ -1,4 +1,3 @@",
  " model = build_model()",
  " fit(model)",
  "-evaluate(model)",
  " print('done')",
].join("\n");

const APPLIED_DIFF = [
  "--- a/requirements.txt",
  "+++ b/requirements.txt",
  "@@ -1 +1 @@",
  "-numpy",
  "+numpy==1.26.4",
].join("\n");

const rejected: RepairAttemptDiff = {
  attempt_number: 1,
  diff_text: REJECTED_DIFF,
  gate_decision: "REJECT",
  gate_violations: [
    { rule: "DELETED_EVAL_CALL", reason: "patch removes the call to 'evaluate' identified during recon", file: "train.py" },
  ],
  exit_code: null,
};

const passed: RepairAttemptDiff = {
  attempt_number: 2,
  diff_text: APPLIED_DIFF,
  gate_decision: "PASS",
  gate_violations: [],
  exit_code: 0,
};

function makeRun(overrides: Partial<RunOut> = {}): RunOut {
  return {
    id: "run-1",
    repo_url: "https://github.com/example/paper",
    commit_sha: "a".repeat(40),
    stage: "done",
    verdict: "BLOCKED",
    taxonomy_code: "DEP_MISSING",
    indeterminate_reason: null,
    attempts_used: 1,
    created_at: "2026-09-23T00:00:00Z",
    updated_at: "2026-09-23T00:00:00Z",
    ...overrides,
  };
}

function makeCert(diffs: RepairAttemptDiff[], overrides: Partial<CertificateOut> = {}): CertificateOut {
  return {
    run_id: "run-1",
    verdict: "BLOCKED",
    certificate_prose: "prose",
    full_log: "log",
    build_plan: {},
    diffs,
    reproduction_passport_hash: "f".repeat(64),
    timestamp: "2026-09-23T00:00:00Z",
    ...overrides,
  };
}

function renderCertificate() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/runs/run-1/certificate"]}>
        <Routes>
          <Route path="/runs/:runId/certificate" element={<Certificate />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Certificate — rejected patches", () => {
  it("never renders a REJECTED patch as applied", async () => {
    getRun.mockResolvedValue(makeRun());
    getCertificate.mockResolvedValue(makeCert([rejected]));
    const { container } = renderCertificate();

    expect(await screen.findByText(/tamper gate REJECTED/i)).toBeTruthy();
    // The violation is shown with its rule and reason.
    expect(screen.getByText("DELETED_EVAL_CALL")).toBeTruthy();
    expect(screen.getByText(/removes the call to 'evaluate'/)).toBeTruthy();
    // The diff is labelled as rejected / never applied.
    expect(screen.getByText(/rejected diff \(never applied\)/i)).toBeTruthy();

    // No "applied" state anywhere.
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/Applied diff/i);
    expect(text).not.toMatch(/tamper gate PASSED/i);
    expect(text).not.toMatch(/Re-execution exit code/i);
    // A rejected patch must never be offered for export.
    expect(screen.queryByRole("button", { name: /Export patch/i })).toBeNull();
  });

  it("keeps a rejected patch out of the applied section when a later patch passes", async () => {
    getRun.mockResolvedValue(makeRun({ verdict: "RUNS_AFTER_REPAIR", taxonomy_code: null, attempts_used: 2 }));
    getCertificate.mockResolvedValue(makeCert([rejected, passed], { verdict: "RUNS_AFTER_REPAIR" }));
    renderCertificate();

    const rejectedCard = (await screen.findByText(/Repair attempt 1 — tamper gate REJECTED/i)).parentElement!;
    const passedCard = screen.getByText(/Repair attempt 2 — tamper gate PASSED/i).parentElement!;

    expect(rejectedCard.textContent).not.toMatch(/Applied diff/i);
    expect(rejectedCard.textContent).toMatch(/never applied/i);
    expect(rejectedCard.textContent).toContain("evaluate(model)");

    expect(passedCard.textContent).toMatch(/Applied diff/i);
    expect(passedCard.textContent).toContain("numpy==1.26.4");
    expect(passedCard.textContent).not.toContain("evaluate(model)");
    expect(screen.getAllByText(/Applied diff/i)).toHaveLength(1);
  });
});

describe("Certificate — INDETERMINATE", () => {
  it("renders the recon reason code via indeterminate_reason", async () => {
    const reason = "ENTRYPOINT_UNCLEAR: no runnable entrypoint discoverable in recon";
    getRun.mockResolvedValue(makeRun({ verdict: "INDETERMINATE", taxonomy_code: null, indeterminate_reason: reason, attempts_used: 0 }));
    getCertificate.mockResolvedValue(makeCert([], { verdict: "INDETERMINATE" }));
    renderCertificate();

    expect(await screen.findByText(reason)).toBeTruthy();
    expect(screen.queryByText(/Repair attempts/i)).toBeNull();
  });
});

describe("Certificate — Environment Delta vs Code Diff", () => {
  const aptChange = {
    op: "apt",
    package: "build-essential",
    version: null,
    git_url: null,
    commit: null,
    justification: "gcc is missing to build regex",
    evidence: "error: command 'gcc' failed",
  };
  const envPass: RepairAttemptDiff = {
    attempt_number: 2,
    diff_text: "",
    gate_decision: "PASS",
    gate_violations: [],
    exit_code: 0,
    env_delta: [aptChange],
  };
  const envReject: RepairAttemptDiff = {
    attempt_number: 1,
    diff_text: "",
    gate_decision: "REJECT",
    gate_violations: [{ rule: "ENV_GIT_UNPINNED", reason: "git source must be pinned to a full 40-hex commit sha" }],
    exit_code: null,
    env_delta: [{ ...aptChange, op: "pip_git", package: "dassl", git_url: "https://github.com/o/r", commit: "main" }],
  };

  it("shows applied env changes and code diffs in separate sections, excluding rejected ones", async () => {
    getRun.mockResolvedValue(makeRun({ verdict: "RUNS_AFTER_REPAIR", taxonomy_code: null, attempts_used: 3 }));
    getCertificate.mockResolvedValue(makeCert([envReject, envPass, passed], { verdict: "RUNS_AFTER_REPAIR" }));
    renderCertificate();

    const envSection = (await screen.findByRole("heading", { name: "Environment Delta" })).parentElement!;
    const codeSection = screen.getByRole("heading", { name: "Code Diff" }).parentElement!;

    expect(envSection.textContent).toContain("apt install build-essential");
    expect(envSection.textContent).toContain("error: command 'gcc' failed");
    // The rejected (unpinned git) change never appears as applied.
    expect(envSection.textContent).not.toContain("dassl");
    expect(codeSection.textContent).toContain("numpy==1.26.4");
    expect(codeSection.textContent).not.toContain("build-essential");

    // ...but it is visible, labelled as rejected, in its own attempt card.
    const rejectedCard = screen.getByText(/Repair attempt 1 — tamper gate REJECTED/i).parentElement!;
    expect(rejectedCard.textContent).toContain("ENV_GIT_UNPINNED");
    expect(rejectedCard.textContent).toMatch(/rejected environment delta \(never applied\)/i);
    expect(screen.getByText(/Applied environment delta/i)).toBeTruthy();
  });

  it("does not count a gate-PASS attempt whose patch failed to apply", async () => {
    const failedApply: RepairAttemptDiff = { ...passed, exit_code: null, stderr_tail: "git apply failed" };
    getRun.mockResolvedValue(makeRun());
    getCertificate.mockResolvedValue(makeCert([failedApply]));
    renderCertificate();

    const codeSection = (await screen.findByRole("heading", { name: "Code Diff" })).parentElement!;
    expect(codeSection.textContent).not.toContain("numpy==1.26.4");
    expect(screen.queryByRole("button", { name: /Export patch/i })).toBeNull();
  });
});

describe("Certificate — cited and verified dependency sources", () => {
  it("lists the Tavily citations and the RERUN-verified git source for the attempt", async () => {
    const sha = "c4d3e9f1a2b3c4d5e6f708192a3b4c5d6e7f8091";
    const attempt: RepairAttemptDiff = {
      attempt_number: 1,
      diff_text: "",
      gate_decision: "PASS",
      gate_violations: [],
      exit_code: 0,
      tavily_sources: [{ title: "Dassl.pytorch", url: "https://github.com/KaiyangZhou/Dassl.pytorch", content: "" }],
      resolved_sources: [
        {
          kind: "git",
          url: "https://github.com/KaiyangZhou/Dassl.pytorch",
          commit: sha,
          committed_at: "2023-07-20",
          commit_url: `https://github.com/KaiyangZhou/Dassl.pytorch/commit/${sha}`,
        },
        { kind: "pypi", url: "javascript:alert(1)", package: "x", version: "1.0", uploaded: "2019-01-01", cpython_tags: [] },
      ],
    };
    getRun.mockResolvedValue(makeRun({ verdict: "RUNS_AFTER_REPAIR", taxonomy_code: null }));
    getCertificate.mockResolvedValue(makeCert([attempt], { verdict: "RUNS_AFTER_REPAIR" }));
    renderCertificate();

    expect(await screen.findByText(/Cited sources \(Tavily\)/i)).toBeTruthy();
    const verified = screen.getByText(/Verified sources \(RERUN\)/i).parentElement!;
    const link = verified.querySelector(`a[href="https://github.com/KaiyangZhou/Dassl.pytorch/commit/${sha}"]`);
    expect(link).toBeTruthy();
    // A non-http(s) URL is rendered as text, never as a link.
    expect(verified.querySelector('a[href^="javascript:"]')).toBeNull();
    expect(verified.textContent).toContain("PyPI x 1.0");
  });
});
