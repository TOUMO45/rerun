"""The defect register D-1..D-28 as data, each row with quoted sources from the committed reports.

Status rule (shown on the dashboard):
  fixed-and-gated    the fix-map status is "fixed" with no open remainder AND a committed gate (or seal) report line states the
                     fix was observed working live. It does not mean the gate passed: neither exploratory gate did.
  fixed-unvalidated  a fix or correction exists, but no committed gate line shows it working (offline tests, seal only, or
                     a documentation correction).
  open               no fix, a fix the fix map itself calls partial, or a defect that still shows in practice.
Every quote is checked against the committed file when REPLAY is built; a missing quote stops the build.
"""

from __future__ import annotations

DEFECTS = "reports/corpus-v2.1/candidate_v1.3.3_defects.md"
FIXMAP = "reports/corpus-v2.1/v1.3.3/DEFECT_FIX_MAP.md"
G133 = "reports/corpus-v2.1/v1.3.3/smoke_gate/SMOKE_GATE_REPORT.md"
G134 = "reports/corpus-v2.1/v1.3.3/smoke_gate/SMOKE_GATE_REPORT_v1.3.4.md"
METHODOLOGY = "METHODOLOGY.md"
D24_TEST = "backend/tests/test_d24_build_essential.py"

FIXED_GATED, FIXED_UNVALIDATED, OPEN = "fixed-and-gated", "fixed-unvalidated", "open"
STATUSES = (FIXED_GATED, FIXED_UNVALIDATED, OPEN)
STATUS_RULE = {
    FIXED_GATED: "The fix map calls it fixed with no open remainder, and a committed gate or seal report line states the fix was observed "
                 "working live. It does not mean the gate passed: neither exploratory gate did.",
    FIXED_UNVALIDATED: "A fix or correction exists, but no committed gate line shows it working (offline tests, seal only, or a documentation correction).",
    OPEN: "No fix, a fix the fix map itself calls partial, or a defect that still shows in practice.",
}
NOT_FIXED_134 = "## Found by the v1.3.4 smoke gate (2026-09-30; `v1.3.3/smoke_gate/SMOKE_GATE_REPORT_v1.3.4.md`; not fixed: stop rule)"
PHASE_D = "## Found by the Phase D record inventory (2026-10-01; offline, from the committed records; documented only, not fixed)"


def _row(defect: str, title: str, status: str, registered: tuple[str, str], basis: list[tuple[str, str]], note: str = "") -> dict:
    return {"id": defect, "title": title, "status": status, "note": note,
            "registered": {"path": registered[0], "quote": registered[1]},
            "basis": [{"path": p, "quote": q} for p, q in basis]}


REGISTER: list[dict] = [
    _row("D-1", "Repairer patches never applied", OPEN, (DEFECTS, "## D-1  Repairer emits invalid unified diffs"),
         [(FIXMAP, "target 80 % NOT met offline"), (G133, "**PASS**: 2 applied of 4 proposed")],
         "Partly fixed: patches now apply in both gates, the offline target was not met, and no applied patch produced a recovery."),
    _row("D-2", "Tamper gate passed a diff with no hunks", FIXED_UNVALIDATED, (DEFECTS, "## D-2  Tamper gate PASSes a diff with zero hunks"),
         [(FIXMAP, "| `test_the_gate_rejects_a_diff_with_headers_and_no_hunks` | fixed |")], "Offline test only."),
    _row("D-3", "Root cause bundle of one entry: empty repair, identical search, timeout as pipeline error", FIXED_UNVALIDATED,
         (DEFECTS, "## D-3  Entry 1: root cause of"),
         [(FIXMAP, "test_a_timeout_in_a_repair_reexecution_is_TIMEOUT_not_PIPELINE_ERROR` | fixed |")], "Offline test only."),
    _row("D-4", "Search query did not vary with attempt history", FIXED_GATED, (DEFECTS, "## D-4  Search query does not vary with attempt history"),
         [(FIXMAP, "fixed (whether the repairer will cite in practice is measured at the smoke gate, criterion c)"),
          (G133, "The queries carried error, framework and Python version as designed and returned results")],
         "The query fix worked live; the repairer still does not cite (see the citation defect, open)."),
    _row("D-5", "One unlockable name discarded the whole era environment", FIXED_GATED,
         (DEFECTS, "## D-5  An era lock that fails for one name discards the whole era environment"),
         [(FIXMAP, "| `tests/test_v133_dependencies.py` (real uv errors of entries 1, 8, 20) | fixed |"),
          (G133, "the fallback batch pip after a failed lock")]),
    _row("D-6", "A repository's own compiled module planned as a dependency", OPEN, (DEFECTS, "## D-6  Entry 19 planning gap"),
         [(FIXMAP, "**partly:** no longer mistaken for a package")], "Partly fixed; the documented build step is still not planned or run."),
    _row("D-7", "Per-entry spend ceiling was not hard", OPEN, (DEFECTS, "**D-7 Per-entry $2 ceiling is not hard.**"),
         [(FIXMAP, "fixed for repairs; **not hard for the baseline**"), (G134, "| (d) no entry over $2, cost guard correct | PASS |")],
         "Hard for repairs, observed in the gate; the baseline run is still not capped."),
    _row("D-8", "A timed-out operation's spend was unrecorded", FIXED_GATED, (DEFECTS, "**D-8 A timed-out sandbox operation may be unrecorded spend.**"),
         [(FIXMAP, "fixed; the real kill path is verified live at the seal"),
          (G134, "the killed step's spend was recorded (#8: $0.28 estimate flagged)")],
         "The gate kill carries a flagged estimate. Seal-verification kill runs carry no cost for the killed step (see the ledger defect, open)."),
    _row("D-9", "Error extraction took noise as the error", FIXED_GATED, (DEFECTS, "**D-9 Error extraction takes noise as the error.**"),
         [(FIXMAP, "| `tests/test_v133_tavily_classifier.py` | fixed |"), (G133, "The classifier did its job (no noise taken for an error)")]),
    _row("D-10", "Environment change could not remove a system package", FIXED_UNVALIDATED,
         (DEFECTS, "**D-10 `remove` in env_delta does not remove apt packages.**"),
         [(FIXMAP, "test_remove_of_an_apt_package_edits_the_apt_list_entry_12` | fixed |")], "Offline test only."),
    _row("D-11", "The time machine overrode a declared Python version", FIXED_GATED,
         (DEFECTS, "**D-11 The time machine overrides a repo-declared Python.**"),
         [(FIXMAP, "test_the_orchestrator_passes_the_readme_python_to_the_era_lock` | fixed |"), (G133, "README Python 3.6 honoured (D-11 works)")]),
    _row("D-12", "Repairer proposed packages that do not exist, and one unrelated project", OPEN,
         (DEFECTS, "**D-12 The repairer proposes packages that do not exist for the image, and one that is a different project.**"),
         [(FIXMAP, "**partly:** the confusion guard is fixed")], "Partly fixed; system package names are still not validated before a sandbox run."),
    _row("D-13", "Runner-setup failures never reach the time machine", OPEN, (DEFECTS, "**D-13 Runner-setup failures never reach the time machine.**"),
         [(FIXMAP, "**open, not addressed in v1.3.3**")]),
    _row("D-14", "A pre-registered methodology sentence is inaccurate", FIXED_UNVALIDATED, (DEFECTS, "**D-14 METHODOLOGY line 729 is inaccurate.**"),
         [(FIXMAP, "the pre-registered text is not edited | — | documented |")], "Documentation correction; the pre-registered text is not edited and no gate applies."),
    _row("D-15", "Patch application broke on a Windows host", FIXED_GATED,
         (FIXMAP, "| D-15 (new) | on a Windows host `git apply` received the patch through text-mode stdin"),
         [(FIXMAP, "negative control `test_negative_control_text_mode_stdin_really_breaks_git_apply_on_windows`"),
          (G133, "#3 repair 1 and repair 2 applied and re-executed (first applied patches of the project: v1.3.2 0 of 16)")]),
    _row("D-16", "Runner installed an incompatible NumPy beside an old torch", FIXED_GATED,
         (FIXMAP, "| D-16 (new) | entry 11: the runner installed NumPy 2 beside a torch < 2.3"),
         [(FIXMAP, "live at the seal (`runner_numpy_cap_old_torch`) | fixed |"), (G133, "NumPy cap + era lock (entry 11 recovered with no model call)")],
         "The cap worked live. The recovery named in the quoted line was later identified as a smoke-limit artefact."),
    _row("D-17", "A step stopped by the sandbox returned as a normal result", FIXED_GATED,
         (FIXMAP, "| D-17 (new, found live at the seal verification, 2026-09-30)"),
         [(METHODOLOGY, "so both branches of the stop handling were seen live"), (G134, "the guard fired twice (#11, #8), both correctly")]),
    _row("D-18", "The managed lock was shown to the repairer under the repository file's name", FIXED_GATED,
         (DEFECTS, "- **D-18** The repairer prompt shows"),
         [(FIXMAP, "`tests/test_v134_repair_loop.py` (D-18 section) | fixed |"), (G134, "D-18 (no attempt targeted the lock)")]),
    _row("D-19", "A silent exit left the repairer no error text", FIXED_GATED, (DEFECTS, "- **D-19** A silent exit 1 after a progress stream"),
         [(G134, "D-19 (silent exits detected, head+tail delivered, blind patch rejected, diagnostics patch applied)")],
         "The detection and the blind-patch rule worked live; locating the exit is a separate open defect."),
    _row("D-20", "The download route could not carry a patched file", FIXED_UNVALIDATED, (DEFECTS, "- **D-20** The download route"),
         [(G134, "D-20 (verified at the seal on entry 8's repository; not reached in the gate)")], "Verified live at the seal only; not reached in the gate."),
    _row("D-21", "The repairer never cites", OPEN, (DEFECTS, "- **D-21** The repairer declared no `cited_sources` in 7 searches"),
         [(G134, "**D-21 (still open in practice): the repairer never cites, even with a REQUIRED field.**")],
         "The mechanism exists; no attempt in any record carries a citation."),
    _row("D-22", "An attempt that ended in a harness error was not recorded", FIXED_GATED,
         (DEFECTS, "- **D-22** An attempt that ends in INVALID_HARNESS is not recorded"),
         [(FIXMAP, "| D-22 section | fixed |"), (G134, "D-22 (no attempt lost)")]),
    _row("D-23", "Per-repair funding starves entries that pay a torch install each time", OPEN, (DEFECTS, "- **D-23** The per-repair funding rule"),
         [(DEFECTS, NOT_FIXED_134)]),
    _row("D-24", "The compiler rule fires only on the baseline classification", FIXED_UNVALIDATED, (DEFECTS, "- **D-24** The deterministic"),
         [(D24_TEST, "def test_at_repair_time_the_recorded_gcc_error_adds_build_essential_with_no_model_call"),
          ("CHANGELOG.md", "post-gate, unvalidated")],
         "Fixed after the last gate, in a harness version that is not sealed and has run in no gate. The basis is an offline test, not a gate line."),
    _row("D-25", "Model-placed diagnostics cannot locate a deliberate silent exit", OPEN, (DEFECTS, "- **D-25** One round of model-placed diagnostics"),
         [(DEFECTS, NOT_FIXED_134)]),
    _row("D-26", "No reason is recorded when a declined attempt does not cite", OPEN,
         (DEFECTS, "- **D-26** `reason_no_citation` is not recorded on a DECLINED attempt"), [(DEFECTS, PHASE_D)]),
    _row("D-27", "The ledger records only completed cost", OPEN, (DEFECTS, "- **D-27** The ledger records only completed cost"), [(DEFECTS, PHASE_D)],
         "The ledger total is a lower bound."),
    _row("D-28", "Result-table record hashes are hashes of worktree files", OPEN, (DEFECTS, "- **D-28** `record_*_sha256` in"), [(DEFECTS, PHASE_D)],
         "The mapping to blob hashes and record ids is in the record index."),
]
