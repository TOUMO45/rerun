import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { HealthOut, RunListOut, Scene } from "../api";

// Only the network layer is replaced; Gallery, Intake, Shell and VerdictBadge render for real.
const listRuns = vi.fn<() => Promise<RunListOut>>();
const health = vi.fn<() => Promise<HealthOut>>();
const listScenes = vi.fn<() => Promise<{ scenes: Scene[] }>>(() => Promise.resolve({ scenes: [] }));
vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return { ...actual, api: { ...actual.api, listRuns: () => listRuns(), health: () => health(), listScenes: () => listScenes() } };
});

import { Gallery, parseDemoSource, repoName } from "./Gallery";
import { Intake } from "./Intake";
import { Shell } from "../components/Shell";

const LIST: RunListOut = {
  total: 3,
  limit: 200,
  offset: 0,
  runs: [
    {
      id: "demo-harness-v1.5.1-dev-15",
      repo_url: "https://github.com/YuliaRubanova/latent_ode",
      commit_sha: "c0682d4f52b806fb88d965755892eadd9783f936",
      status: "DONE",
      verdict: "RUNS_AFTER_REPAIR",
      taxonomy_code: "DEP_YANKED",
      demo_source: "runs/corpus_v2_batch/harness-v1.5.1/dev/15_YuliaRubanova__latent_ode.json",
      created_at: "2026-10-03T16:23:47Z",
    },
    {
      id: "demo-harness-v1.4.3-gate-03",
      repo_url: "https://github.com/autumn9999/vmtl",
      commit_sha: "e20022da842cd44c3e9566ee76c2f888e08b8e80",
      status: "DONE",
      verdict: "BLOCKED",
      taxonomy_code: "DATA_MISSING",
      demo_source: "runs/corpus_v2_batch/harness-v1.4.3/gate/03_autumn9999__vmtl.json",
      created_at: "2026-10-02T12:46:48Z",
    },
    {
      id: "live-1",
      repo_url: "https://github.com/example/paper",
      commit_sha: null,
      status: "RECON_PENDING",
      verdict: null,
      taxonomy_code: null,
      demo_source: null,
      created_at: "2026-10-03T17:00:00Z",
    },
  ],
};

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Shell>
          <Routes>
            <Route path="/" element={<Intake />} />
            <Route path="/gallery" element={<Gallery />} />
          </Routes>
        </Shell>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const healthy = (demo_mode: boolean): HealthOut => ({ status: "ok", nebius_configured: false, tavily_configured: false, demo_mode });

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("parseDemoSource / repoName", () => {
  it("reads tag, arm, entry and name off a record path and rejects anything else", () => {
    expect(parseDemoSource("runs/corpus_v2_batch/harness-v1.5.1/dev/15_YuliaRubanova__latent_ode.json")).toEqual({
      tag: "harness-v1.5.1",
      arm: "dev",
      entry: "15",
      name: "YuliaRubanova__latent_ode",
    });
    expect(parseDemoSource(null)).toBeNull();
    expect(parseDemoSource("runs/corpus_v2_batch/harness-v1.5.1/dev/round_summary.json")).toBeNull();
    expect(repoName("https://github.com/autumn9999/vmtl")).toBe("autumn9999/vmtl");
    expect(repoName("https://github.com/autumn9999/vmtl.git/")).toBe("autumn9999/vmtl");
  });
});

describe("Gallery", () => {
  it("lists the seeded audits with entry, harness tag, verdict, blocker class and a certificate link", async () => {
    listRuns.mockResolvedValue(LIST);
    health.mockResolvedValue(healthy(true));
    renderAt("/gallery");

    expect(await screen.findByText("Recorded audits (2)")).toBeTruthy();
    const rows = screen.getAllByTestId("gallery-row");
    expect(rows).toHaveLength(3);

    const latentOde = rows.find((r) => within(r).queryByText("YuliaRubanova/latent_ode"))!;
    expect(within(latentOde).getByText("#15")).toBeTruthy();
    expect(within(latentOde).getByText("harness-v1.5.1")).toBeTruthy();
    expect(within(latentOde).getByText("RUNS AFTER REPAIR")).toBeTruthy();
    expect(within(latentOde).getByText("—")).toBeTruthy(); // a RUNS_* verdict has no blocker class
    expect(within(latentOde).getByRole("link", { name: /Certificate/ }).getAttribute("href")).toBe(
      "/runs/demo-harness-v1.5.1-dev-15/certificate",
    );

    const vmtl = rows.find((r) => within(r).queryByText("autumn9999/vmtl"))!;
    expect(within(vmtl).getByText("#03")).toBeTruthy();
    expect(within(vmtl).getByText("harness-v1.4.3")).toBeTruthy();
    expect(within(vmtl).getByText("BLOCKED")).toBeTruthy();
    expect(within(vmtl).getByText("DATA_MISSING")).toBeTruthy();

    // a live, unexecuted run is listed separately and links to its timeline instead
    expect(screen.getByText("Live runs (1)")).toBeTruthy();
    const live = rows.find((r) => within(r).queryByText("example/paper"))!;
    expect(within(live).getByText("recon_pending")).toBeTruthy();
    expect(within(live).getByRole("link", { name: /Open/ }).getAttribute("href")).toBe("/runs/live-1");

    // demo mode shows the banner here too; the Shell nav has the Gallery entry
    expect(await screen.findByRole("status")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Gallery" }).getAttribute("href")).toBe("/gallery");
  });

  it("shows the harness-v1.7 labels of a recorded audit from the server's verdict_label", async () => {
    const labelled = {
      ...LIST,
      runs: LIST.runs.map((r) =>
        r.verdict === "RUNS_AFTER_REPAIR" ? { ...r, verdict_label: "RUNS_AFTER_REPAIR (semantic change; RESOURCE-ADAPTED: --batch_size 256->128)" } : r,
      ),
    };
    listRuns.mockResolvedValue(labelled);
    health.mockResolvedValue(healthy(true));
    renderAt("/gallery");
    expect(await screen.findByText("RUNS AFTER REPAIR (SEMANTIC CHANGE; RESOURCE-ADAPTED)")).toBeTruthy();
  });

  it("says so when there are no runs and shows no banner outside demo mode", async () => {
    listRuns.mockResolvedValue({ runs: [], total: 0, limit: 200, offset: 0 });
    health.mockResolvedValue(healthy(false));
    renderAt("/gallery");
    expect(await screen.findByText("No runs yet.")).toBeTruthy();
    expect(screen.queryByRole("status")).toBeNull();
  });
});

describe("Gallery scenes (harness-v1.9, task 5)", () => {
  it("shows every scene marked REPLAY, with the claims the server computed and a link to the certificate", async () => {
    listRuns.mockResolvedValue(LIST);
    health.mockResolvedValue(healthy(true));
    listScenes.mockResolvedValue({
      scenes: [
        {
          id: "latent_ode", order: 1, mode: "REPLAY", title: "A dependency the paper's era cannot install", run_id: "demo-harness-v1.7.1-dev-15",
          record: "runs/corpus_v2_batch/harness-v1.7.1/dev/15_YuliaRubanova__latent_ode.json",
          claims: [{ text: "The adjudicator adopts candidate 1.", basis: "result.attempts[].chosen" }], note: null,
        },
        {
          id: "spline-calibration", order: 2, mode: "REPLAY", title: "Candidates that reach exit 0 by skipping missing inputs, none adopted",
          run_id: "demo-harness-v1.8.0-treatment-01", record: "runs/corpus_v4_batch/harness-v1.8.0/treatment/01_kartikgupta-at-anu__spline-calibration.json",
          claims: [{ text: "6 candidates pass the tamper gate and reach exit 0 by skipping every missing file.", basis: "result.attempts" }],
          note: "Not from the record: harness-v1.9 adds a tamper-gate rule.",
        },
      ],
    });
    renderAt("/gallery");
    const cards = await screen.findAllByTestId("scene-card");
    expect(cards).toHaveLength(2);
    for (const card of cards) expect(within(card).getByTestId("mode-badge").textContent).toBe("REPLAY");
    expect(within(cards[1]).getByText(/6 candidates pass the tamper gate/)).toBeTruthy();
    expect(within(cards[1]).getByText(/Not from the record/)).toBeTruthy();
    expect(within(cards[1]).getByRole("link", { name: /Certificate/ }).getAttribute("href")).toBe("/runs/demo-harness-v1.8.0-treatment-01/certificate");
  });

  it("reads a corpus-v4 record path too", () => {
    expect(parseDemoSource("runs/corpus_v4_batch/harness-v1.8.0/treatment/01_kartikgupta-at-anu__spline-calibration.json")?.entry).toBe("01");
  });
});

describe("Intake in demo mode", () => {
  it("shows the demo banner when /healthz reports demo_mode", async () => {
    health.mockResolvedValue(healthy(true));
    renderAt("/");
    const banner = await screen.findByRole("status");
    expect(banner.textContent).toContain("Demo:");
    expect(banner.textContent).toContain("replaying recorded audits; live runs are off");
    // the nav entry and the banner's own pointer both lead to the gallery
    expect(screen.getAllByRole("link", { name: "Gallery" }).map((a) => a.getAttribute("href"))).toEqual(["/gallery", "/gallery"]);
  });

  it("shows no banner when demo_mode is false", async () => {
    health.mockResolvedValue(healthy(false));
    renderAt("/");
    expect(await screen.findByText("Repository URL")).toBeTruthy();
    expect(screen.queryByRole("status")).toBeNull();
  });
});
