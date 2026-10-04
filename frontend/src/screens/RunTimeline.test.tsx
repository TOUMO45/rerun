import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { HealthOut, RunOut } from "../api";

const getRun = vi.fn<(id: string) => Promise<RunOut>>();
const health = vi.fn<() => Promise<HealthOut>>();
vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return { ...actual, api: { ...actual.api, getRun: (id: string) => getRun(id), health: () => health() } };
});

import { RunTimeline } from "./RunTimeline";

const PENDING: RunOut = {
  id: "run-1",
  repo_url: "https://github.com/example/paper",
  commit_sha: "a".repeat(40),
  stage: "RECON_PENDING",
  verdict: null,
  taxonomy_code: null,
  indeterminate_reason: null,
  attempts_used: 0,
  demo_source: null,
  created_at: "2026-10-03T00:00:00Z",
  updated_at: "2026-10-03T00:00:00Z",
};

function renderRun() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/runs/run-1"]}>
        <Routes>
          <Route path="/runs/:runId" element={<RunTimeline />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("RunTimeline in demo mode", () => {
  it("disables the execute button and shows the banner when /healthz reports demo_mode", async () => {
    getRun.mockResolvedValue(PENDING);
    health.mockResolvedValue({ status: "ok", nebius_configured: false, tavily_configured: false, demo_mode: true });
    renderRun();
    const button = (await screen.findByRole("button", { name: "Start execution run" })) as HTMLButtonElement;
    expect(await screen.findByRole("status")).toBeTruthy();
    expect(button.disabled).toBe(true);
    expect(screen.getByText(/Execution is off in demo mode/)).toBeTruthy();
  });

  it("keeps the execute button enabled outside demo mode", async () => {
    getRun.mockResolvedValue(PENDING);
    health.mockResolvedValue({ status: "ok", nebius_configured: true, tavily_configured: false, demo_mode: false });
    renderRun();
    const button = (await screen.findByRole("button", { name: "Start execution run" })) as HTMLButtonElement;
    expect(await screen.findByText("Intake complete. Ready to build the environment and execute.")).toBeTruthy();
    expect(button.disabled).toBe(false);
    expect(screen.queryByRole("status")).toBeNull();
  });
});
