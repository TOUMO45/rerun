import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { PreregisteredResults, PreregisteredSet } from "../api";

// Only the network layer is replaced; BatchLab, its set cards and VerdictBadge render for real.
const getPreregistered = vi.fn<() => Promise<PreregisteredResults>>();
vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return { ...actual, api: { ...actual.api, getPreregistered: () => getPreregistered() } };
});

import { BatchLab } from "./BatchLab";

afterEach(cleanup);

function set(over: Partial<PreregisteredSet>): PreregisteredSet {
  return {
    key: "x", title: "X", harness: "harness-v1.8.0", what: "w", measure: "ran their documented command", count: 1, of: 10, tag: "DERIVED", registered: true,
    source: "reports/x.md", spend_usd: 31.4, spend_tag: "API-REPORTED", rows: [], metrics: null, diagnosis: null, ...over,
  };
}

const RESULTS: PreregisteredResults = {
  note: "Counts over a handful of entries, one run each: not rates.",
  sets: [
    set({
      key: "test_c", title: "TEST-C", count: 1, of: 10,
      diagnosis: { count: 7, of: 9, tag: "DERIVED", measure: "non-running entries whose stored diagnosis is actionable under the committed rubric", source: "reports/test-c/TEST_C_RESULT.md", note: "Most of it is the per-class sentences." },
      metrics: {
        median_seconds_to_diagnosis: 575.49, median_api_reported_cost_usd_to_diagnosis: 1.4922, measured_over: { seconds: 9, cost: 9 }, non_running: 9, diagnosed: 9,
        recovery: { as_published_failed: 9, recovered_after_repair: 1 }, cost_tag: "API-REPORTED (with the estimate of killed steps; not billed)", source: "reports/dev/v18/set_metrics.json",
      },
    }),
    set({ key: "test_b", title: "TEST-B", harness: "harness-v1.7.2", count: 1, of: 8, metrics: null, diagnosis: null }),
  ],
};

function renderLab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <BatchLab />
    </QueryClientProvider>,
  );
}

describe("BatchLab (harness-v1.8 measurements)", () => {
  it("shows the run count and the actionable-diagnosis count side by side, labelled never merged", async () => {
    getPreregistered.mockResolvedValue(RESULTS);
    renderLab();
    const card = (await screen.findByRole("heading", { name: "TEST-C" })).closest("section") as HTMLElement;
    expect(within(card).getByText("ran their documented command")).toBeTruthy();
    const figure = within(card).getByTestId("diagnosis-figure");
    expect(figure.textContent).toContain("7");
    expect(figure.textContent).toContain("of 9");
    expect(figure.textContent).toMatch(/beside the count above, never merged with it/);
    expect(figure.textContent).toContain("Most of it is the per-class sentences");
  });

  it("shows the measured medians, with their source and that the cost is API-reported, not billed", async () => {
    getPreregistered.mockResolvedValue(RESULTS);
    renderLab();
    const strip = await screen.findByTestId("measurements");
    expect(strip.textContent).toContain("median time to a diagnosis");
    expect(strip.textContent).toContain("10 min"); // 575 s
    expect(strip.textContent).toContain("$1.49");
    expect(strip.textContent).toContain("9 of 9");
    expect(strip.textContent).toContain("1 of 9 failed as published");
    expect(strip.textContent).toContain("reports/dev/v18/set_metrics.json");
    expect(strip.textContent).toContain("not billed");
  });

  it("shows no measurement strip and no diagnosis figure for a set that carries none, and never an hours figure", async () => {
    getPreregistered.mockResolvedValue(RESULTS);
    renderLab();
    const card = (await screen.findByRole("heading", { name: "TEST-B" })).closest("section") as HTMLElement;
    expect(within(card).queryByTestId("measurements")).toBeNull();
    expect(within(card).queryByTestId("diagnosis-figure")).toBeNull();
    expect(document.body.textContent).not.toMatch(/hours saved|researcher hours/i);
  });
});
