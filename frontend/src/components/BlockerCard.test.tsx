import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { Blocker } from "../api";
import { BlockerCard } from "./BlockerCard";

afterEach(cleanup);

const BASE: Blocker = {
  class: "SYS_LIB_MISSING",
  family: "Environment",
  phase: "repo_run",
  attribution: "ENV",
  evidence: "subprocess.CalledProcessError: Command '['which', 'g++']' returned non-zero exit status 1.",
  fixable_by: "deterministic",
  what_a_human_must_supply: "nothing yet: RERUN's apt step added `build-essential`, and the run after the step did not finish",
  sources: null,
};

describe("BlockerCard (harness-v1.8 diagnosis)", () => {
  it("shows the cause, that it came from the record's evidence, the verbatim line and the next action", () => {
    render(
      <BlockerCard
        blocker={{
          ...BASE,
          cause: "SYSTEM_PACKAGE_ADDED_UNTESTED",
          diagnosis: "evidence",
          error_line: "subprocess.CalledProcessError: Command '['which', 'g++']' returned non-zero exit status 1.",
          next_action: "run the documented command again with `build-essential` installed; if the record ends on a spend cap, with a larger per-entry budget",
        }}
      />,
    );
    expect(screen.getByText("cause: SYSTEM_PACKAGE_ADDED_UNTESTED")).toBeTruthy();
    expect(screen.getByText(/diagnosis: from this record's evidence/)).toBeTruthy();
    expect(screen.getByText(/Command '\['which', 'g\+\+'\]' returned non-zero exit status 1/)).toBeTruthy();
    expect(screen.getByTestId("next-action").textContent).toContain("build-essential");
  });

  it("says a class default is a default, and does not repeat the same sentence as a next action", () => {
    const same = "the dataset the repository expects at saved_logits/x.p, obtained as its README describes";
    render(
      <BlockerCard
        blocker={{ ...BASE, class: "DATA_MISSING", family: "Data", cause: "DATA_MISSING", diagnosis: "class_default", what_a_human_must_supply: same, next_action: same }}
      />,
    );
    expect(screen.getByText(/class default \(no rule matched this record\)/)).toBeTruthy();
    expect(screen.queryByTestId("next-action")).toBeNull(); // identical to "What a human must supply": shown once
    expect(screen.queryByText(/^cause:/)).toBeNull(); // cause equals the class: no second tag
  });

  it("states that the spend cap stopped the run and that this is not a verdict on the repository", () => {
    render(<BlockerCard blocker={{ ...BASE, diagnosis: "evidence", stopped_by: { cause: "COST_CAP", line: "a sandbox operation reached its budget-derived limit of 87s" } }} />);
    const note = screen.getByTestId("stopped-by").textContent ?? "";
    expect(note).toContain("spend cap stopped the run");
    expect(note).toContain("87s");
    expect(note).toContain("not a verdict on the repository");
  });

  it("still renders a report an older server wrote (no harness-v1.8 fields)", () => {
    render(<BlockerCard blocker={BASE} />);
    expect(screen.getByText("What blocks it")).toBeTruthy();
    expect(screen.getByText(/which', 'g\+\+/)).toBeTruthy();
    expect(screen.queryByText(/diagnosis:/)).toBeNull();
    expect(screen.queryByTestId("stopped-by")).toBeNull();
  });
});
