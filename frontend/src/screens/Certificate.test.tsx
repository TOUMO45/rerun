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

describe("Certificate — time machine", () => {
  it("shows the era, its source, the Python choice and the lock in the Environment Delta", async () => {
    const tm: RepairAttemptDiff = {
      attempt_number: 0,
      diff_text: "",
      gate_decision: "PASS",
      gate_violations: [],
      exit_code: 0,
      origin: "time_machine",
      time_machine: {
        era: { date: "2019-03-04", source: "dependency-files", detail: { "requirements.txt": "2019-03-04" } },
        python: { version: "3.7", reason: "newest CPython first released >=180 days before the era date", source: "https://devguide.python.org/versions/" },
        undeclared_imports: ["numpy", "tensorflow"],
        apt_added: ["build-essential"],
        apt_reason: "error: command 'gcc' failed",
        lock: { ok: true, lock: ["numpy==1.16.2", "tensorflow==1.13.1"], inputs: [], not_on_index: [], command: "", error: "" },
      },
    };
    getRun.mockResolvedValue(makeRun({ verdict: "RUNS_AFTER_REPAIR", taxonomy_code: null }));
    getCertificate.mockResolvedValue(makeCert([tm], { verdict: "RUNS_AFTER_REPAIR" }));
    renderCertificate();

    const env = (await screen.findByRole("heading", { name: "Environment Delta" })).parentElement!;
    expect(env.textContent).toContain("2019-03-04 — latest change to dependency files (requirements.txt 2019-03-04)");
    expect(env.textContent).toContain("3.7");
    expect(env.textContent).toContain("tensorflow==1.13.1");
    expect(screen.getByText(/Time machine — era environment, re-execution exit code 0/)).toBeTruthy();
  });

  it("renders a deterministic --no-build-isolation step after the era run (A2b)", async () => {
    const era: RepairAttemptDiff = {
      attempt_number: 0,
      diff_text: "",
      gate_decision: "PASS",
      gate_violations: [],
      exit_code: 1,
      origin: "time_machine",
      time_machine: {
        era: { date: "2024-08-30", source: "dependency-files", detail: { "requirements.txt": "2024-08-30" } },
        python: { version: "3.12", reason: "era", source: "" },
        undeclared_imports: [],
        apt_added: [],
        apt_reason: "",
        lock: { ok: true, lock: ["numpy==2.1.0"], inputs: [], not_on_index: [], command: "", error: "" },
      },
    };
    const step: RepairAttemptDiff = {
      attempt_number: 0,
      diff_text: "",
      gate_decision: "PASS",
      gate_violations: [],
      exit_code: 0,
      origin: "time_machine",
      env_delta: [{ op: "pip_no_build_isolation", package: "dassl", version: null, git_url: null, commit: null, justification: "deterministic", evidence: "ModuleNotFoundError: No module named 'numpy'" }],
      time_machine: { step: "pip_no_build_isolation", package: "dassl", module: "numpy", evidence: "ModuleNotFoundError: No module named 'numpy'" },
    };
    getRun.mockResolvedValue(makeRun({ verdict: "RUNS_AFTER_REPAIR", taxonomy_code: null }));
    getCertificate.mockResolvedValue(makeCert([era, step], { verdict: "RUNS_AFTER_REPAIR" }));
    renderCertificate();

    const env = (await screen.findByRole("heading", { name: "Environment Delta" })).parentElement!;
    expect(env.textContent).toContain("2024-08-30");
    expect(env.textContent).toContain("pip install --no-build-isolation dassl");
    expect(screen.getByText(/Time machine — deterministic step: pip_no_build_isolation dassl, re-execution exit code 0/)).toBeTruthy();
    expect(screen.getByText(/isolated build could not import numpy/)).toBeTruthy();
  });
});

describe("Certificate — baseline vs RERUN (bundle v2)", () => {
  it("shows baseline vs final in execution-only wording and marks a recovery", async () => {
    getRun.mockResolvedValue(makeRun({ verdict: "RUNS_AFTER_REPAIR", taxonomy_code: null }));
    getCertificate.mockResolvedValue(
      makeCert([], {
        verdict: "RUNS_AFTER_REPAIR",
        bundle_version: 2,
        baseline: { result: "FAILS", exit_code: 1, taxonomy_code: "SYS_LIB_MISSING", evidence: "error: command 'gcc' failed" },
        recovery: true,
      }),
    );
    const { container } = renderCertificate();
    const section = (await screen.findByRole("heading", { name: "Baseline vs RERUN" })).parentElement!;
    expect(section.textContent).toContain("As published (baseline): did not run to completion (exit code 1, SYS_LIB_MISSING)");
    expect(section.textContent).toContain("After RERUN: ran to completion");
    expect(section.textContent).toContain("Recovered");
    expect(screen.getByText("Execution Certificate")).toBeTruthy();
    // Nothing on the certificate claims reproduced results.
    const text = (container.textContent ?? "").replace(/Reproduction Passport/g, "");
    expect(text).not.toMatch(/reproduc(es|ed|ible)/i);
  });
});

describe("Certificate — outcome ladder (harness-v1.6)", () => {
  it("renders each rung as reached / not reached and names the origin that cleared the first error", async () => {
    getRun.mockResolvedValue(makeRun());
    getCertificate.mockResolvedValue(
      makeCert([], {
        outcome_levels: { first_error_cleared: true, first_error_cleared_by: "time_machine", env_resolved: true, entrypoint_runs: false },
        blocker: null,
      }),
    );
    renderCertificate();

    const ladder = (await screen.findByRole("heading", { name: "Outcome ladder" })).parentElement!;
    const env = screen.getByTestId("rung-env_resolved");
    const entry = screen.getByTestId("rung-entrypoint_runs");
    const first = screen.getByTestId("rung-first_error_cleared");
    expect(env.getAttribute("data-reached")).toBe("true");
    expect(env.textContent).toMatch(/^reached/);
    expect(env.textContent).toContain("Environment resolved");
    expect(entry.getAttribute("data-reached")).toBe("false");
    expect(entry.textContent).toMatch(/^not reached/);
    expect(entry.textContent).toContain("Entrypoint runs (60 s smoke)");
    expect(first.getAttribute("data-reached")).toBe("true");
    expect(first.textContent).toContain("First error cleared by: time machine");
    // Rungs are shown in order.
    const items = ladder.querySelectorAll("li");
    expect(Array.from(items).map((li) => li.getAttribute("data-testid"))).toEqual([
      "rung-env_resolved",
      "rung-entrypoint_runs",
      "rung-first_error_cleared",
    ]);
    expect(ladder.textContent).toMatch(/count of stored fields/);
    expect(ladder.textContent).toMatch(/600 s sustained check/);
    // Nothing blocks: no blocker card.
    expect(screen.queryByRole("heading", { name: "What blocks it" })).toBeNull();
  });

  it("shows an unexplained origin and all rungs not reached", async () => {
    getRun.mockResolvedValue(makeRun());
    getCertificate.mockResolvedValue(
      makeCert([], {
        outcome_levels: { first_error_cleared: false, first_error_cleared_by: null, env_resolved: false, entrypoint_runs: false },
      }),
    );
    renderCertificate();
    await screen.findByRole("heading", { name: "Outcome ladder" });
    for (const key of ["env_resolved", "entrypoint_runs", "first_error_cleared"]) {
      expect(screen.getByTestId(`rung-${key}`).getAttribute("data-reached")).toBe("false");
    }
    expect(screen.getByTestId("rung-first_error_cleared").textContent).toContain("First error cleared by: —");
  });
});

describe("Certificate — blocker card (harness-v1.6)", () => {
  const blocker = {
    class: "DATA_MISSING",
    family: "Data",
    phase: "TEST",
    attribution: "REPO",
    evidence: "FileNotFoundError: [Errno 2] No such file or directory: 'data/train.csv'",
    fixable_by: "human" as const,
    what_a_human_must_supply: "the dataset the repository expects at data/train.csv, obtained as its README describes",
    sources: null,
  };

  it("renders class, family, phase, attribution, evidence, fixable-by and the human sentence, plus linked sources", async () => {
    getRun.mockResolvedValue(makeRun({ taxonomy_code: "DATA_MISSING" }));
    getCertificate.mockResolvedValue(
      makeCert([], {
        blocker: {
          ...blocker,
          sources: {
            query: "download train.csv dataset paper",
            sources: [
              { title: "Dataset page", url: "https://example.org/dataset" },
              { title: "Evil", url: "javascript:alert(1)" },
            ],
            reason: null,
          },
        },
      }),
    );
    renderCertificate();

    const card = (await screen.findByRole("heading", { name: "What blocks it" })).parentElement!;
    expect(card.textContent).toContain("DATA_MISSING · Data");
    expect(card.textContent).toContain("phase: TEST");
    expect(card.textContent).toContain("attribution: REPO");
    expect(card.querySelector("pre")!.textContent).toBe(blocker.evidence);
    expect(card.textContent).toMatch(/Fixable by\s*human/);
    expect(card.textContent).toContain(`What a human must supply: ${blocker.what_a_human_must_supply}`);
    expect(card.textContent).toContain("Where to get it (Tavily)");
    const link = card.querySelector('a[href="https://example.org/dataset"]')!;
    expect(link).toBeTruthy();
    expect(link.textContent).toContain("Dataset page");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    expect(card.querySelector('a[href^="javascript:"]')).toBeNull();
    expect(card.textContent).toContain("query: download train.csv dataset paper");
  });

  it("shows the reason when the lookup found no sources, and never renders HTML from the strings", async () => {
    getRun.mockResolvedValue(makeRun({ taxonomy_code: "DATA_MISSING" }));
    getCertificate.mockResolvedValue(
      makeCert([], {
        blocker: {
          ...blocker,
          evidence: "<img src=x onerror=alert(1)> missing",
          sources: { query: "download train.csv", sources: null, reason: "Tavily not configured" },
        },
      }),
    );
    renderCertificate();

    const card = (await screen.findByRole("heading", { name: "What blocks it" })).parentElement!;
    expect(card.textContent).toContain("no sources: Tavily not configured");
    expect(card.textContent).toContain("query: download train.csv");
    expect(card.querySelector("a")).toBeNull();
    expect(card.querySelector("img")).toBeNull();
    expect(card.querySelector("pre")!.textContent).toBe("<img src=x onerror=alert(1)> missing");
  });

  it("is absent when blocker is null", async () => {
    getRun.mockResolvedValue(makeRun({ verdict: "RUNS_CLEAN", taxonomy_code: null }));
    getCertificate.mockResolvedValue(
      makeCert([], {
        verdict: "RUNS_CLEAN",
        outcome_levels: { first_error_cleared: false, first_error_cleared_by: null, env_resolved: true, entrypoint_runs: true },
        blocker: null,
      }),
    );
    renderCertificate();
    await screen.findByRole("heading", { name: "Outcome ladder" });
    expect(screen.queryByRole("heading", { name: "What blocks it" })).toBeNull();
  });
});

describe("Certificate — semantic change (harness-v1.7, R6, D-44)", () => {
  it("labels a RUNS_AFTER_REPAIR whose model patch touched a listed call, and names the calls on the ladder", async () => {
    getRun.mockResolvedValue(makeRun({ verdict: "RUNS_AFTER_REPAIR", taxonomy_code: null }));
    getCertificate.mockResolvedValue(
      makeCert([], {
        verdict: "RUNS_AFTER_REPAIR",
        outcome_levels: {
          first_error_cleared: true,
          first_error_cleared_by: "time_machine",
          env_resolved: true,
          entrypoint_runs: true,
          semantic_change: ["torch.lu", "linalg"],
        },
        blocker: null,
      }),
    );
    renderCertificate();
    expect(await screen.findByText("RUNS AFTER REPAIR (SEMANTIC CHANGE)")).toBeTruthy();
    expect(screen.getByTestId("semantic-change").textContent).toContain("torch.lu, linalg");
  });

  it("labels a resource-adapted run and says what changed", async () => {
    getRun.mockResolvedValue(makeRun({ verdict: "RUNS_AFTER_REPAIR", taxonomy_code: null }));
    getCertificate.mockResolvedValue(
      makeCert([], {
        verdict: "RUNS_AFTER_REPAIR",
        outcome_levels: {
          first_error_cleared: true,
          first_error_cleared_by: "time_machine",
          env_resolved: true,
          entrypoint_runs: true,
          resource_adapted: "RESOURCE-ADAPTED: --batch_size 256->128",
        },
        blocker: null,
      }),
    );
    renderCertificate();
    expect(await screen.findByText("RUNS AFTER REPAIR (RESOURCE-ADAPTED)")).toBeTruthy();
    expect(screen.getByTestId("resource-adapted").textContent).toContain("--batch_size 256->128");
  });

  it("labels a memory-hook run and a dependency change, and names both on the ladder", async () => {
    getRun.mockResolvedValue(makeRun({ verdict: "RUNS_AFTER_REPAIR", taxonomy_code: null }));
    getCertificate.mockResolvedValue(
      makeCert([], {
        verdict: "RUNS_AFTER_REPAIR",
        outcome_levels: {
          first_error_cleared: true,
          first_error_cleared_by: "time_machine",
          env_resolved: true,
          entrypoint_runs: true,
          memory_adapted: "memory hook: DataLoader num_workers 2->0",
          dependency_change: "dependency change: torchvision 0.5.0->0.4.0",
        },
        blocker: null,
      }),
    );
    renderCertificate();
    expect(await screen.findByText("RUNS AFTER REPAIR (MEMORY HOOK; DEPENDENCY CHANGE)")).toBeTruthy();
    expect(screen.getByTestId("memory-adapted").textContent).toContain("num_workers 2->0");
    expect(screen.getByTestId("dependency-change").textContent).toContain("torchvision 0.5.0->0.4.0");
  });

  it("keeps the plain label when no listed call was touched", async () => {
    getRun.mockResolvedValue(makeRun({ verdict: "RUNS_AFTER_REPAIR", taxonomy_code: null }));
    getCertificate.mockResolvedValue(
      makeCert([], {
        verdict: "RUNS_AFTER_REPAIR",
        outcome_levels: { first_error_cleared: true, first_error_cleared_by: "model", env_resolved: true, entrypoint_runs: true },
        blocker: null,
      }),
    );
    renderCertificate();
    expect(await screen.findByText("RUNS AFTER REPAIR")).toBeTruthy();
    expect(screen.queryByTestId("semantic-change")).toBeNull();
  });
});

describe("Certificate — certificates served before harness-v1.6", () => {
  it("renders without the ladder or the blocker card when both fields are absent", async () => {
    getRun.mockResolvedValue(makeRun());
    getCertificate.mockResolvedValue(makeCert([rejected]));
    renderCertificate();

    expect(await screen.findByText("Execution Certificate")).toBeTruthy();
    expect(screen.getByText(/tamper gate REJECTED/i)).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Outcome ladder" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "What blocks it" })).toBeNull();
  });
});
