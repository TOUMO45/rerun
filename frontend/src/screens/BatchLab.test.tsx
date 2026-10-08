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

describe("BatchLab headline (harness-v1.9)", () => {
  const family = (name: string, n: number, rejected: number, by: number) => ({ name, n, rejected, by_semantic_rule: by });
  const run = (rejectedCheats: number, rejectedControls: number) => ({
    families: { F1: family("swallowed exception", 31, 21, 21), F3: family("skipped missing input", 11, rejectedCheats, rejectedCheats) },
    cheats: { n: 115, rejected: 37 + rejectedCheats, rate: null }, controls: { n: 53, rejected: rejectedControls, rate: null }, tamper_gate_blob: null, head: null,
  });
  const HEADLINE = {
    ran: { count: 3, of: 26, tag: "DERIVED", parts: [{ set: "TEST", count: 1, of: 8 }, { set: "TEST-B", count: 1, of: 8 }, { set: "TEST-C", count: 1, of: 10 }], measure: "ran" },
    diagnosis: { count: 7, of: 9, strict: { count: 6, of: 9, source: "reports/test-c/TEST_C_RESULT.md" }, set: "TEST-C", tag: "DERIVED", source: "reports/test-c/TEST_C_RESULT.md" },
    counterfactual: {
      fresh: { ungated_at_least: 6, of: 26, certified: 5, after_audits: 3 }, dev: { ungated_at_least: 15, of: 40, certified: 12 }, fakes_that_exited_0: 9, fakes_passed_by_the_gate: 9,
      fakes_refused_by_the_adjudicator: 9, gate_faking_rule_rejections: 24, of_which_honest: 24, adopted_outside_both_classes: 1, tag: "DERIVED", source: "reports/v1.9/counterfactual/RESULT.md",
    },
    planted: { half: "held-out", before: run(0, 6), after: null, tag: "DERIVED", source: "reports/v1.9/planted/RESULT.md", note: "Planted patches, labelled by construction." },
  };

  it("leads with the run count, the diagnosis rate with its strict figure, the counterfactual and the planted benchmark; the 'after' column says not run yet when absent", async () => {
    getPreregistered.mockResolvedValue({ ...RESULTS, headline: HEADLINE });
    renderLab();
    const headline = await screen.findByTestId("headline");
    expect(headline.textContent).toContain("3 of 26");
    expect(headline.textContent).toContain("TEST 1/8 · TEST-B 1/8 · TEST-C 1/10 · ran ≠ reproduced");
    expect(headline.textContent).toContain("7 of 9");
    expect(headline.textContent).toContain("strict: 6 of 9 (67%)");
    expect(headline.textContent).toContain("≥6 vs 5");
    expect(headline.textContent).toContain("9 of 9");
    expect(headline.textContent).toContain("24 of 24 were honest patches");
    const table = within(headline).getByTestId("planted-table");
    expect(table.textContent).toContain("not run yet");
    expect(table.textContent).toContain("honest controls rejected (false rejects)");
  });

  it("fills the after column when the held-out re-run exists and shows no headline when the server sends none", async () => {
    getPreregistered.mockResolvedValue({ ...RESULTS, headline: { ...HEADLINE, planted: { ...HEADLINE.planted, after: run(11, 0) } } });
    const { unmount } = renderLab();
    const table = await screen.findByTestId("planted-table");
    expect(table.textContent).not.toContain("not run yet");
    expect(table.textContent).toContain("11 (11)");
    unmount();
    getPreregistered.mockResolvedValue({ ...RESULTS, headline: null });
    renderLab();
    await screen.findByRole("heading", { name: "TEST-C" });
    expect(screen.queryByTestId("headline")).toBeNull();
  });
});
