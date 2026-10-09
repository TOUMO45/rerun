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

describe("BatchLab headline (flag-mode pass: read from figures.json)", () => {
  const row = (label: string, n: number, refused: number, adopted: number, flagged: number, by: Record<string, number>) => ({ label, n, refused, adopted, flagged, refused_by_layer: by });
  const HEADLINE = {
    source: "reports/v1.9/figures.json",
    ran: { count: 3, of: 26, tag: "DERIVED", parts: [{ set: "TEST", count: 1, of: 8 }, { set: "TEST-B", count: 1, of: 8 }, { set: "TEST-C", count: 1, of: 10 }], measure: "ran" },
    diagnosis: { count: 7, of: 9, strict: { count: 6, of: 9, pct: 67, source: "reports/test-c/TEST_C_RESULT.md" }, set: "TEST-C", tag: "DERIVED", source: "reports/test-c/TEST_C_RESULT.md" },
    benchmark: {
      source: "benchmark/README.md", command: "python benchmark/score.py --all", tag: "DERIVED",
      sets: { planted: 337, independent: 208, independent_measured_cheats: 144, independent_dropped: 22 },
      status: "Both sets are development material now: a new independent set is needed to measure again",
      tables: [
        { name: "planted_heldout.pipeline_v1.9.0", title: "Planted set, held-out half: the full pipeline (harness-v1.9.0)",
          note: "Table only, no summary sentence: the adjudicator refused all 31 honest controls that passed the run here.",
          rows: [row("cheats, all", 115, 115, 0, 0, { adjudicator: 63, gate: 35, run: 17 }), row("honest controls (refused = false refusals)", 53, 53, 0, 0, { adjudicator: 31, run: 22 })] },
        { name: "independent.flag_mode.derived", title: "Independent set: the flag mode",
          note: "Derived from committed records, not measured by a run of the flag mode; this use of the checks was chosen after the results were seen.",
          rows: [row("cheats, all", 144, 127, 0, 17, { adjudicator: 121, audit: 2, gate: 4 }), row("cheats aimed at failing repositories", 50, 36, 0, 14, { adjudicator: 32 })] },
      ],
    },
    counterfactual: {
      fresh: { ungated_at_least: 6, of: 26, certified: 5, after_audits: 3 }, dev: { ungated_at_least: 15, of: 40, certified: 12, certified_after_erratum: 11, erratum: "E-3: the M-FAC run ran on a changed algorithm" },
      removed_by_audit: 2, removed_that_were_fakes: 0, fakes_that_exited_0: 9, fakes_passed_by_the_gate: 9, fakes_refused_by_the_adjudicator: 9, gate_faking_rule_rejections: 24, of_which_honest: 24,
      tag: "DERIVED", source: "reports/v1.9/counterfactual/RESULT.md",
    },
    limits: ["Anti-cheat is not a headline claim: harness-v1.9.0 adopted 14 of the 50 independent cheats aimed at repositories whose run really fails (28%), above the 25% line."],
  };

  it("leads with the run count and the diagnosis, then the benchmark's per-layer tables, the counterfactual and the limits", async () => {
    getPreregistered.mockResolvedValue({ ...RESULTS, headline: HEADLINE });
    renderLab();
    const headline = await screen.findByTestId("headline");
    expect(headline.textContent).toContain("3 of 26");
    expect(headline.textContent).toContain("TEST 1/8 · TEST-B 1/8 · TEST-C 1/10 · ran ≠ reproduced");
    expect(headline.textContent).toContain("7 of 9");
    expect(headline.textContent).toContain("strict: 6 of 9 (67%)");
    const text = headline.textContent ?? "";
    expect(text.indexOf("3 of 26")).toBeLessThan(text.indexOf("7 of 9"));
    expect(text.indexOf("7 of 9")).toBeLessThan(text.indexOf("The cheat benchmark"));
    expect(text.indexOf("The cheat benchmark")).toBeLessThan(text.indexOf("Limits"));
    const bench = within(headline).getByTestId("benchmark");
    expect(bench.textContent).toContain("python benchmark/score.py --all");
    expect(bench.textContent).toContain("development material");
    const t1 = within(bench).getByTestId("benchmark-planted_heldout.pipeline_v1.9.0");
    expect(t1.textContent).toContain("refused all 31 honest controls");
    expect(t1.textContent).toContain("adjudicator 63, gate 35, run 17");
    expect(t1.textContent).not.toContain("REVIEW_REQUIRED");
    const flag = within(bench).getByTestId("benchmark-independent.flag_mode.derived");
    expect(flag.textContent).toContain("adopted with REVIEW_REQUIRED");
    expect(flag.textContent).toContain("Derived from committed records");
    const cf = within(headline).getByTestId("counterfactual");
    expect(cf.textContent).toContain("at least 6 of 26");
    expect(cf.textContent).toContain("certified 3 after the published audits (5 as recorded)");
    expect(cf.textContent).toContain("runs the audits removed were not fakes (0 were)");
    expect(cf.textContent).toContain("DEV: ≥15 vs 11 of 40 (12 as recorded");
    expect(within(headline).getByTestId("limits").textContent).toContain("Anti-cheat is not a headline claim");
  });

  it("shows no headline when the server sends none", async () => {
    getPreregistered.mockResolvedValue({ ...RESULTS, headline: null });
    renderLab();
    await screen.findByRole("heading", { name: "TEST-C" });
    expect(screen.queryByTestId("headline")).toBeNull();
  });
});
