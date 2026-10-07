# harness-v1.8 — Phase 1 triage (2026-10-07)

**Scope.** Phase 1 only: no harness code changed, no paid or live call made, nothing committed. The 21 held-out entries (TEST 8, TEST-B 8, out-of-sample scan 5) are read from their committed records at `4bccdfa`. Their published results are not edited; every correction below is stated beside them.

**Tags used for each statement.**

| tag | meaning |
|---|---|
| RECORD | read from a committed record under `runs/` |
| REPO | read from the target repository's source at its recorded commit (cloned into a scratch folder, read-only) |
| REPLAY | the harness's own current functions run offline on a recorded input |
| CHECKED | an outside fact I looked up today |
| JUDGEMENT | my estimate; **not a measurement** |

Effort scale (JUDGEMENT, includes tests and DEV verification): **S** ≤ 0.5 day, **M** about 1–1.5 days, **L** ≥ 3 days. "Seal" means the change touches a sandbox-touching file (`runner_env.py`, `runner_hooks.py`, `sandbox*.py`, `smoke_exec.py`) and needs the paid re-seal (previous seals: $1.12–$1.32 API-reported).

## 0. Two readings of the brief that I need you to confirm

1. **"Never re-run or re-score them" vs "may be used as DEV".** My reading: the *published* TEST / TEST-B / OOS results and records stay untouched, and no v1.8 number is ever attributed to those three sets. The 21 repositories may be run under v1.8 as **DEV (contaminated)**, written to a separate folder (`runs/dev_v18/`), labelled `DEV-CONTAMINATED (was TEST / TEST-B / OOS)` in every record, table and UI tile. If you meant that these repositories must not be run again at all, Phase 2 verification has only the original 8 DEV entries plus new DEV repos.
2. **Where "tamper gate semantics" ends.** Untouched in all cases: `tamper_gate.py` rules and `env_repair.py` rules. One proposed fix (T1) changes what the orchestrator *records as failed* before the gate sees it, so the same rule fires on different inputs. I count that as upstream bookkeeping, not a gate change, but it needs your yes. Also excluded as a gate change: the rule that treats any `test_*.py` file as protected (it rejected all 9 patches on TEST-B #1, see E-TB1).

## 1. What the 21 records say

| group | entries | count |
|---|---|---|
| Ran for real | TEST #10 patchSmoothing (CPU shim; sustained run not completed), TEST-B #4 L2D (CPU shim, exit 0) | 2 |
| Verdict RUNS_* but not a real run | TEST #18 adversary_critic (pipeline hid the failure), TEST-B #6 trees_from_transformers (`--help`), OOS steamctl (no-argument notice) | 3 |
| Blocked by something no generic harness fix removes: licensed or missing data, docker, conda, credentials, an era-bound extension, a documentation bug | TEST-B #1, #5; TEST #1, #2, #6, #19, #20; OOS fb scraper, openstreetmap-heatmap, AutoDoc-ChatGPT | 10 |
| Blocked by something a generic fix could pass (it may then meet another blocker) | TEST #13 neo_gnns; TEST-B #2 ovis, #3 video_prediction, #7 Hindsight, #8 gandissect; OOS mud-pi | 6 |
| | | **21** |

**Reading for the plan [JUDGEMENT].** Even if every run-relevant fix below works, I expect between 2 and 4 of the 6 "generic" entries to reach a RUNS_* verdict, and the 10 "no generic fix" entries will not move. So v1.8's honest gain is mostly in **diagnosis**, which matches your Phase 3. It should not be sold as a run-rate jump, and the TEST-C thresholds should be set from DEV evidence, not from hope.

**Cost of the 21 entries [RECORD].** $18.13 API-reported in total (cost guard). One entry broke its cap: TEST #13 neo_gnns recorded $4.18 against an entry cap of $2.50, see T17.

### 1.1 Entry table

`fixable_by` in the last-but-one column is what the record currently says; "wrong" is my JUDGEMENT.

| # | set | entry | verdict as recorded | what actually stops it | exact line in the record | what the record says a human must supply (judged) | disposition | fixes |
|---|---|---|---|---|---|---|---|---|
| E-T1 | TEST | nadiinchi/power_laws_deep_ensembles | BLOCKED DEP_MISSING | `models/vgg.py` imports `curves`, which is not in the repo (vendored from another project, never committed) [REPO]; the PyPI project `curves` is unrelated and fails to install (`SyntaxError`, invalid `match`) [RECORD: adjudicator] | `ModuleNotFoundError: No module named 'curves'` | "exact release of curves the authors used": **wrong**, no such release exists | DIAGNOSIS-ONLY | T9 |
| E-T2 | TEST | DeformableFriends/NeuralTracking | BLOCKED RUNTIME_ERROR_OTHER | documented command `sh start_nnrt.sh` runs `docker`; the sandbox has none | `start_nnrt.sh: 27: docker: not found` | "a code change; the repairer proposes one": **wrong** (`fixable_by: model`) | WONTFIX (run); stop early | T9 |
| E-T6 | TEST | grigorisg9gr/rocgan | BLOCKED RUNTIME_ERROR_OTHER | documented command passes `'--config …yml'` as one token, the script defines `--config_path` [REPO]; also needs MPI and CUDA (chainermn). Five gate-passed patches (rounds 2–3) went to `train_mn_rocgan.py` while `train_mn.py` was the file failing; the one patch aimed at `train_mn.py` was refused as unparseable [RECORD] | `SystemExit: 2` (the exit hook's re-raise, not argparse's message) | "a code change": **wrong** | WONTFIX (run) | T8, T9, T10 |
| E-T10 | TEST | alevine0/patchSmoothing | RUNS_AFTER_REPAIR GPU_REQUIRED | ran through the CPU shim, no model patch | — | — | OK | — |
| E-T13 | TEST | seongjunyun/neo_gnns | INDETERMINATE DEP_BUILD_FAILED (COST_CAP) | era lock failed on torch-scatter's build isolation, fell back to an unpinned install, then `torch_sparse` needed `g++`; a candidate compiling from source was killed at 257 s | `subprocess.CalledProcessError: Command '['which', 'g++']' returned non-zero exit status 1.` | "apt rule adds the build dependencies": right, but no rule exists for `g++` | GENERIC-FIXABLE | T5, T14, T6a, T17 |
| E-T18 | TEST | aam-at/adversary_critic | RUNS_CLEAN | documented `… | bash`: the script died on `import decorator`, the pipe's status is `bash`'s | none recorded (the stream's SHA-256 equals the 154-byte `ModuleNotFoundError: No module named 'decorator'` traceback, D-46 audit) | — | FALSE POSITIVE | T11 |
| E-T19 | TEST | lrjconan/RBP | BLOCKED DEP_MISSING | `operators/_ext` is built by the README's `./setup.sh` using `torch.utils.ffi`, which was removed in PyTorch 1.0; README asks for PyTorch 0.4.0 [REPO]. The tamper gate correctly refused to install an unrelated PyPI `operators` | `ModuleNotFoundError: No module named 'operators._ext'` | "exact release of operators._ext": **wrong** | WONTFIX (era-bound) | T9, T12 |
| E-T20 | TEST | XiaoxiaoGuo/fashion-retrieval | BLOCKED DATA_MISSING | pretrained captioner file; two patches also refused as unparseable | `FileNotFoundError: [Errno 2] No such file or directory: 'caption_models/infos_best.pkl'` | right | WONTFIX (human data); diagnosis already good | T7 |
| E-TB1 | TEST-B | yikangshen/Ordered-Neurons | BLOCKED RUNTIME_ERROR_OTHER | needs the licensed Penn Treebank. NLTK's downloadable `ptb` is a 6 KB stub "for the full Penn Treebank Corpus version 3" [CHECKED: NLTK index]. All 9 patches were also refused as `PROTECTED_PATH_MODIFIED` because the documented entrypoint is named `test_phrase_grammar.py` [RECORD] | `Resource ptb not found.` | "a code change": **wrong** | WONTFIX (licensed data; gate rule excluded) | T9 (D-54) |
| E-TB2 | TEST-B | vlievin/ovis | INDETERMINATE DEP_YANKED (RUNNER_SETUP_FAILED) | the runner's own setup could not install the pinned pre-release `torchvision==0.6.0a0`, so no baseline and no repair ran. The documented command also contains literal placeholders (`--exp exp_id --processes n_procs_per_gpu`) [RECORD] | `ERROR: Could not find a version that satisfies the requirement torchvision==0.6.0a0 (from versions: …)` | right | GENERIC-FIXABLE (then expect an argument error) | T2 |
| E-TB3 | TEST-B | alexlee-gk/video_prediction | BLOCKED DEP_BUILD_FAILED | `git+git://github.com/…lpips-tensorflow.git` in the install line: GitHub's `git://` protocol no longer answers (reproduced here: `Connection timed out`; `https://` answers) [CHECKED]. Before that the plan's `apt libgl1-mesa-glx` had "no installation candidate", classified RUNTIME_ERROR_OTHER, which skipped the time machine. Data and pretrained models are also missing [RECORD] | recorded `error: subprocess-exited-with-error` (pip's wrapper line); real line is `fatal: unable to connect to github.com: … Connection timed out` | "apt rule / a wheel": partly right | GENERIC-FIXABLE (then expect missing data) | T3, T10 |
| E-TB4 | TEST-B | zcajiayin/L2D | RUNS_AFTER_REPAIR GPU_REQUIRED | ran through the CPU shim | — | — | OK | — |
| E-TB5 | TEST-B | twitter-research/cwn | BLOCKED DEP_NOT_ON_PYPI | the documented command is an install script that needs conda for `graph-tool`; era lock also failed (torch-scatter build isolation) | `ERROR: Could not find a version that satisfies the requirement graph_tool (from versions: none)`; first error `graph-tool_install.sh: 3: conda: not found` | "exact release of graph_tool": **wrong** (conda-only) | WONTFIX (run); stop early | T9 |
| E-TB6 | TEST-B | galsang/trees_from_transformers | RUNS_CLEAN | documented command is `python run.py --help` | — | — | not a run (corpus definition); struck by the TEST-B audit | — |
| E-TB7 | TEST-B | Stilwell-Git/Hindsight-Goal-Generation | BLOCKED DEP_MISSING | needs the MuJoCo 2.1 binaries at `~/.mujoco/mujoco210`. **My TEST-B text called this "a licensed simulator binary"; that is wrong: MuJoCo 2.1.0 is free and downloadable** [CHECKED]. The error moved from `mujoco_py` to the missing library after the first candidate, and that progress was not adopted | `ModuleNotFoundError: No module named 'mujoco_py'` | "exact release of mujoco_py": misleading | GENERIC-FIXABLE (new rule) | T13, T1 |
| E-TB8 | TEST-B | CSAILVision/gandissect | BLOCKED SYS_LIB_MISSING | `apt libfreetype6-dev` was tried only on a losing round-1 branch (candidate 3, `apt pkg-config + libfreetype6-dev`) that died on another error; from then on it was barred as "already tried and failed", so the fix for the final error was never applied [RECORD, confirmed in the attempts] | `src/checkdep_freetype2.c:1:10: fatal error: ft2build.h: No such file or directory` | "apt rule resolves it": right, never applied | GENERIC-FIXABLE | T5, T1 |
| E-O1 | OOS | ValvePython/steamctl | RUNS_AFTER_REPAIR | `python steamctl/__main__.py` instead of `python -m steamctl` (D-50); the adopted `sys.path` patch then printed argcomplete's notice and exited 0 (D-51). Nothing ran | `ModuleNotFoundError: No module named 'steamctl'` | — | FALSE POSITIVE; product path only | T16 |
| E-O2 | OOS | n0kovo/fb_friend_list_scraper | BLOCKED API_REMOVED | newest pyOpenSSL removed `SSLv2_METHOD`; the first candidate that moved the error was not adopted; the tool also needs a Facebook login | `AttributeError: module 'OpenSSL.SSL' has no attribute 'SSLv2_METHOD'. Did you mean: 'SSLv23_METHOD'?` | "nothing, if the era lock …": **wrong** (needs credentials) | WONTFIX (credentials) | T9, T1 |
| E-O3 | OOS | Frimkron/mud-pi | INDETERMINATE ENTRYPOINT_UNCLEAR | the README says `python simplemud.py`; discovery found no candidate because the script's loop runs at module level (D-52) [REPO] | "no candidate scripts found …" | — | GENERIC-FIXABLE; product path only | T15 |
| E-O4 | OOS | njanakiev/openstreetmap-heatmap | BLOCKED API_REMOVED | Blender script needing the Blender release of its era; three patches refused as unparseable | `AttributeError: module 'bpy.ops.object' has no attribute 'select_by_layer'. Did you mean: 'select_by_type'?` | "nothing, if the era lock …": **wrong** | WONTFIX | T7, T9 |
| E-O5 | OOS | awekrx/AutoDoc-ChatGPT | INDETERMINATE ENTRYPOINT_NEEDS_ARGS | needs `-file` and an OpenAI key; stopped correctly | `main.py: error: the following arguments are required: -file` | right | WONTFIX (human input); diagnosis fine | — |

**Of the 14 blocker records, 9 carry a `fixable_by` / "human must supply" text that I judge wrong or misleading** (E-T1, T2, T6, T19, TB1, TB5, TB7, O2, O4) [JUDGEMENT]. The text is a fixed per-class sentence (`blocker.py`), so the same class always says the same thing whatever the evidence. That is the main Phase 3 target.

### 1.2 D-50 … D-54

| id | what it is | disposition in v1.8 |
|---|---|---|
| D-50 | package `__main__.py` run as a file, not `python -m pkg` | fix **together with D-51** (T16). On its own it would turn steamctl's false success into a plain RUNS_CLEAN false positive. Product path only: corpus runs use the documented command |
| D-51 | exit 0 after a no-argument CLI notice read as a run | T16 (plus T11's evidence-of-work check) |
| D-52 | module-level script is not an entrypoint candidate | T15: admit scripts the README names (`python simplemud.py`) as candidates [REPO]. Product path only |
| D-53 | TEST-B evaluator read a hash-only baseline as empty | an evaluator defect, not a harness one. For TEST-C the audit rules must work from hashes, and the harness should keep a tail for exit-0 baselines (T19) |
| D-54 | NLTK `Resource X not found` classified RUNTIME_ERROR_OTHER | T9 (classification). Note the entry it came from cannot run anyway (licensed data) |
| D-47 (residual) | the v1.7.2 indentation normaliser does not cover this class | see T7: replaying the recorded patches through the current code, `normalise_patch` refuses all 3 of osm-heatmap's and both of fashion-retrieval's [REPLAY]. rocgan's patch is stored truncated (6000 chars), so it cannot be replayed |

## 2. Generic defects and the ranked table

**Definitions.** **B** = entries whose recorded blocker the fix removes or passes (read from the record's own text; the entry may then meet another blocker). **U** = of those, entries I think could then reach a RUNS_* verdict [JUDGEMENT]. **D** = entries whose recorded class, error line or next action it improves. Ranking: B / effort (S = 1, M = 2, L = 4), then U, then D / effort. Items with B = 0 are ranked in their own band by D / effort.

**Counts in TEST-C?** The TEST-C protocol will run each repo's *documented command*, like TEST and TEST-B. Fixes to the recon/UI path (T15, T16) therefore change the product and the demo, not TEST-C.

| rank | id | fix (generic: a class of repos, not one repo) | B | U | D | effort | seal | counts in TEST-C | shares entries with |
|---|---|---|---|---|---|---|---|---|---|
| 1 | **T5** | a missing C header or compiler tool in a source build maps to the apt package that provides it, deterministically, labelled (`ft2build.h` → `libfreetype6-dev`, `png.h`, `jpeglib.h`, `yaml.h`, `ffi.h`, `openssl/ssl.h`, `which g++` → `build-essential` …); same mechanism as the existing D-24 compiler rule | 2 (gandissect, neo_gnns) | 1 | 2 | S | no | yes | T1 (gandissect), T14 / T6a (neo_gnns) |
| 2 | T15 | README-named scripts count as entrypoint candidates (D-52) | 1 (mud-pi) | 1 | 1 | S | no | **no** | — |
| 3 | T2 | a pre-release pin (`==X.Y.Za0`) the index does not serve becomes its final release, labelled a DEPENDENCY CHANGE; same mechanism as the R5 companion rule (`state.torch_overrides`) | 1 (ovis) | 0 | 1 | M (S if the override path needs no `runner_env.py` change) | maybe | yes | — |
| 4 | T3 | install-line repair: `git+git://github.com/` → `git+https://github.com/`; Debian package names removed upstream (`libgl1-mesa-glx` → `libgl1`); route "has no installation candidate" to the time machine instead of RUNTIME_ERROR_OTHER | 1 (video_prediction) | 0–1 | 1 | M | no | yes | T10 |
| 5 | T1 | a change that *moves the error* is progress, not a failure: it is not barred from retry and the adjudicator may adopt it. Today every non-winning candidate's changes go into `failed_moves` whenever its smoke run did not succeed (`orchestrator.py`, three `failed_moves.update` sites) | 1 (gandissect) | 1 | — | M | no | yes | **gate-adjacent, needs your yes (section 0)**; A = 3: gandissect, Hindsight, fb scraper |
| 6 | T11 | a documented command with a pipe runs under `bash -o pipefail` (sh here is dash, which has no pipefail); an exit-0 run with no output and a sub-second run time is "no evidence of work" and is not RUNS_CLEAN | 1 (adversary_critic) | 1 | 2 | M | **yes** (`smoke_exec.py` / run wrapper) | yes | T16 |
| 7 | T14 | PyG extension wheels (`torch-scatter`, `torch-sparse`, `torch-cluster`, `torch-spline-conv`) from `data.pyg.org` for the matched torch version, as a dated snapshot like the existing torch-wheel index | 1 (neo_gnns) | 1 | — | L | yes | yes | T5, T6a (neo_gnns) |
| 8 | T13 | MuJoCo 2.1 provisioning for `mujoco_py` repos: pinned, hash-checked download of the 2.1.0 binary to `~/.mujoco/mujoco210`, the apt libraries, `LD_LIBRARY_PATH`; labelled | 1 (Hindsight) | 1 | 1 | L | yes | yes | T1 |
| 9 | T6 | era-lock failures (5 of 21 entries). (a) build isolation for packages that need torch to build (`--no-build-isolation` / extra build deps): neo_gnns, cwn. (b) `exclude-newer` cut-off older than a build tool's floor (`exclude-newer-package` for setuptools / wheel): RBP. (c) the lock builds old sdists on the *host* Windows machine (a `C:\Users\…\easy_install-…` path is in the error): fashion-retrieval. (d) unsatisfiable set, message leaks the internal project name: fb scraper | 1 (neo_gnns; (b), (c), (d) are blocked behind other things) | 0–1 | 2 | M for (a)(b), L for (c) | no | yes | T14 |
| 10 | T16 | package CLIs: `python -m pkg` for a package `__main__`, and a no-argument CLI notice is not a run (D-50 + D-51 together) | 0 (turns a false success into an honest INDETERMINATE) | 0 | 1 | M | no | **no** | T11 |
| — | T9 | classification and stop-early for classes nothing in the loop can fix: `DOCKER_REQUIRED` (NeuralTracking), `CONDA_REQUIRED` (cwn), argparse rejection of the documented command (rocgan), NLTK/`Resource … not found` → DATA_MISSING with the licence hint (D-54, Ordered-Neurons), apt "no installation candidate" (video_prediction), "module not in repo and the only PyPI project of that name is unrelated or unbuildable" = missing vendored module (power_laws, RBP). Each gets a per-record next action, not a per-class sentence | 0 | 0 | **6** | M | no | yes | T10 |
| — | T10 | exact-line selection: never record pip's wrapper lines (`error: subprocess-exited-with-error`, `× Encountered error while generating package metadata`) or the exit hook's re-raise (`SystemExit: 2`) as the evidence; pick the first specific line (`fatal:`, `error:`, `ERROR:`, argparse's own message) | 0 | 0 | **3** (video_prediction, rocgan, gandissect's first error) | S | no | yes | T3, T9 |
| — | T19 | audit-readable records: keep a tail for exit-0 baselines, keep the whole `model_patch` (today truncated at 6000 chars), so an audit never has to infer from hashes (D-53) | 0 | 0 | 0 (supports audits of E-T18, E-TB6, E-T6) | S | no | yes | — |
| — | T17 | cost guard coherence: TEST #13 recorded $4.18 against a $2.50 entry cap. The operation was funded 256.8 s at $0.00779/s (about $2.00), killed after 241 s, and charged at the killed-step estimate rate $0.0152/s = $3.66 ESTIMATED [RECORD: `operations[2]`, `cost_events`]; the true cost was not reported. Fund seconds = remaining ÷ the estimate rate, so the estimate cannot exceed the cap | 0 | 0 | 0 (budget safety) | S | no | yes | — |
| — | T7 | patch re-indentation: when the model's `old` text starts without its indentation and carries wrong absolute indents, the whitespace-tolerant match applies `new` verbatim and the result does not parse. Re-base `new` onto the matched lines | 0 (both entries sit behind human-only blockers) | 0 | 0 | M | no | yes | D-47 residual |
| — | T8 | the repairer should see the file the documented command actually runs (resolved from the command and the traceback), not the recon guess; for a shell script, its text | 0 | 0 | 0 | M | no | yes | — |

**Overlap note.** neo_gnns needs a chain (T5, then T14 or T6a); it is counted once in the total, not once per fix. gandissect is fixed by T5 alone; T1 would also have let it through. After T5 ships, T1's incremental B is 0, and I would then drop it (see the cut line).

### 2.1 WONTFIX, with the reason

| entry | why not |
|---|---|
| TEST-B #1 Ordered-Neurons | licensed Penn Treebank data; the `test_*` protected-path rule is a gate-semantics item, excluded |
| TEST #1 power_laws | the repo omits a module it imports (diagnosis only) |
| TEST #2 NeuralTracking | needs docker |
| TEST-B #5 cwn | conda-only dependency, install script as the documented command |
| TEST #6 rocgan | README flag disagrees with the script (`--config` vs `--config_path`), plus MPI and CUDA |
| TEST #19 RBP | needs the README's `./setup.sh` building a `torch.utils.ffi` extension on PyTorch 0.4 (T12: running README setup steps; L, era-bound, low probability) |
| TEST #20 fashion-retrieval | pretrained file the user must supply |
| OOS fb scraper | Facebook login |
| OOS openstreetmap-heatmap | Blender of the script's era |
| OOS AutoDoc-ChatGPT | arguments and an OpenAI key |
| TEST-B #6 trees_from_transformers | the documented command is `--help` (corpus definition, not a defect) |

### 2.2 Proposed cut line

Time: today is Oct 7, the target is Oct 16. Phase 4 needs about 3 days (selection rule, preregistration, seal, one run, audit), Phase 5 about 1, so Phases 2–3 get about 4 days. At S = 0.5 / M = 1.25 / L = 3 days:

- **In (about 4 days):** T5, T3, T2, T11, T10, T9, T19, T17 (and T15 only if you want the product path in the same tag). One bundled seal for T11.
- **Decide:** T1 (needs your yes; after T5 it adds nothing for gandissect, so I recommend dropping it unless you want the Hindsight and fb progress cases covered).
- **Out for v1.8:** T13, T14, T6, T7, T8, T16 (L-sized or no run value on the 21; listed so they are not forgotten).

Expected effect on the 21, as DEV-labelled re-runs [JUDGEMENT, not a prediction of TEST-C]: gandissect, ovis, video_prediction and adversary_critic move past their recorded blocker; at most gandissect and adversary_critic have a realistic chance of a RUNS_* verdict. Diagnosis improves on about 9 entries.

## 3. Facts that correct published text (to be added *beside* the originals, never in place)

| where | what it says | what the records and checks show |
|---|---|---|
| `reports/test-b/TEST_B_RESULT.md`, #7 | "`mujoco_py` (MuJoCo, a licensed simulator binary) is not installable" | MuJoCo 2.1.0 binaries are free to download [CHECKED]; the blocker is a missing provisioning rule |
| same file, #1 | "NLTK's `ptb` corpus (the Penn Treebank sample)" | NLTK's downloadable `ptb` is a stub for the licensed full corpus; the free sample is `treebank` [CHECKED: NLTK index] |
| `reports/dev/TEST_RESULT.md` | #18 false positive, correctly stated | add: the D-46 second form (pipe) is T11 |
| `SCAN_OOS_v1.7.2.md`, D-47 | not in that file; the D-47 register line says the indentation case is fixed | the fix does not cover mid-line anchored edits [REPLAY] |

## 4. Inputs for later phases (noted now so Phase 2 does not close doors)

- **Phase 3 (diagnosis).** The record should carry `{blocker_class, error_line, next_action, basis}` per non-running entry; `next_action` is filled from the evidence (package, file, command), not from a per-class sentence. Draft rubric for "actionable": (1) the class is the right one, (2) the line is a verbatim line of the run's own stderr/stdout that names the cause, (3) the next action names a concrete artifact or command a researcher can act on. It must be committed before TEST-C and scored by a script plus a written key, not by me reading my own output. Rough baseline [JUDGEMENT, from the `fixable_by` reading in section 1.1, not yet from the rubric]: 5 of the 14 blocker records (E-T13, T20, TB2, TB3, TB8) have text I judge right. The real baseline comes from scoring DEV records with the committed rubric, never from me re-reading TEST records.
- **"Recovery rate" and "researcher hours saved" tiles.** Recovery rate can be computed from committed records. Researcher hours saved cannot: there is no committed measurement of hours, so any figure would be an assumption. Unless you give me an estimation method to commit and link, I will leave that tile out.
- **Phase 4 (TEST-C).** Use the same documented-command protocol as TEST-B so the numbers are comparable; the selection rule is the part I will write and commit first. A plain-text note: for TEST-C the headline pair is `RAN n of N` beside `actionable diagnosis m of N`, never merged.
- **Phase 5 (demo).** Genuinely passing cases with a gate-checked fix are in DEV, not in the 21. DEV #15 latent_ode: `RUNS_AFTER_REPAIR` in 5 harness versions, fix = a gate-checked environment change (`remove dataclasses`, the repo pins `dataclasses==0.8`), 4 attempts [RECORD]. DEV #14 M-FAC at v1.5.2: three code patches passed the gate and the adjudicated one ran (replace `torch.lu(pivot=False)`), but the same entry failed or timed out in rounds 4 and 5, so it is the weaker demo. I recommend #15 and will confirm in Phase 5.
- **Budget [RECORD].** Ledger $98.2478 of $300.00 API-reported; last BILLED reading $45.14. Printed worst case for the next paid phase will come from `reports/ledger_total.py --next-phase-cap-usd X` before each run.

## 5. What I need from you before Phase 2

1. Confirm reading 1 (the 21 as DEV-CONTAMINATED under v1.8, in their own folder) or tell me to avoid running them.
2. Confirm reading 2, and say yes or no to T1.
3. Approve the cut line, or move items across it.
4. Say whether T15 (product path) goes into the same v1.8.0 tag.
