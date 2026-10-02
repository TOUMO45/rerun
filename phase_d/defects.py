"""The defect register D-1..D-43 as data, each row with quoted sources from the committed reports.

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
G141 = "reports/corpus-v2.1/v1.4.1/gate/GATE_REPORT_v1.4.1.md"
G142 = "reports/corpus-v2.1/v1.4.2/gate/GATE_REPORT_v1.4.2.md"
G143 = "reports/corpus-v2.1/v1.4.3/gate/GATE_REPORT_v1.4.3.md"
SEAL141 = "reports/corpus-v2.1/v1.4.1/seal/SEAL_STATUS.md"
METHODOLOGY = "METHODOLOGY.md"
D24_TEST = "backend/tests/test_d24_build_essential.py"

FIXED_GATED, FIXED_UNVALIDATED, OPEN = "fixed-and-gated", "fixed-unvalidated", "open"
STATUSES = (FIXED_GATED, FIXED_UNVALIDATED, OPEN)
STATUS_RULE = {
    FIXED_GATED: "The fix map calls it fixed with no open remainder, and a committed gate report line states the fix was observed "
                 "working live. It does not mean a gate passed: none did.",
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
         "The mechanism exists; citations are stored in the records of the first two root-cause-line gates and are absent in the last, so it still shows in practice."),
    _row("D-22", "An attempt that ended in a harness error was not recorded", FIXED_GATED,
         (DEFECTS, "- **D-22** An attempt that ends in INVALID_HARNESS is not recorded"),
         [(FIXMAP, "| D-22 section | fixed |"), (G134, "D-22 (no attempt lost)")]),
    _row("D-23", "Per-repair funding starves entries that pay a torch install each time", FIXED_GATED, (DEFECTS, "- **D-23** The per-repair funding rule"),
         [(DEFECTS, NOT_FIXED_134), ("reports/corpus-v2.1/v1.4.0/gate/GATE_REPORT_v1.4.0.md", "The checkpoint fix worked as designed")],
         "Fixed by checkpoint images in the first root-cause-line version and observed in its gate (the era run branched from the baseline's torch layer). Entries that still ended COST_CAP did so for the funding and resume defects registered later."),
    _row("D-24", "The compiler rule fires only on the baseline classification", FIXED_GATED, (DEFECTS, "- **D-24** The deterministic"),
         [(D24_TEST, "def test_at_repair_time_the_recorded_gcc_error_adds_build_essential_with_no_model_call"),
          ("CHANGELOG.md", "post-gate, unvalidated"),
          (G142, "Candidate 3 had the D-33/D-34/D-35 rules fire on its branch (build-essential, exit hook, exit wrapper: $0.5079 together)")],
         "Fixed after the third exploratory gate and labelled unvalidated then; the sealed versions since carry it, and the last gate shows the compiler rule firing live on a candidate's own branch, with no model call."),
    _row("D-25", "Model-placed diagnostics cannot locate a deliberate silent exit", OPEN, (DEFECTS, "- **D-25** One round of model-placed diagnostics"),
         [(DEFECTS, NOT_FIXED_134), (DEFECTS, "- **D-25 [annotation: premise withdrawn by the D-41 probe]**")],
         "Its premise, a deliberate silent exit on the third corpus entry, was a CUDA error behind a cut stream, the defect registered after it. Kept open as a design for a genuine silent exit; no record shows one."),
    _row("D-26", "No reason is recorded when a declined attempt does not cite", OPEN,
         (DEFECTS, "- **D-26** `reason_no_citation` is not recorded on a DECLINED attempt"), [(DEFECTS, PHASE_D)]),
    _row("D-27", "The ledger records only completed cost", OPEN, (DEFECTS, "- **D-27** The ledger records only completed cost"), [(DEFECTS, PHASE_D)],
         "The ledger total is a lower bound."),
    _row("D-28", "Result-table record hashes are hashes of worktree files", OPEN, (DEFECTS, "- **D-28** `record_*_sha256` in"), [(DEFECTS, PHASE_D)],
         "The mapping to blob hashes and record ids is in the record index."),
    # D-29..D-41: found by the harness-v1.4.0 seal and the v1.4.0 / v1.4.1 / v1.4.2 gates (register: candidate_v1.3.3_defects.md)
    _row("D-29", "The seal script of the first root-cause-line version lost the cost of a timed-out operation", FIXED_UNVALIDATED, (DEFECTS, "- **D-29** The v1.4.0 seal script"),
         [(DEFECTS, "Status: fixed-unvalidated (tests exist; not gate-validated)")],
         "A seal-script defect: its fix is exercised by the later seals, which are not gates."),
    _row("D-30", "The guard funded every operation at a fixed wall-clock rate", FIXED_GATED, (DEFECTS, "- **D-30** The guard funded every operation at a fixed $0.0085 per second of WALL clock"),
         [(G141, "**D-30** funded every operation between $0.0030 and $0.0052 per wall second (recorded on each) and never starved one")],
         "The rolling rate worked live in the second root-cause gate. In the last gate one entry ended COST_CAP at its entry cap, not for lack of the funding rule."),
    _row("D-31", "A budget-limited stop ended the entry although the kept layers could resume", FIXED_UNVALIDATED,
         (DEFECTS, "- **D-31** A budget-limited stop ended the entry even when the stopped operation had kept every layer it built"),
         [(G141, "**D-31** was not exercised (no operation")], "Verified at the seal on the real service (the kept layer of a killed operation is reopened); not exercised in any gate."),
    _row("D-32", "The candidate adjudicator had no JSON re-ask", FIXED_GATED, (DEFECTS, "- **D-32** The candidate adjudicator had no JSON re-ask"),
         [(G141, "**D-32** re-asked live once (#7 round 3)."), (G142, "D-32's re-ask worked on #8 round 1.")]),
    _row("D-33", "The deterministic rules only saw the adopted failure", FIXED_GATED,
         (DEFECTS, "- **D-33** The deterministic rules (D-24, the CPU shim, the exit-site hook) only saw the adopted failure."),
         [(G141, "**D-33** fired live once, adopted (#8 round 3, the CPU shim on the candidate's own failure)")]),
    _row("D-34", "A repair-time apt package rebuilt the first setup step", FIXED_GATED,
         (DEFECTS, "- **D-34** An apt package added at repair time changed the plan's FIRST setup step"),
         [(G142, "Candidate 3 had the D-33/D-34/D-35 rules fire on its branch (build-essential, exit hook, exit wrapper: $0.5079 together)")],
         "The additive apt layer ran live in the last gate, on two entries."),
    _row("D-35", "The exit-site hook cannot see a bare raise SystemExit", FIXED_UNVALIDATED, (DEFECTS, "- **D-35** The exit-site hook cannot see a bare `raise SystemExit(n)`"),
         [(G141, "**D-35** fired twice (#3, #11) and both times reported \"exit outside Python\"")],
         "The wrapper fired in the gates and printed nothing each time; the seal shows it printing the raise site on a controlled script. The probe showed that on the silent-exit entry its output was cut off by the truncation defect (confirmed), and the last gate never reached that path again, so no gate line shows it working."),
    _row("D-36", "Ledger figures are API-reported cost, not account billing", OPEN, (DEFECTS, "- **D-36** Ledger figures are the sandbox API's reported operation cost"),
         [(DEFECTS, "Annotation on **D-36** (2026-10-01, the owner's second balance reading)"), (G141, "D-36 stays open")],
         "The balance moved far less than the ledger in both readings; the cause is not established."),
    _row("D-37", "The adjudicator adopted nothing unless the run passed", FIXED_GATED, (DEFECTS, "- **D-37** The candidate adjudicator adopts nothing unless the run passes."),
         [(G142, "D-37 partial progress worked as designed on #7 round 2")],
         "Observed once, on one entry: the adoption and its reasons are in the record. The only RUNS_AFTER_REPAIR of the root-cause-line gates followed it."),
    _row("D-38", "A kill by signal was classified as a silent exit", FIXED_GATED, (DEFECTS, "- **D-38** A kill by signal is classified as a silent exit."),
         [(G142, "D-38 / D-40: #11 is a MEMORY kill, evidenced from inside the sandbox (OOM-killer line, 3.85 GiB VM)")]),
    _row("D-39", "The CPU shim did not cover an explicit .cuda()", FIXED_GATED, (DEFECTS, "- **D-39** The CPU shim covers `torch.load` and `torch.cuda.is_available()` only."),
         [(G143, "the first live exercise of the `.cuda()` path, D-39")],
         "Checked against real torch offline, then observed live on the entry whose explicit call had been hidden by the truncation defect: the shim handled it with no model call."),
    _row("D-40", "The sandbox's resource limits were invisible to the harness", FIXED_GATED, (DEFECTS, "- **D-40** Resource classification and evidence."),
         [(G142, "D-38 / D-40: #11 is a MEMORY kill, evidenced from inside the sandbox (OOM-killer line, 3.85 GiB VM)"),
          (G143, "**The API's peak-memory figure for the step (`max_rss`, stored for the first time in this version)")],
         "Kills are classified, one evidence run reads the sandbox, and the API's own peak memory per step is stored as returned. The memory limit itself is a platform limit: the SDK has no instance parameter, so the entry ends INDETERMINATE with the kernel line quoted."),
    _row("D-41", "The sandbox SDK truncates each output stream at a fixed byte limit and the harness does not look", FIXED_GATED,
         (DEFECTS, "- **D-41** The sandbox SDK truncates stdout and stderr at 65,535 bytes"),
         [(G143, "**D-41 fixed, live.**"), (DEFECTS, "- **D-41 [annotation: CONFIRMED by the probe of 2026-10-02]**"),
          (DEFECTS, "- **D-41 [annotation: suspected on other records (D6 scan)]**")],
         "Confirmed by a probe, fixed in the last version (the client asks for a larger limit, the API's flag, the sizes and the hashes are stored, a cut stream with no error is labelled instead of guessed) and observed live on the entry whose CUDA error had been cut off in every earlier version. A stream beyond the new limit would still lose its end; none did. The records of the earlier versions keep what they stored: the probe confirms one record, the silent-exit records of the others are inferred from the same cut point, and the red-team scan flags three more whose stored tails end mid-line in a build log (suspected, not probed); a verdict that rests on a cut stream stays as recorded, with the annotation beside it."),
    _row("D-42", "A smoke-criterion pass had nothing beside it saying how long the command really ran", FIXED_UNVALIDATED,
         (DEFECTS, "- **D-42 [new; the sustained-run line, fixed-unvalidated]**"),
         [(G143, "the sustained-run line (D-42) had nothing to label and made no live run")],
         "A non-gating line re-executes a smoke pass from its kept image for as long as the gate cap allows and stores the outcome beside the verdict. Its primitive was verified live in the seal; no entry ended with such a verdict in the last gate, so no gate line shows it working."),
    _row("D-43", "A gate run cannot be resumed and its process can be killed by its environment", OPEN,
         (DEFECTS, "- **D-43 [new, open]**"),
         [(G143, "A full restart was impossible")],
         "The gate process was killed twice (with the session that started it, then by a console control event whose sender is not known). After the fact the runner can resume from complete records and runs without a console, and the resumed gate finished; the cause of the second death is not known, and the spend of the interrupted attempts is only a lower bound."),
]
