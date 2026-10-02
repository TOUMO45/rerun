# Changelog

One entry per phase of the post-corpus-v2 plan. Numbers are produced by scripts in `scripts/`.

## Phase D update for harness-v1.4.3 and D6 red team (2026-10-02; offline)
65 passports, REPLAY for seven versions, the dashboard and the five submission texts rebuilt; register D-1..D-43 (D-39, D-40, D-41 fixed-and-gated, D-42 fixed-unvalidated, D-43 open). Headline by the owner's rule: 2 of 24 gate entry-runs reached a RUNS_* verdict, no gate passed. Ledger $29.1704 = $26.2069 API-reported + $1.4761 estimated + $1.4874 derived (parsed from the logs of the killed gate attempts), a lower bound; BILLED for the last two gates awaited.
D6 (`reports/phase-d/D6_RED_TEAM.md`): findings fixed or documented in six attacks; `phase_d.truncation_scan` lists the 11 records that may rest on a cut stream, each with a D-41 annotation (probed, inferred or suspected) and no changed verdict; new tests compare the gate reports' figures with the rebuilt ones; the repair loop is stated to have worked blind on entry 3 before the last version.

## harness-v1.4.3 - gate (2026-10-02; live, NOT PASSED: 0 of 4)
Entries 3, 7, 8, 11: #3 BLOCKED DATA_MISSING (the CUDA error that the 65,535-byte cut had hidden in every version was seen, the CPU shim fired, then a dataset path that does not exist in the sandbox), #7 and #8 BLOCKED RUNTIME_ERROR_OTHER, #11 INDETERMINATE RESOURCE_LIMIT (OOM again). (b), (c) (7 citations), (d), (e) pass. Gate $3.69455; ledger $29.1704 (lower bound), room $2.8296 under the $32.00 ceiling. The gate process was killed twice by its environment and finished as a resumed run (INTERRUPTED_ATTEMPT.md); no stream of any record was cut; no RUNS_* entry, so no sustained run. Report `reports/corpus-v2.1/v1.4.3/gate/GATE_REPORT_v1.4.3.md`. All live work stops for good; Phase D and the D6 red team follow.

## harness-v1.4.3 - seal (2026-10-02; live, $1.4307 recorded)
All 17 earlier seal entries re-verified against the new `sandbox.py` plus two new ones (19 paths, 34 live run ids), five stages, every check ok; $1.1262 API-reported + $0.3045 ESTIMATED (K1 stopped step), cap $1.50, branch run $0.00053. New live checks: a 200,075-byte stderr comes back whole, a 5 MiB stream is cut at exactly 4 MiB with the flag set, a cut inside a multi-byte character returns without an exception, `run_on_image` works. Ledger $23.9728 (lower bound), ceiling $32.00. Tag `harness-v1.4.3`; report `reports/corpus-v2.1/v1.4.3/seal/SEAL_STATUS.md`.

## harness-v1.4.3-rc — D-41 probe and Step 1 of the v1.4.3 directive (2026-10-02; offline except the probe, unsealed)
Owner's answers to the v1.4.2 report: v1.4.2 accepted; headline wording and the replacement rule ("state the verdict class and the criterion it met, never a rate, never the word recovered without the criterion beside it"); spend ceiling raised to $32.00; D-41 probe first, then v1.4.3 as the final gate, then Phase D and D6 without waiting.
**Probe (cap $0.05, cost $0.048615 API-reported): D-41 confirmed.** #3's real stderr is 400,939 bytes, the SDK returned 65,535, the raw `truncated` flag was true, and the cut-off tail is `AssertionError: Torch not compiled with CUDA enabled` at `.cuda()`: #3's "silent exit" in every version was a CUDA error the harness never saw, and the CPU shim never ran on it. Record `d41-probe/probe_03_vmtl_op5@51727e64...`.
v1.4.3-rc: every sandbox client asks for a 4 MiB output limit; each step stores the API's truncated flags, sizes, hashes and peak memory as returned; a failed command still cut with no error in it ends INDETERMINATE OUTPUT_TRUNCATED; the smoke attempt records the image it ran on; entry cap $1.75, gate cap $7.00; the sustained-run line (D-42, non-gating) re-executes each RUNS_* entry whose smoke run was alive from its final image for up to 600 s (funded from what the gate cap has left). No larger-instance rule: the SDK has no such parameter. The directive's tee-to-a-file re-fetch is not implemented (reasons in `candidate_v1.3.3_defects.md`). Independent review of the rc: 2 HIGH and 4 MEDIUM findings fixed (the sustained run re-executes the command the smoke run executed; the last attempt's cut stream is not BLOCKED; byte requests so a cut multi-byte character cannot raise inside the SDK; a cut ALIVE line; the classifier's progress pattern was quadratic on a long digit run; the seal driver records every stage's spend). Seal: all 17 entries re-verified (sandbox.py changed), ESTIMATED $1.4765 (pessimistic: the stopped step of K1 at $0.0152/s), cap $1.50. Ledger $22.5421 (lower bound), ceiling $32.00.

## harness-v1.4.2 — gate (2026-10-01/02; live, NOT PASSED: 1 of 4)
Entries 3, 7, 8, 11: #7 RUNS_AFTER_REPAIR (60 s smoke; D-37 partial progress adopted candidate 2 in round 2), #3 INDETERMINATE EXIT_OUTSIDE_PYTHON, #8 INDETERMINATE COST_CAP at the $1.50 cap (past the GPU error, `compare_psnr`), #11 INDETERMINATE RESOURCE_LIMIT (the evidence run read the kernel's OOM kill on a 3.85 GiB VM). (c) failed: no citations. Gate $3.9350 API-reported, ledger $22.4935, room $2.5065. New D-41: the SDK truncates each output stream at 65,535 bytes and the harness never reads `.truncated`; #3's silent exit is probably a cut-off error (not proven). Report `reports/corpus-v2.1/v1.4.2/gate/GATE_REPORT_v1.4.2.md`. All live work stops; Phase D follows.

## harness-v1.4.2 — seal (2026-10-01; live, $0.045032 API-reported)
Option B over `runner_hooks.py` only: 9 of 9 operations ok (the hooks and the wrapper as in v1.4.1; the evidence command around a calm run, a self-SIGKILL, and an allocation probe). The probe measured what no document gives: a sandbox VM has 3.85 GiB of memory, 4 CPUs and no swap, and a process that holds all of it is killed with exit 137. Every seal record carries its code blobs; the writer checks them. Independent review of the Step 1 diff: 8 findings fixed before the seal (STEP1_REPORT section 8). Ledger $18.5533. Tag `harness-v1.4.2`; report `reports/corpus-v2.1/v1.4.2/seal/SEAL_STATUS.md`.

## harness-v1.4.2-rc — Step 1 of the v1.4.2 directive (2026-10-01; offline, unsealed, no Nebius call, no spend)
Four fixes from the v1.4.1 gate: D-37 the adjudicator adopts the candidate that strictly advanced furthest when none passes ("partial progress"); D-39 the CPU shim covers `.cuda()`, `.to("cuda*")` and `torch.device("cuda*")` and records
the paths that fired; D-38/D-40 exit 137 / -9 is RESOURCE_LIMIT (INDETERMINATE with the limit quoted, one evidence run that reads the sandbox's own limits, no model attempt; the documented limits, none for memory and CPU, are stored on every
operation); #3's "exit outside Python" gets one more wrapper run with evidence (RESOURCE_LIMIT if a kill is evidenced, else INDETERMINATE EXIT_OUTSIDE_PYTHON). From now on a killed step is ESTIMATED at $0.0152/s (owner, D-27); past
estimates are annotated, not recomputed. BILLED for the v1.4.1 gate: $49.57 (at most $0.43 cumulative; $0.04 between the readings against $3.8588 recorded). Gate v1.4.2 pre-registered (same entries, order, criteria; entry cap $1.50,
gate cap $6.00; seal cap $0.49 so that seal + gate stay under the $25.00 ceiling); seal = option B over changed files, estimated $0.2821. `harness-v1.4.1` (`5ba14a2`) untouched. Ledger $18.5083 ($17.3366 API-REPORTED + $1.1717 ESTIMATED,
lower bound D-27). Report: `reports/corpus-v2.1/v1.4.2/STEP1_REPORT.md`.

## harness-v1.4.1 — gate v1.4.1: attempted, did not pass (2026-10-01; live, owner's caps)
Gate on entries 3, 7, 8, 11: NOT PASSED, (a) 0 of 4 (all BLOCKED; no entry ended COST_CAP, v1.4.0 had two); (b), (c), (d), (e) pass (8 patches applied, 6 attempts with stored citations, largest entry
$1.1140 of $1.50, no operation stopped). Live: the exit wrapper reported "exit outside Python" on #3 and #11 (#11: killed by signal, exit 137, after the CPU shim cleared its GPU error); the CPU shim fired on a
candidate's own failure on #8 (D-33); the adjudicator re-asked once on #7 (D-32). New findings D-37 (the adjudicator adopts no partial progress), D-38 (a kill by signal is a silent exit), D-39 (the shim does not
cover `.cuda()`). The first pre-batch upload smoke test failed on a slow line and the gate refused to start; it passed on the second attempt. Gate spend $3.5247 API-reported; ledger $18.5083
($17.3366 API-REPORTED + $1.1717 ESTIMATED, lower bound D-27). Report: `reports/corpus-v2.1/v1.4.1/gate/GATE_REPORT_v1.4.1.md`. Phase D assets unchanged.

## harness-v1.4.1 — seal (option B over changed files only), complete (2026-10-01; live, owner's caps)
Ten live operations, all ok: the exit wrapper on Python 3.10 and 3.6 (a bare `raise SystemExit(1)` leaves nothing on stderr with the hook alone), the additive apt layer on a kept
image, and the layer of an operation stopped at its limit reopened by id by a new operation (D-31 on the real service). Seal spend $0.3263 ($0.1254 API-REPORTED + $0.2009
ESTIMATED), branch run $0.00062790. 11 of the 12 v1.4.0 seal entries carried over (their code files are unchanged). Tag `harness-v1.4.1`. The gate v1.4.1 starts under the seal -> gate rule.
Ledger $14.9758 ($13.8041 API-REPORTED + $1.1717 ESTIMATED, lower bound D-27). Report: `reports/corpus-v2.1/v1.4.1/seal/SEAL_STATUS.md`.

## harness-v1.4.1-rc — Step 1 of the v1.4.1 directive (2026-10-01; offline, unsealed, no Nebius call, no spend)
Six deterministic fixes from the v1.4.0 gate records, each registered fixed-unvalidated (D-30 to D-35) with its test: the funding rate is the rolling measured rate of the
entry's own completed operations x 1.5 (floor $0.0030, ceiling $0.0085) and is recorded on every operation; a budget-limited stop resumes from a kept environment image while the
money left funds one operation; the candidate adjudicator re-asks once on invalid JSON and falls back to the furthest recorded stage; D-24, the CPU shim and the exit hook observe every
candidate's failure; repair-time apt packages are additive layers on the kept image (no change to `sandbox.py`); an exit wrapper catches the bare `raise SystemExit` the hook cannot see.
D-36 (open): ledger figures are the sandbox API's reported cost, not account billing (balance reading: at most $0.39 charged against a ledger of $14.6495); the tag MEASURED is
renamed API-REPORTED in the Phase D assets, with BILLED lines. Gate v1.4.1 pre-registered (same entries, order and criteria; entry cap $1.50, gate cap $6.00); seal = option B over
changed files only, estimated $0.3637, cap $1.00. Report: `reports/corpus-v2.1/v1.4.1/STEP1_REPORT.md`. `harness-v1.4.0` (`15d3cdf`) stays byte-identical.
Ledger $14.6495 ($13.6787 API-REPORTED + $0.9708 ESTIMATED, lower bound D-27).

## harness-v1.4.0 — seal (option B) and gate v1.4.0: attempted, did not pass (2026-10-01; live, owner's caps)
Seal complete (run 1: branch run $0.00054618 MEASURED, kept image reopened after 600 s at $0.00017; 14 option-B checks; run 2 retry after
D-29, the seal script's funding defect), tag `harness-v1.4.0` at `15d3cdf`. Gate on entries 3, 7, 8, 11: NOT PASSED, (a) 0 of 4; (b), (c),
(d), (e) pass, (c) with the first stored Tavily citations of any gate. Report and findings: `reports/corpus-v2.1/v1.4.0/gate/GATE_REPORT_v1.4.0.md`.
Phase D assets unchanged. Ledger $14.6495 ($13.6787 MEASURED + $0.9708 ESTIMATED, lower bound D-27).

## harness-v1.4.0-rc — Step 1 of the v1.4.0 directive (2026-10-01; offline, unsealed, no Nebius call, no spend)
Root-cause fix of D-23 (the environment was rebuilt in every sandbox operation): operations keep their images (the committed tree, then one
image per setup step) and later operations reopen the deepest matching one by id and run only the missing steps; every gate-approved change
travels in a branch overlay on top (the D-20 download-route overlay leaves the live flow; its tests are marked `legacy`). Deterministic steps
before any model call: the CPU shim on GPU_REQUIRED and the D-25 exit-site hook on a silent exit (`runner_hooks.py`), next to D-24. Parallel
repair: up to three candidates per failure, py_compile-checked, run in branches (concurrently when the budget funds each branch, else
one after another); the outcome-changing ones are adjudicated by
Ultra, the chosen one is applied and its image becomes the environment image. Gate budget rules (`gate_budget.py`): gate cap >= 4 x a fixed
entry cap. New record field `operations` (sandbox_seconds, install_seconds per step, branch_from_image, result_image, image_kept, ...).
Gate v1.4.0 pre-registered in METHODOLOGY with criterion (e); gate and seal runners under `reports/corpus-v2.1/v1.4.0/` (no default caps).
Details, tests and the decision needed on the seal rule: `reports/corpus-v2.1/v1.4.0/STEP1_REPORT.md`. Step 0 (budget note, annotations)
is `docs/design/v1.4.0-budget.md`. `harness-v1.3.4` stays at `10319b3`; Phase D assets unchanged. Ledger: $10.1349 ($9.8507 MEASURED +
$0.2842 ESTIMATED, lower bound D-27).

## Phase D5 — submission assets (2026-10-01; documents and offline tooling only, no Nebius call)
One commit per deliverable. (1) `docs/submission/demo_script.md`: a timed script under three minutes that shows recorded artifacts only, with a side-by-side table mapping every spoken
sentence that contains a number to a passport field or record id. To let the video and the texts quote models and counts from a recorded artifact, `replay/summary.json` gained `stack`
(model per role, call and token counts, sandbox backend, search configuration, read from the run records) and `inventory`, and the dashboard gained a "How it ran, as recorded" section.
`backend/tests/test_phase_d_submission.py` checks every submission text: each number is in the REPLAY JSON, each line with a number carries a tag, and no sentence says the LLM repair
loop recovered an entry. The pre-Phase-D demo script moved to `docs/history/`. (2) `README.md` rewritten in the submission order (what it is, the measured result, how it works, where Nemotron / Token Factory / Tavily are used,
offline and live runs, evidence and integrity, defect register and status rule, cost ledger, licence, known limits); the model names are checked against the records, every number is in
the REPLAY JSON and tagged; `summary.json` `inventory` gained the defect counts by status. The build-log README moved to `docs/history/README_build_log.md`. (3) `docs/submission/devpost_answers.md`: question drafts, ratings marked PROPOSED with their evidence, comparison with other models "not measured",
Tavily = Yes with the sentence that the model never cited a reference, new-vs-existing left blank for the owner. (4) `docs/submission/description.md`: the project description and a
two-sentence tagline. (5) `docs/submission/criteria_map.md`: for each judging criterion, three evidence items with record ids or test names and the weakest point stated plainly. Ledger: $10.1349 ($9.8507 MEASURED + $0.2842 ESTIMATED, lower bound D-27).

## Phase D4 — design notes for D-23 and D-25 (2026-10-01; documents only, no code)
`docs/design/D-23.md` (cached torch layer and per-operation floor, compared) and `docs/design/D-25.md` (harness-injected exit-site hook, with a `-X dev -m trace` fallback): the problem
as the records show it with record ids, the proposed mechanism, what a validating gate would have to measure, and an ESTIMATED cost of that gate. Both defects stay open.

## Phase D4 — D-24 fix: post-gate, unvalidated (2026-10-01; tag `harness-v1.3.5-unvalidated`; no Nebius call)
**post-gate, unvalidated.** The deterministic "missing C compiler -> apt build-essential" rule now also fires on a SYS_LIB_MISSING classification at repair time, before any model
proposal for that failure (deterministic first, model second). The step is recorded as an attempt of origin `time_machine` with `time_machine_action` = {rule, matched_error,
apt_added, phase}; it passes the same env gate as a model proposal and does not use up a model attempt. The baseline path is unchanged and shares the matcher. Only
`backend/app/services/orchestrator.py` changed. `harness-v1.3.4` (`10319b3`) stays byte-identical; this change is on `main` as `harness-v1.3.5-unvalidated`, which is not sealed and is
never used in a gate, seal, passport, REPLAY or dashboard figure. No gate has measured it: nothing here claims a recovery. Tests: test_d24_build_essential.py (entry 7's recorded
error string from the v1.3.4 gate record, no model call; baseline regression; an unrelated SYS_LIB_MISSING does not fire; the attempt record carries the quoted string).
Register: D-24 is now `fixed-unvalidated`, its basis the quoted test name. Dashboard wording: "harness-level, no entry passport"; the status column reads "Status (rule above)".
Ledger from here on: $10.1349 ($9.8507 MEASURED + $0.2842 ESTIMATED, lower bound D-27).

## Phase D3 — static dashboard from the REPLAY JSON (2026-10-01; offline, no Nebius call)
`python -m phase_d.build_dashboard` writes `reports/phase-d/dashboard/index.html`: headline card, gate scorecard (pre-registered anchor, CONTROL and TREATMENT separate; the two
EXPLORATORY versions with their D1 badges above the numbers), cost ledger (MEASURED + ESTIMATED, lower bound D-27, the three seal kill records), defect register D-1..D-28 with
status and passport links, and a per-entry drill-down. The build stops if the REPLAY check fails or if the rendered page has an untagged or unlinked number or an external resource
(`phase_d/check_dashboard.py` parses the HTML). REPLAY gained `summary.json` (headline counts, defect register with quoted sources, ledger recomputed from the seal and gate records)
and, per entry, the blob hash and the D-28 worktree hash. Passport annotations no longer carry a `status` (the register is the single source; still schema v3). D-24 is shown open.
Tests: test_phase_d_dashboard.py; test_phase_d_replay.py extended.

## Phase D housekeeping 2 — D-28, passport schema note, ledger rounding (2026-10-01; documentation and regenerated passports)
D-28 registered (the `record_*_sha256` values of `results_tables.json` are hashes of CRLF worktree files, not git blobs): open, documented only; `results_tables.json` is not
modified, `results_tables.md` carries the annotation beside its first hash column, and `reports/phase-d/record_index.md` maps worktree hash -> blob hash -> record id.
Passport schema: v1 at tag `phase-d1`, v2 at tag `phase-d2` (so passport hashes differ between the two tags), v3 from this commit (adds `record.results_tables_sha256`). Passports
are regenerable from the record blobs at any of these commits with `python -m phase_d.build_passports`. Ledger: the report's $10.134 is a sum of rounded components; the
full-precision record sum is annotated beside it. REPLAY regenerated (passport hashes changed).

## Phase D2 — REPLAY from committed records, cross-checked against the passports (2026-10-01; offline, no Nebius call)
`python -m phase_d.build_replay` writes `reports/phase-d/replay/<version>.json`, `<version>.md` and `index.md` for harness-v1.3.2 (the pre-registered anchor, CONTROL and
TREATMENT separate), v1.3.3 and v1.3.4 (EXPLORATORY badges from D1, verbatim). Per entry: baseline, era lock, each attempt (gate decision, outcome, consulted, cited, reason,
silent exit), execution and kills with the quoted source line, verdict with its annotations, and cost against the entry cap and the batch cap, split MEASURED / ESTIMATED.
Every value shown is cross-checked against its passport field (a mismatch stops the build); every number carries a tag and a pointer to the passport field; the output has no
build timestamp. Passport schema v2 adds the tagged fields REPLAY displays (consulted count, batch cap, per-operation cost lines, gate criteria b and d, the v1.3.2 primary
line); all 49 passports were regenerated and still verify. Tests: test_phase_d_replay.py.

## Phase D housekeeping — D-27, ledger lower bound, tag-check scope (2026-10-01; documentation only)
D-27 registered (the ledger records only completed cost; the spend of a killed step is absent): open, documented only. The ledger line in `SMOKE_GATE_REPORT_v1.3.4.md` is annotated
"$10.134 is a lower bound (D-27)"; no amount is reconstructed and no DERIVED bound exists (no event line states one). `reports/phase-d/README.md` states that the tag check is
JSON-only and that REPLAY and the dashboard may display only numbers read from tagged passport fields.

## Phase D1 — passports from committed records (2026-10-01; offline, no Nebius call; the sealed harness is untouched)
`phase_d/` (outside the sealed harness paths) builds one passport per committed run record of harness-v1.3.2 / v1.3.3 / v1.3.4 into `reports/phase-d/passports/`, with
`reports/phase-d/record_index.md`. Record id = `<harness_tag>/<arm>/<entry>@<sha256 of the committed blob>`; every number is tagged MEASURED, ESTIMATED or DERIVED; a field a
harness version did not store is null with that reason. `python -m phase_d.verify_passports` rebuilds from the blobs and diffs to zero; `python -m phase_d.check_tags` fails on an
untagged number. harness-v1.3.3 and v1.3.4 passports carry the EXPLORATORY badge with each version's own measured gate line. Annotations added beside (never in place of) the
original lines of `SMOKE_GATE_REPORT_v1.3.4.md` and `candidate_v1.3.3_defects.md`: the figure 9 for consulted attempts is not reproducible from records (records: `consulted` on 7
attempts, `reason_no_citation` on 6), the gate and ledger totals contain the entry-8 estimate, and the headline is restated as 0 of 8 entry-runs. New defect D-26
(`reason_no_citation` not recorded on a DECLINED attempt): open, documented only. Tests: test_phase_d_passports.py.

## harness-v1.3.4 — the five defects the v1.3.3 smoke gate found (2026-09-30; exploratory; v1.3.2 stays the pre-registered result)
Smoke gate v1.3.3 (entries 11, 7, 3, 8): 1/4 recovered, 2 patches applied, 0 citations, no cost event; NOT PASSED. Fixes: D-20 the download route carries patched files as an
overlay applied before the integrity check (entry 8's INVALID_HARNESS); D-22 a voided attempt is still recorded; D-18 the RERUN-managed lock is never shown as `requirements.txt`
and cannot be a patch target; D-19 silent failures (no error text) give the repairer head+tail of both streams and the exit code, a blind code patch is rejected unless it only adds
diagnostics, and re-executions run unbuffered with faulthandler; D-21 numbered references with a REQUIRED `cited_sources` field, `consulted` and cited stored and hashed, a
deterministic `content_match` citation when the applied change's text appears in a reference. New tests: test_v134_overlay.py, test_v134_repair_loop.py.

## harness-v1.3.3 — exploratory repair-loop fixes (2026-09-30; v1.3.2 stays the pre-registered result)
Fixes for the defects the v1.3.2 records showed (`reports/corpus-v2.1/v1.3.3/DEFECT_FIX_MAP.md`): hard per-entry / per-operation spend enforcement during a sandbox operation
with killed-operation spend recorded and TIMEOUT instead of PIPELINE_ERROR; one static whole-tree dependency batch with the repo's own modules excluded and a dependency-confusion
guard; era-lock robustness (relax, drop, or one fallback pip step) and a README-declared Python that wins; a patch pipeline that rebuilds the model's diff and checks it with
`git apply --check` before the gate (offline: 11 of the 16 stored v1.3.2 patches recovered, 68.75 %, target 80 % not met offline); Tavily citations carried into the record and the passport;
classifier denoising; apt `remove`; smoke execution for re-executions; a Windows-host bug in the apply step (text-mode stdin turned LF into CRLF); NumPy<2 beside torch<2.3.
Suite: see the commit. Nothing was run on Nebius before the seal verification.

## Phase 0 — pilot run summary (2026-09-29)
corpus-v2 on harness-v1.2 was stopped by the operator after 3 of 20 entries (commit `56fc710`) because the
Nebius sandbox refuses torch's executable-stack shared objects and the harness charged that to the repository
(entry 3). It is recorded as a **pilot run**, not a baseline; entries 1–3 stay frozen (entry 2
UPLOAD_TOO_LARGE, entry 3 MISATTRIBUTED). `scripts/summarize_batch.py` produces `reports/corpus-v2/summary.md`
(results table, PRIMARY lines, STATUS, failure attribution, run integrity). The baseline is redesigned as a
same-harness ablation (CONTROL: repair off / TREATMENT: repair on), replacing "v2 vs v2.1".

## Phase 1 — sandbox limits (2026-09-29)
`backend/app/services/sandbox_limits.py` encodes the Nebius limits (source: Sandboxes team email, 2026-09-29): upload gate
120 MiB (unit unresolved by evidence, so the smaller reading is enforced with a margin; the harness-v1.2 cap of
125,009,920 B was the top of RERUN's probe ladder, not a Nebius number), an in-sandbox download route for over-limit
repos (manifest-only upload; the sandbox fetches the pinned GitHub commit and verifies it against the git-blob manifest;
WSL dry run passed, tamper caught), setup split into system/torch/rest operations, and a per-op 12 GB delta ESTIMATE
check. 26 new tests; suite 768 passed, 9 skipped.

## Phase 2 — SANDBOX_QUOTA / SANDBOX_INCOMPAT, error chain, attribution (2026-09-29)
Sandbox-side failures (quota/limit; platform refusal such as the exec-stack refusal that sank pilot entry 3) now end
INDETERMINATE and stop the repair loop; they are excluded from every rate. Every run records an ordered error chain with
attribution (REPO / ENV / SANDBOX_QUOTA / PLATFORM), `first_repo_error` (first REPO link) and `last_error`; passport bundle
v4 hashes the whole verdict record. Regression tests derive entry 1's chain from its real pilot log (first repo error =
undeclared `tabulate`; the `Iterable` error is ENV because we chose py3.11). Deviation from the brief, flagged: torch-family
missing is ENV even though undeclared (runner-provided by policy). Suite: 795 passed, 9 skipped.

## Phase 3 — runner-level torch and Python policy (2026-09-29)
Torch is now provided by the runner (CPU wheels as their own op, then an exec-stack fix + `import torch` verification op),
verified in a real sandbox (glibc 2.41, kernel 7.0.6): the newest wheel loads; an old pin (1.12.1) reproduces the pilot's
executable-stack refusal and is fixed by `patchelf --clear-execstack`. Python defaults to 3.10 unless the repo declares a version
(reason logged; 6-fixture resolver tests). Not done, with reasons: pre-warmed snapshot (SDK supports `tag_as`; low value, adds
mutable state) and pre-installing numpy/scipy/tabulate (would hide REPO-attributable undeclared dependencies). Preflight now refuses
a non-sealed `NEBIUS_SANDBOX_IMAGE`. Suite: 815 passed, 9 skipped.

## Phase 3b — harness-v1.3 driver and ablation plumbing (2026-09-29)
`live_run.py --arm control|treatment` (control: `repair_enabled=false`, no Tavily, no time machine); the batch driver owns its children
(kill-on-close job object on Windows, process group elsewhere; verified with a real process test), writes a driver log and pid file,
validates every record on resume (complete JSON, frozen hash/tag/arm, verifying passport, no driver error, never a dev run) and re-runs an
invalid one once; `scripts/watch_batch.py` reports pid-alive AND summary-absent with a timestamp on every line;
`scripts/compare_batches.py` implements the pre-registered analysis (categories never merged, stated denominator, Wilson interval, regression
exit code). The spend ceiling is a parameter (`--total-cap-usd`, `--already-spent-usd`) so one cap can span both arms without a re-seal. Preflight now allows `reports/` and `CHANGELOG.md` as post-tag data. Pre-registration written in METHODOLOGY. No batch started:
the spend cap as written (3× pilot = $1.13) is below one arm's expected cost; awaiting the operator's number.

## Phase 3c — upload boundary probe, spend cap, harness-v1.3.1 (2026-09-30)
`scripts/upload_boundary_probe.py` (records `runs/upload_probe/boundary_*.json`): 128,000,000 B and 127 MiB accepted; 128 MiB and 129 MiB
rejected (ENOSPC in the upload op). MAX_UPLOAD_BYTES stays 120 MiB (5.5 % below the largest accepted size); docstring and METHODOLOGY
"Sandbox limits" updated from "unsettled" to measured; re-sealed as `harness-v1.3.1` (no behavioural change vs v1.3). Operator decisions:
total spend cap $25 across both arms (`--total-cap-usd 25`), per-entry $2 unchanged; torch-family missing = ENV even when undeclared
(rationale in METHODOLOGY); TREATMENT gated on >= 8 CONTROL entries with a REPO-attributed non-PASS.

**Operator environment (not in git; `.env` is untracked):** `NEBIUS_SANDBOX_IMAGE` changed `python:3.11-slim` -> `python:3.10-slim`
(the sealed driver requires it).

## Phase 3d — attempt 1 aborted; harness-v1.3.2 (2026-09-30)
CONTROL on harness-v1.3.1 stopped at 4/20 ($0.47): entry 3 charged RERUN's failed `patchelf --clear-execstack` (py3.6 resolves patchelf 0.17.2)
to the repo, entry 2 failed the download route's exit-97 check (mode 664 vs 0644 on all 374 files, then a `shutil.move` into `/media` bug),
entry 4 lacked torchvision (runner installed torch only), and the driver crashed once on U+FFFD (cp1252). Records kept in
`runs/corpus_v2_batch/attempt1_harness-v1.3.1_aborted_4of20/`. v1.3.2: phase-first attribution (`runner_setup` never REPO; `RUNNER_SETUP_FAILED`),
runner-owned pinned patchelf with a pre-check (SANDBOX_INCOMPAT if the flag is absent), git-first download route with a tarball fallback and an
exec-bit-only mode check, matched torch family, UTF-8 driver, and the enforced seal rule (`seal_verification.json`, preflight). Live
verification records: `runs/sandbox_verification/final/` (9 real Nebius runs; pre-seal spend $1.97). Suite: 974 passed, 9 skipped.

## Phase 4 — CONTROL result and attribution audit (2026-09-30)
CONTROL on harness-v1.3.2: 20/20 records, $4.07 (commit `4b99d3b`). Read-only audit in `reports/corpus-v2.1/audit/`: gate (a) 16, (b) 12; no DECLARED_NOT_PARSED.
Pre-registered before TREATMENT (METHODOLOGY): the INFRA_ERROR retry policy and the fix-difficulty strata (`reports/corpus-v2.1/strata.json`, sha256 `ade8083fcda9bda5...`).

## Phase 5 (partial) - TREATMENT result and comparison (2026-09-30)
TREATMENT on harness-v1.3.2: 20/20 records, $17.68 (total with CONTROL $21.76 of $25). `scripts/compare_batches.py`: **RRR 0/16 (95 % Wilson 0-19 %)**, no regression.
Per-stratum table and four harness defects seen in the sealed run (numpy-2/old-torch runner failure charged to ENV, compare_batches filing it as REPO_STILL_FAILING, repair-time wall-clock
as PIPELINE_ERROR, the non-hard $2 per-entry ceiling): `reports/corpus-v2.1/treatment-findings.md`. Nothing in the sealed harness or any record was changed.

