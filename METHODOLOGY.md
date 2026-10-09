# Batch Lab methodology

This document describes how the 20-repo corpus in
[`backend/app/batch/corpus.yaml`](backend/app/batch/corpus.yaml) was selected, what its
results will and will not prove, and its known limitations — stated honestly, per
`RERUN_BUILD_DIRECTIVE.md`'s rule that the corpus is the project's decisive gate and
must never be silently shrunk or its scope quietly overstated.

## Status

**The corpus is assembled. The Batch Lab has not been run yet.** Executing it requires
a live Nebius Token Factory API key (`NEBIUS_API_KEY`) and Nebius Serverless Jobs, which
this environment does not have (see `DECISIONS.md`). Every claim below is about how the
20 repos were *chosen*, not about what RERUN found when it ran them — no verdict,
taxonomy code, or recovery rate for any of these repos should be treated as measured
until `batch_results.json` actually exists, is committed, and is loaded live by S4. If
you are reading this and `batch_results.json` is present, `S4` renders directly from
that file, not from anything asserted here.

## How the 20 were selected

Every candidate was verified to genuinely exist, live, via two independent real checks
performed during corpus assembly (2026-09-19), not assumed from memory or from an LLM
web-search summary:

1. `git ls-remote --exit-code <url> HEAD` — confirms the repo is public and reachable,
   and captures the exact commit SHA pinned in `corpus.yaml`.
2. A GitHub API root-directory listing — confirms which dependency files
   (`requirements.txt`, `setup.py`, `environment.yml`, `pyproject.toml`, or none at all)
   are actually present, rather than assumed from a repo's reputation.

One candidate an initial web search suggested (a repo whose description claimed a
`requirements.txt`) was found on direct inspection to have no dependency file matching
that claim at all, and one initially-selected repo (`facebookresearch/moco`) returned an
inconsistent/empty GitHub API listing during verification and was dropped in favor of
`google-research/simclr` rather than included on unverified faith. This is exactly why
every fact in `corpus.yaml` is sourced from a live check, not a description.

### Selection criteria (not a random sample)

The 20 were deliberately chosen to span, in the language of `RERUN_BUILD_DIRECTIVE.md`
§7 ("prefer repos spanning multiple failure modes... a corpus that's all clean or all
broken proves nothing"):

- **Era**: 2016 (`rllab`) through 2026 (`LinCIR`'s most recent push) — old TensorFlow 1.x
  code (`bert`, `gpt-2`) alongside actively-maintained modern repos (`fairseq`,
  `detectron2`).
- **Dependency declaration style**: some `requirements.txt`, some `setup.py` /
  `pyproject.toml`, and several with **no machine-readable dependency file at all**
  (`nanoGPT`, `LinCIR`, `nxtp`, `awd-lstm-lm`) — confirmed by direct inspection, not
  assumed just because they're old.
- **Entrypoint clarity**: from a single obvious `train.py`, to genuinely ambiguous
  multi-entrypoint monorepos (`pytorch/examples`, `minGPT`) included specifically to
  stress-test recon's calibrated abstention (§6.1) — an `INDETERMINATE` verdict on
  `pytorch/examples` would be the *correct* outcome, not a failure of the tool, unless
  recon has a real way to disambiguate.
- **Popularity/attention spread**: from 40k+-star canonical repos (`bert`) to single-digit-star
  academic releases (`TTPT`, 3 stars) — reproducibility tooling is usually only
  demonstrated against famous repos; most real paper code looks like the low-star end.
- **Framework**: mostly PyTorch, with one TensorFlow entry (`simclr`) so the corpus
  isn't accidentally PyTorch-only despite RERUN v1's framework-agnostic scope.
- **Resource assumptions**: `detectron2` is included specifically as a likely
  `GPU_REQUIRED` candidate, since its install docs and demos generally assume a CUDA
  GPU RERUN's CPU-only sandbox won't have — naming that boundary explicitly (§5.2) is
  the point, not a defect.

None of the per-repo `selection_note` entries in `corpus.yaml` predict which taxonomy
code or verdict a repo will actually receive — that would be presenting a guess as a
measurement. They explain why each repo is a *structurally interesting* candidate for
diversity.

## What SMOKE-level reproduction does and does not prove

Per the project's scope boundary (`RERUN_BUILD_DIRECTIVE.md` §1): RERUN verifies that a
repo's entrypoint **executes** — exit code 0 plus non-trivial stdout — after RERUN's own
environment synthesis and, if needed, a gate-approved minimal patch. It does **not**
verify that the paper's reported numerical results are reproduced. A `RUNS_CLEAN` or
`RUNS_AFTER_REPAIR` verdict on any corpus entry means "the code ran," never "the paper's
claims are correct." This applies to every number the Batch Lab ever reports, including
the headline Reproducibility Recovery Rate (§6.2).

## Known limitations

- **N = 20 is small.** It is large enough to show a spread across taxonomy codes, not
  large enough to support a statistically rigorous claim about "the field's"
  reproducibility rate. The corpus is a demonstration sample, not a survey.
- **Selection is not random.** Repos were chosen by a human(-directed) process aiming
  for structural diversity, not drawn uniformly from all published paper code. This
  likely *understates* true breakage relative to a purely random sample, since every
  entry here was at least popular/visible enough to be found via search or general ML
  community knowledge — the long tail of never-cited, never-starred repos is not
  represented.
- **Commit pinning vs. shallow clone.** `corpus.yaml` pins an exact commit SHA per repo
  at assembly time, but `intake.py`'s current `clone_repo()` does a shallow clone of the
  default branch's *current* HEAD, not an arbitrary pinned SHA. If a repo is pushed to
  between corpus assembly and the actual Batch Lab run, `batch/runner.py` (not yet
  built) must explicitly fetch and check out the pinned SHA rather than relying on a
  plain shallow clone of HEAD — this is a real implementation requirement, not yet
  solved, logged here so it isn't silently glossed over when the runner is built.
- **If the corpus size ever changes**, `RERUN_BUILD_DIRECTIVE.md`'s cut ladder requires
  reporting the real N everywhere it's shown, never presenting a shrunk corpus as if it
  were still 20. `backend/app/batch/corpus.py::load_corpus()` and its test suite
  (`test_corpus_loads_with_exactly_twenty_entries`) will need updating in lockstep with
  any such change — the test failing on its own is the intended signal.


## corpus-v1 — pre-registered selection rule (registered 2026-09-24, before the draw)

The original 20-repo corpus (`backend/app/batch/corpus.yaml`, now "corpus-v0") was a
hand-picked diversity set, not a sample. corpus-v1 replaces selection-by-judgment with
a rule fixed **before** any repository was looked at. The full machine-readable version is
[`backend/app/batch/corpus_v1/prereg.json`](backend/app/batch/corpus_v1/prereg.json),
executed by [`scripts/draw_corpus.py`](scripts/draw_corpus.py); both were committed before
`draw` ran, and the draw refuses to run if the population file or its regexes differ from
the registration.

**Source of paper→code links.** The Papers with Code archive on Hugging Face
(`pwc-archive/papers-with-abstracts` @ `459480aeac58509a93f5af2acd4adf20236ce8d9`,
`pwc-archive/links-between-paper-and-code` @ `56cc5c1938678c33dedebf5f74fc4e62e2c35381`).
Why: it was the standard index of papers to their code, it records each paper's venue
(`proceeding`) and whether a code link is the authors' own (`is_official`), and — with
paperswithcode.com shut down — its last public snapshot at a pinned revision is the most
reproducible frame available. Accessed with DuckDB over `hf://` parquet using column
projection and pushed-down filters; the full files are not downloaded.

**Frame (population).** Papers whose `proceeding` is a main-track NeurIPS/NIPS, ICML or
ICLR label for 2018–2022 (`^(NeurIPS|NIPS|ICML|ICLR) (2018|…|2022)( <month>)?$`) with an
`is_official` link to a `github.com/<owner>/<repo>` URL; one row per paper (smallest
official repo URL if several), sorted by `paper_url`. **5,485 papers** (population.csv,
sha256 `ec825aac…`). **Known coverage bias, stated rather than corrected:** the archive's
main-track labels are very uneven — ICML 2019 (1), ICML 2021 (1), ICML 2022 (3) and NeurIPS
2022 (7) are nearly absent — so the frame is effectively ICLR 2018–22, NeurIPS 2018–21 and
ICML 2018/2020.

**Eligibility (screened in draw order, automatically):** E3 the repository is reachable
(`git ls-remote HEAD`; that HEAD is pinned as the commit); E4 GitHub's primary language is
Python; E5 the root README documents a run command — the first line (in reading order)
of the form `python|python3|bash|sh <script>.py|.sh` or `python -m <module>`, optionally
prefixed by `VAR=value`, whose script/module exists at the pinned commit and which contains
no placeholder (`<…>`, `{…}`, `/path/to`, `YOUR_`, `xxx`, `...`). That line is recorded
verbatim as the corpus command (ground truth for "runs"). CPU feasibility, runtime and
data availability are **not** screened — they are what RERUN measures. Limitation: only the
root README is searched (not docs/), to keep the check deterministic and within GitHub's
unauthenticated API budget.

**Draw.** Seed **20260924**; `random.Random(seed).shuffle` over population indices;
screen in that order; skip a repository already drawn for another paper; stop at **20**
eligible (or report the achieved N if the frame is exhausted). No manual exclusions or
replacements. Every draw is logged with its pass/fail reason in `screening_log.jsonl`.

**Freezing.** `corpus_hash` = sha256 over canonical JSON of {prereg sha256, entries (name,
repo_url, commit_sha, command) sorted by name}; written into corpus.yaml and
corpus_hash.txt, tagged `corpus-v1`, and carried into every run's passport (bundle v3
`corpus_hash`). Any change is a new corpus version; results from different versions are
never mixed. All corpus-v1 files are protected paths in the tamper gate.

### corpus-v1 — draw result (2026-09-24)

Drawn exactly as registered: **59 draws → 20 eligible** (E4 not Python: 15 — Jupyter
Notebook 9, C++ 3, Julia/MATLAB/R 1 each; E5 no runnable documented command: 24; no E3
failures, no duplicates). `corpus_hash` **063b700c38006bcf3160c64674a196cdf2fddb768a0c3de232746181aeef7d5c**
(independently recomputed), tag `corpus-v1`. Every draw with its reason:
`backend/app/batch/corpus_v1/screening_log.jsonl`. Venue-years drawn: ICML 2020 ×4,
ICLR 2020 ×3, ICML 2018 ×3, NeurIPS 2018/2021 and ICLR 2021/2022 ×2 each, NeurIPS
2019/2020 ×1.

**Post-draw review — a weakness of the registered E5 rule, reported, not corrected.** E5
accepted the *first* README line that invokes an existing script, which is not always a
command that *runs the paper's code*. Manual reading of the 20 recorded commands: **12 are
ready-to-run** (#1, 2, 4, 5, 7, 8, 9, 11, 12, 15, 16, 20); **8 are not**: an install step
(#6 `python setup.py install`), a data download (#13 `bash download.sh`), preprocessing
(#3 `preprocess.py`, #14 `process.py`, #18 `data/basketball/read_raw.py`), a setup script
(#19 `tools/pre_run.sh`), and unfilled placeholders the regex didn't catch (#3 `$TEXT`, #10
`CONF_FILE`/`LOG_DIR`, #17 `[ellipse|sawtooth|…]`, #18 `$RAW_DATA_DIR`). Because the rule
was pre-registered, corpus-v1 is left exactly as drawn — changing entries after seeing
them is precisely what pre-registration forbids. For a corpus-v2 registration: exclude
`setup.py`/install/download/(pre)process/setup-named scripts, treat `$VAR`, `[a|b]`
choice lists and ALL-CAPS argument values as placeholders, and pick the first
*remaining* command. Whether the Batch Lab runs corpus-v1 as registered (reporting the 8
as their own category) or a re-registered corpus-v2 is a decision for the human; the batch
has not been run.

## Taxonomy note — `SYS_LIB_MISSING` covers missing system tools/binaries

The code keeps its historical name (certificates already issued carry it), but since
2026-09-28 it covers **any missing system dependency**: shared libraries and headers as
before, **and** missing system tools/binaries (git, gcc, make, cmake, nvcc, wget, …; the
fixed list is `classifier.SYSTEM_BINARIES`). The binary forms are pip's `Cannot find
command '<x>'`, `/usr/bin/env: '<x>': No such file or directory`, `executable file not
found in $PATH`, and — only for names on the fixed list — `<x>: command not found`,
`sh: N: <x>: not found` and `[Errno 2] No such file or directory: '<x>'`. A missing
repository-local script or helper (`./train.sh: No such file or directory`, `run_exp:
command not found`) is **not** a system dependency and never gets this code; a missing
data file stays `DATA_MISSING`.

## corpus-v1 — amendment 1: pre-results analysis amendment (registered 2026-09-28)

Decision: corpus-v1 is **run exactly as registered and drawn** — all 20 entries, their
pinned commits and recorded commands, unchanged. This amendment changes only how the
results are **analysed and reported**, and it was committed **before the batch started**
and before the harness was frozen (the `harness-v1` tag is on the amendment's own commit).
Machine-readable: [`backend/app/batch/corpus_v1/amendment-1.json`](backend/app/batch/corpus_v1/amendment-1.json),
sha256 `63d409a3ffc92b016fde502b90e53500a48287b7a286c7078148ac3650b9622d` (also in
`amendment-1.sha256` and pinned in `scripts/run_corpus_v1_batch.py`, which refuses to
start if any of the three disagree).

**No outcomes observed.** At classification time no corpus-v1 entry had been executed by
RERUN — no baseline, repair or verdict for any of the 20. The classification reads only
the command strings in `corpus.yaml`. The only live runs since the draw are development
runs of TTPT (`dev_run: true`), which is not a corpus-v1 entry.

**Primary endpoint = the 12 genuine run commands:** entries **#1, 2, 4, 5, 7, 8, 9, 11,
12, 15, 16, 20** (neuroailab/Neural-Alignment, bluer555/KernelGCN,
Lucas2012/ProbabilisticNeuralProgrammedNetwork, expressGNN/ExpressGNN,
bgleon/latent-goal-architectures, lissomx/MSP, YuchenJin/autolrs, danecor/VaST,
kcyu2014/eval-nas, zhuchen03/VIBNet, ElementAI/osaka, slowbull/DDG). The recovery rate
and every headline number are computed over these 12 only.

**`COMMAND_NOT_A_RUN` = the other 8:** **#3, 6, 10, 13, 14, 17, 18, 19**. They are
executed exactly like the primary entries (same frozen harness, same $2 cap), reported
separately, and **never counted in the recovery rate** or any headline number.

**Classification rules** (`backend/app/batch/command_rules.py`, applied identically to
every entry; an entry is `COMMAND_NOT_A_RUN` if ANY rule matches). The *target* is the
first `python|python3|bash|sh <path>.py|.sh` or `python -m <module>` after optional
`VAR=value` assignments; the *stem* is the script's file name without extension (or the
module's last component), matched case-insensitively; *args* are the shell-split words
after the target, matched case-sensitively.

| Rule | Tests | Regex |
|---|---|---|
| R1_INSTALL | stem, or any arg | stem `^(setup\|install)$`; arg `^(install\|develop)$` |
| R2_DOWNLOAD | stem | `download` |
| R3_PREPROCESS | stem | `^(pre_?)?process` |
| R4_SETUP_SCRIPT | stem | `^(pre_?run\|prepare\|setup_\|init_?env)` |
| R5_PLACEHOLDER | any arg | `\$\{?[A-Za-z_]` or `\[[^\]]*\|[^\]]*\]` or `(?:^\|=)[A-Z]+(?:_[A-Z]+)+$` |

Result: #3 R3+R5 (`preprocess.py`, `$TEXT`), #6 R1 (`setup.py install`), #10 R5
(`CONF_FILE`, `LOG_DIR`), #13 R2 (`download.sh`), #14 R3 (`process.py`), #17 R5
(`[ellipse|sawtooth|…]`), #18 R5 (`$RAW_DATA_DIR` — the manual review called it
preprocessing; R3 does not match `read_raw`, R5 catches it), #19 R4 (`pre_run.sh`). The
rules reproduce the manual post-draw review **entry by entry** (tested, and
`scripts/write_amendment.py` refuses to write the amendment if they don't). R5's
ALL-CAPS test requires an underscore so real values such as `TTL2` (#7) and `D4` (#15)
are not placeholders (tested; loosening it fails #7 and #15).

**Reported for the 12:** failed as published (baseline `FAILS`) / `RUNS_AFTER_REPAIR`
(baseline `FAILS` and final `RUNS_AFTER_REPAIR`) / `BLOCKED` by taxonomy code /
`INVALID_HARNESS` (RERUN's fault, excluded from the rate); deterministic vs
model_assisted among the recovered; total spend. Headline: `PRIMARY: <recovered>/<failed
as published> of 12`.

## Harness changes discovered during the corpus-v1 batch (harness-v1 → harness-v1.1, 2026-09-28)

**corpus-v1 is therefore a disclosed development set, not a blind measurement.** Its
batch on `harness-v1` was stopped after 3 of 20 entries because the harness itself failed
in ways that were recorded as, or distorted, verdicts about repositories. Those three
records are void (kept in `runs/corpus_v1_batch/void_harness-v1/`, with a README). The
fixes below were made after seeing them, so corpus-v1 results on `harness-v1.1` are
reported in full but are not a blind test of the harness. **corpus-v2 is the blind
measurement:** pre-registered and sealed in the same commit as these fixes, drawn after
the seal, and run on `harness-v1.1` with no harness change at all. If corpus-v2 exposes a
harness bug it is recorded, not fixed, and its batch stops.

Every fix is generic: none names a repository, and every one has tests and a mutation
check (18 mutations, all caught).

| Fix | Exposed by | What changed |
|---|---|---|
| **(a) External failures are INFRA_ERROR** | #2 KernelGCN (sandbox upload timeout → `NOT_ATTEMPTABLE`), #3 knnlm (upload + model API timeouts) | New `app/services/infra.py`: one retry policy (bounded exponential backoff, 2 s/4 s/8 s, 4 attempts) for transient failures; a persistent or non-transient external failure raises `InfraError`, which no stage fallback may catch. The run ends with verdict **`INFRA_ERROR`** (reason `INFRA_ERROR:<source>:<cause>`), a RERUN's-fault code excluded from every denominator. Audited paths, each tested with an injected failure: Nebius sandbox API (all errors except our own wall-clock ceiling), model API at recon/planner/repairer/adjudicator (timeouts, connection, 429/5xx; 401/403/404 immediately), GitHub (era lookup, resolver verification; 403 rate limit immediately), the package index (resolver, `uv` lock), and the git host (clone). `NOT_ATTEMPTABLE` can no longer come from a sandbox error; a wall-clock overrun is still `TIMEOUT`; any other sandbox error is RERUN's bug (`PIPELINE_ERROR`). Tavily stays non-fatal by design (cited enrichment only). |
| **(a) One-archive upload** | #2, #3 | The SDK uploaded every file as its own POST, all concurrently. The repository is now sent as one tar; the first sandbox step extracts it and **verifies every file against a manifest** (git blob SHA-1 of the exact bytes sent + file mode), then removes RERUN's files. A mismatch → `INVALID_HARNESS`. The local pre-upload gate (bytes == pinned commit) is unchanged. Live smoke test on Nebius before the seal: verified, $0.0009. |
| **(m) Git file modes** | (review of the upload path) | The per-file upload made every file 0644, so `./run.sh` could never run. Archive modes now come from the pinned commit (`git ls-tree`: 100755 → 0755, 100644 → 0644) and are part of the post-extraction check. Round trip tested on a Linux filesystem (WSL): an executable `./run.sh` runs; a mode or content mismatch exits 97. |
| **(b) Import → distribution** | #1 Neural-Alignment (`absl` sent to the resolver instead of `absl-py`) | Three hand-written tables replaced by one table built by `scripts/build_import_map.py` from cited sources, each verified by sha256: pipreqs 0.5.0's curated `mapping` (Apache-2.0, vendored with its license), pigar 2.2.0's PyPI-derived module→distribution database (BSD-3, build time only), and hugovk/top-pypi-packages (2026-09-01; no license declared, so used at build time only and not redistributed). Rule: pipreqs entry; else the most-downloaded of {the name itself} + pigar's providers, never an unranked candidate (pigar lists squatters, e.g. `absl` → `mis-modulos` first); else unchanged. **Hardware/CUDA variants are never chosen** (one pattern: `cuda`/`cuXXX`/`gpu`/`cpu`/`rocm`/`tpu`/`xpu`/`metal`/`directml`/`mkl`/arch tokens, `cupy*`, `nvidia-*`, `jax-cuda*`, `jaxlib-*`), so `cupy`, `faiss` and `onnxruntime` stay unmapped. A row is **low-confidence** when a same-named project provides the import but is unranked and a differently named one was chosen (`clip` → `openai-clip`; also `skimage` → `scikit-image`; 1,413 of 5,300 rows). Low-confidence rows are still applied but flagged. Local modules are excluded before any mapping, which limits the risk from generic names such as `src`. Every mapping used is recorded in the certificate: structured in the era record (`import_mappings`: import, distribution, source, confidence) and as `[import-map]` log lines. The env gate's reverse table (distribution → import, used only to refuse removing an imported package) is unchanged. |
| **(c) Classifier evidence** | #1 (evidence was pip's `[notice]` line) | When no rule matches: skip noise lines (`[notice]`, `WARNING:`, `DEPRECATION:`); prefer the last Python exception line, then the last line with an error marker, then the last remaining line. Regression on #1's real log: `RuntimeError: Python version 2.7 or 3.4+ is required.` |

**Batch driver.** The required tag is configurable (`--harness-tag`, default
`harness-v1.1`). The **tag-or-descendant preflight** lets the corpus-v1 results and the
corpus-v2 draw be committed without moving the harness, and refuses to start unless:
- the working tree is clean (only untracked output of this batch is tolerated, for resume);
- the tag exists, origin has it at the same commit, and HEAD is that commit or a
  descendant of it;
- every path in `git diff --name-only <tag>..HEAD` matches the **data allowlist**:
  `runs/…`, `DECISIONS.md`, `METHODOLOGY.md`, and corpus-v2's draw outputs
  (`screening_log.jsonl`, `corpus.yaml`, `corpus_hash.txt`);
- a **hash check** that is independent of the allowlist passes: the git blob of every
  harness file (`backend/app`, `backend/pyproject.toml`, `scripts`, `frontend/src`,
  `.gitattributes`) and every sealed file (the corpus-v1 pre-registration, corpus and
  amendment; the corpus-v2 pre-registration and its sha256) is identical at HEAD and at
  the tag;
- the amendment / pre-registration sha256 and the recomputed corpus hash match.

Tested against a real temporary git repository with a bare origin. **Circuit breaker:** 2
consecutive `INFRA_ERROR` verdicts stop the batch cleanly. Caps unchanged: $2 per entry,
$40 per batch.

## corpus-v2 — PRE-REGISTRATION (registered 2026-09-28; sealed in harness-v1.1; not drawn)

Sealed in the `harness-v1.1` commit, **before any corpus-v2 candidate was screened**.
Machine-readable: [`backend/app/batch/corpus_v2/prereg.json`](backend/app/batch/corpus_v2/prereg.json),
sha256 `fc100dde4e0bcdd55614c506b7e64a38dc792326de935219ea7d19806f13dbcc` (also in
`corpus_v2/prereg.sha256`).

- **Same as corpus-v1:** datasets and pinned revisions, frame, `population.csv` (5,485
  papers, sha256 `ec825aac…`), eligibility E1–E4, the draw/duplicate/stop procedure,
  target 20.
- **New seed: 20260928** (the registration date, the same convention as corpus-v1's 20260924).
- **Tightened command rule (E5_v2).** corpus-v1's E5 took the first README line invoking
  an existing script, which admitted install, download, preprocessing and setup steps and
  unfilled placeholders (8 of 20; amendment 1). E5_v2 applies corpus-v1's E5 unchanged
  and additionally skips every candidate line matching any amendment-1 rule
  (`command_rules.matched_rules`: R1 install, R2 download, R3 (pre)process, R4 setup
  script, R5 placeholder: `$VAR`, `[a|b]` choice lists, ALL_CAPS_WITH_UNDERSCORE values).
  The **first remaining** line whose script/module exists is the corpus command, so every
  corpus-v2 command is a run command by construction and all drawn entries are the
  primary endpoint.
- **Fresh sample:** corpus-v1's 20 papers and repositories are skipped as duplicates (logged).
- **Draw:** `scripts/draw_corpus.py draw-v2`, sealed with the pre-registration. It refuses
  to draw unless the pre-registration's sha256, the population's sha256, its E5 regexes
  and `command_rules`' exclusion regexes all equal the registered values.
- **Run:** on `harness-v1.1` with no harness change (the batch preflight enforces it). A
  harness bug found by corpus-v2 is recorded, not fixed, and the batch stops.

## Re-queue rule for INFRA_ERROR (operational; registered 2026-09-28, before resuming)

An entry whose run ended **INFRA_ERROR with no baseline execution** (baseline `NOT_RUN`:
nothing of the repository ran, so no outcome about it was observed) is **re-queued, at
most 2 times**. Its record is moved, unmodified, to the batch's `void_infra/` folder with
a note of the re-queue attempt, and the resumed batch (same harness tag, same caps, same
circuit breaker) runs it again. After a second re-queue that still ends INFRA_ERROR, the
entry **stays INFRA_ERROR permanently** and is excluded from the denominator (reported as
such). An INFRA_ERROR after a baseline ran is not re-queued. The rule is mechanical and
applies identically to corpus-v1 and corpus-v2. First application: corpus-v1 #5
ExpressGNN and #6 SearchFair (sandbox upload read timeouts during a transient Nebius
outage; re-queue attempt 1 of 2).

## Known limitations (harness-v1.1, recorded not fixed)

- **Era lock: "no versions" sinks the whole lock.** `time_machine.compile_lock` drops an
  input only when uv reports it "was not found in the package registry". When uv instead
  reports "there are no versions of X" (the name exists on PyPI but has no installable
  version for the era, or is a different project), the whole era lock fails and the run
  continues without the era environment (model repairs only). Affected so far (corpus-v1 on
  harness-v1.1): **#1 neuroailab/Neural-Alignment** (`tfutils`, the lab's own library, not
  installable from PyPI in 2020) and **#4 Lucas2012/ProbabilisticNeuralProgrammedNetwork**
  (`torch==0.4.0`, no longer installable from PyPI). Present since harness-v1; not fixed
  because the harness is frozen for both corpora.
- **Retry window vs. real outages.** The sealed retry policy waits 2 s, 4 s and 8 s (4
  attempts, about 14 s); a Nebius outage longer than that ends the entry INFRA_ERROR (handled
  by the circuit breaker and the re-queue rule above).

## Upload cap — pre-registered live probe (registered 2026-09-28, before probing)

harness-v1.2 ends a run whose upload archive exceeds a fixed cap with verdict
`UPLOAD_TOO_LARGE` (a harness limitation, excluded from every rate, reported separately).
Nebius documents **no** upload or file-size limit: the upload endpoint's API reference
(docs.tokenfactory.nebius.com/api-reference/sandboxes/files/upload-a-file-to-the-server-the-body-must-be-a-file-content),
the Sandboxes limits page (docs.tokenfactory.nebius.com/sandboxes/overview: only "50"
concurrent operations and 180-day checkpoint retention), the SDK Files Manager reference
and the CLI files tutorial state none (checked 2026-09-28). The cap is therefore set by
this probe, fixed **before any harness-v1.2 run** and independent of every corpus entry:

- `scripts/smoke_upload.py probe`: synthetic, incompressible archives (seeded random
  bytes in 50 MB files, seed 20260928) of **150 MB and 500 MB** (decimal), uploaded in
  that order through RERUN's real sandbox client with the harness-v1.2 transport timeout
  (`max(60 s, size_MB / 1 MB/s + 30 s)`), extracted and verified in a real sandbox.
- **Cap = the largest probed archive that uploads and verifies.** If 500 MB fails, the
  cap is the 150 MB archive; if 150 MB fails, no cap can be set and the work stops.
- The probe record (sizes, seconds, effective throughput, cost) is committed in
  `runs/upload_probe/`, and the cap constant is set from it in the harness-v1.2 seal.

### Upload cap probe — amendment 1 (registered 2026-09-28, after the first probe, before any new probe upload)

The first probe (record `runs/upload_probe/probe_2026-09-28.json`) failed at its smallest
size: the 150 MB archive **uploaded** (scaled transport timeout 180 s held; 254 s in total,
0.59 MB/s effective) but the sandbox operation then failed with `OSError 28 'No space left
on device'`, while `df` inside a sandbox shows a shared ~47 TB root filesystem. So some
per-instance storage limit, not documented by Nebius, applies; the extract step kept the
archive and the extracted tree on disk at the same time (~2× the archive). Per the rule,
no cap was set and work stopped. Amended rule (human decision), replacing the sizes above:

1. **Extract step:** the archive is deleted immediately after extraction, *before* the
   manifest check (`tar -x … && rm -f <archive> && python3 verify.py && rm -rf <dir>`);
   the check reads only the extracted tree (tested: command order; a real Linux round
   trip where the archive is gone and a tampered file is still caught).
2. **Sizes, pre-declared:** **25, 50, 75, 100, 125 MB** (decimal; incompressible seeded
   synthetic data, seed 20260928), ascending, **stopping at the first failure**. **Cap =
   the largest passing size.** If 25 MB fails: stop, no cap.
3. **Recorded per step:** upload time (`apply_files`), effective upload MB/s, extract+verify
   time, the extracted tree size (`du`) and `df` (a true per-instance peak is not measurable
   from inside the sandbox: `df` shows the shared root filesystem), cost, and the error
   text on failure.
4. **Timeout constant from the probe:** `UPLOAD_MIN_THROUGHPUT_MBPS = 0.5 × the slowest
   measured upload MB/s among passing steps`; the transport timeout stays
   `max(60 s, size_MB / UPLOAD_MIN_THROUGHPUT_MBPS + 30 s)`, reported at the cap size.
5. **Pre-batch smoke test** = a small upload + an upload at the cap size.

Nebius has been asked for the documented limit in parallel; the probe does not wait for it.

### Upload cap — result (probe re-run 2026-09-29, `runs/upload_probe/probe_2026-09-29_amendment1.json`)

All five pre-declared sizes passed (upload, extract + verify, payload), none failed:

| Archive | Upload | Upload MB/s | Extract + verify | Cost |
|---|---|---|---|---|
| 25.0 MB | 9.5 s | 2.62 | 0.12 s | $0.0021 |
| 50.0 MB | 18.4 s | 2.72 | 0.18 s | $0.0030 |
| 75.0 MB | 38.0 s | **1.97** (slowest) | 0.22 s | $0.0034 |
| 100.0 MB | 33.3 s | 3.00 | 0.28 s | $0.0041 |
| 125.0 MB | 47.2 s | 2.65 | 0.31 s | $0.0043 |

**Cap = 125,009,920 bytes** (the largest passing size). **Assumed throughput = 0.5 × 1.973 =
0.987 MB/s**; transport timeout = `max(60 s, size_MB / 0.987 + 30 s)` = **156.7 s at the cap**.
The voided first run of amendment 1 (a payload bug in the probe itself) was not used. Every
script that runs on Nebius is first dry-run locally under WSL (`scripts/wsl_dryrun.py`:
the real archive, extraction, check and payload on a Linux filesystem); the probe's dry run
found and fixed a crash in the probe's own summary code before the live run.

## Harness changes v1.1 → v1.2 (sealed 2026-09-29)

**Exposed by** corpus-v1 on harness-v1.1: #6 SearchFair (30.6 MB archive) and #5 ExpressGNN
(125.6 MB) failed identically twice with `INFRA_ERROR:sandbox:ApiTimeoutError` while small
smoke uploads passed. Root cause: the Nebius SDK's HTTP `transport_timeout` was never set, so
its silent default of **10 s** applied to every upload. All harness-v1.1 corpus-v1 records
are void (`runs/corpus_v1_batch/void_harness-v1.1/`, README; #2 KernelGCN's
RUNS_AFTER_REPAIR noted as valid but superseded). corpus-v1 is re-run, all 20, on v1.2.

1. **Timeout audit** (`backend/app/services/timeouts.py`): every client/SDK/subprocess
   timeout is an explicit sealed constant; none relies on a silent default. Before → now:
   sandbox HTTP 10 s (SDK default) → scaled to the archive (below); sandbox operations
   1000 s (SDK default) → explicit 1000 s; model API connect 5 s / read-write-pool 600 s
   (SDK default) → explicit 10 / 600 / 60 / 60 s; Tavily 60 s (library default) → explicit
   60 s; GitHub/PyPI 15 s, git fetch 300 s, git local 30 s, `ls-tree` 60 s, `uv` 300/30 s,
   sandbox cleanup 30 s — unchanged, now named constants.
2. **Transport timeout scaled to the archive**: `max(60 s, size_MB / 0.987 MB/s + 30 s)`;
   the throughput constant comes from the probe (above).
3. **Pre-declared upload cap**: archives over **125,009,920 bytes** end with verdict
   **`UPLOAD_TOO_LARGE`** before any network call — a harness limitation, RERUN's fault,
   excluded from every rate and reported separately. Nebius documents no limit; the cap is
   set by the pre-registered probe (above), not by any corpus entry.
4. **Extract step**: the archive is deleted immediately after extraction, before the
   manifest check (the first probe hit an undocumented per-sandbox storage limit with
   archive + tree on disk).
5. **Pre-batch smoke test** (enforced by the batch driver; recorded in the batch folder):
   a small upload + an upload at the cap size; a failure refuses the batch.
6. Tests: `test_harness_v12.py` (timeout formula pinned to the probe's constants, explicit
   SDK/model/Tavily timeouts, cap before any network call, `UPLOAD_TOO_LARGE` verdict, archive
   deleted before the check with a real Linux round trip, the probe payload under `sh`);
   **9/9 mutations caught** (e.g. fixed 10 s transport timeout → 9 tests red).

**corpus-v2 re-sealed** for v1.2: only its harness reference changed (v1.1 → v1.2, in
`status`, `harness` and the exclusion-rules implementation note); seed, frame, rules and
exclusions unchanged; `prereg.json` carries `amendment_1` stating that nothing from corpus-v2
was drawn or observed before the change (new sha256 in `prereg.sha256`).

**Freeze.** No harness changes after `harness-v1.2`. A further defect is recorded under
Known Limitations and the batch continues — **unless** it attributes a failure to a
repository that is not the repository's fault; only that class stops a batch.

## Re-queue rule — amendment (registered 2026-09-29, before any harness-v1.2 run)

Re-queue applies **only to transient failures**. A failure that **repeats identically on
the same entry after a successful smoke test** is a **deterministic harness defect**: the
batch stops and the entry is **not** re-queued (it is handled as a harness change or a
Known Limitation, never as an outage). This is what the harness-v1.1 upload timeouts were.

## Known limitations (harness-v1.2 additions)

- **Upload cap 125,009,920 bytes.** Larger repositories end `UPLOAD_TOO_LARGE` and are not
  measured (reported separately). Repositories that ship large datasets are therefore
  systematically unmeasured in both corpora.
- **Per-sandbox storage limit is undocumented.** The first probe hit `OSError 28 'No space
  left on device'` at 150 MB (archive + extracted tree), while `df` inside the sandbox shows
  a shared ~47 TB root filesystem; a true per-instance peak is not measurable from inside.
  A repository whose install or run writes a lot to disk may hit it (reported as the error).
- **Local WSL dry runs** exercise RERUN's own wiring, not the sandbox image (the host's
  Linux, not `python:X-slim`), so their verdicts are meaningless and never recorded as runs.

## corpus-v1 on harness-v1.2 — result (2026-09-29; disclosed development set)

All 20 entries, from scratch, on `harness-v1.2` (`668c907`): pre-batch smoke test passed
(small + 124 MB); no circuit-breaker stop; total spend **$8.53** of the $40 cap. Records:
`runs/corpus_v1_batch/harness-v1.2/` (`summary.json`).

**PRIMARY (the 12, amendment 1): 1 recovered of 10 that failed as published (n measured = 10
of 12).** No primary entry ran as published. Recovered: #2 bluer555/KernelGCN
(RUNS_AFTER_REPAIR, deterministic: era environment only, no model, no code change; 200
training epochs and a printed test accuracy; tree and passport verified). BLOCKED by reason:
RUNTIME_ERROR_OTHER 4 (#11 VaST, #12 eval-nas, #15 VIBNet, #20 DDG), DEP_YANKED 2 (#4, #16
osaka), DEP_NOT_ON_PYPI 1 (#1 Neural-Alignment, `tfutils`), DEP_MISSING 1 (#9 autolrs),
DATA_MISSING 1 (#8 MSP). Not measured (RERUN's side, excluded): #5 ExpressGNN
`UPLOAD_TOO_LARGE` (125.6 MB > 125.0 MB cap), #7 latent-goal-architectures `INVALID_HARNESS`.
Repair mode among the recovered: deterministic 1, model-assisted 0.
**COMMAND_NOT_A_RUN (the 8, never counted):** RUNS_CLEAN 1 (#13 igeood's `download.sh`),
BLOCKED 5, TIMEOUT 2 (#10 alf, #17 neural-flows).

### Known limitations found during this batch (recorded, not fixed — harness frozen)

- **#7: the local checkout's `.git` became unreadable mid-run** (`fatal: not a git
  repository` before repair 2, after the same 84 files had verified twice). The integrity gate
  correctly voided the run (`INVALID_HARNESS`, RERUN's fault, excluded); cause on the host not
  determined.
- **Cost of timed-out sandbox steps is not reported** by Nebius (#10 $0.0025, #17 $0.0069 for
  runs that used the full 600 s wall clock), so total spend is under-reported for TIMEOUTs.
- **Recon is skipped for large repositories**: #10 alf's recon prompt (~108.7k tokens)
  exceeded the 20k per-attempt token ceiling (`RECON_MODEL_ERROR`); the run proceeded with the
  documented command, as designed, without recon's eval/model names.
- **Python 2 code is not attemptable as such**: #20 DDG fails with `SyntaxError` (Python 2
  syntax); it is classified RUNTIME_ERROR_OTHER and routed to code repair (the model's three
  diffs were all rejected by the tamper gate); the sandbox supports Python ≥ 3.6 only.
- **Wall clock 600 s includes the install**: #10 and #17 timed out inside the repository's
  own dependency install; a genuine TIMEOUT under the pre-registered ceiling, but heavy
  installs make it likely.

### Known limitations found during the corpus-v2 draw (recorded, not fixed — harness frozen)

- **draw-v2 import-order bug**: `scripts/draw_corpus.py draw-v2` imports
  `app.batch.command_rules` before `check_v2_registration` puts `backend/` on `sys.path`, so a
  plain run crashes with `ModuleNotFoundError: 'app'` before anything is screened. The sealed
  code was run unchanged with `PYTHONPATH=backend`; the registration check still ran before
  screening. No code changed.
- **R5 (placeholder) misses placeholders without an underscore**, e.g. `--dataset DATASET`
  (draw #54, IST-DASLab/M-FAC, now in corpus-v2). Such a command counts as a run command under
  the sealed rules; if it fails for that reason it will be a COMMAND_NOT_A_RUN-type outcome
  reported as-is, not re-classified after seeing results.

## corpus-v2 — drawn (2026-09-29)

75 draws screened under the sealed pre-registration (seed 20260928); 20 eligible; corpus_hash
`7df090bea7013974f9f10fb8959ab0162734b51c83a80f744f9c310ce694fbdc`. Outputs: `backend/app/batch/corpus_v2/{corpus.yaml,corpus_hash.txt,screening_log.jsonl}`.

## Pilot run (harness-v1.2, 3/20) — STOPPED (2026-09-29)

> Role, decided 2026-09-29: this is a **pilot**, not the baseline. It discovered a sandbox
> incompatibility (executable-stack refusal for torch's shared objects) and an upload cap.
> Entries 1–3 stay frozen (#2 UPLOAD_TOO_LARGE, #3 MISATTRIBUTED). The full evaluation is the
> corpus-v2.1 ablation (CONTROL: repair off; TREATMENT: repair on) on one newly sealed harness tag.
> Summary: `reports/corpus-v2/summary.md`.

Stopped under the freeze rule (a failure attributed to the repository that is not the
repository's fault). Entries run: #1 nadiinchi/power_laws_deep_ensembles BLOCKED DEP_MISSING
($0.0568); #2 DeformableFriends/NeuralTracking UPLOAD_TOO_LARGE (185,856,000 B > cap; excluded,
$0.0012); #3 autumn9999/vmtl BLOCKED RUNTIME_ERROR_OTHER ($0.3193). Entry #4 was started and
killed by the operator before completing; it has no record and is not counted. Total $0.3773.

**Misattribution (#3):** after `torch` was installed, importing it failed with
`libtorch_cpu.so: cannot enable executable stack as shared object requires: Invalid argument`.
The Nebius sandbox refuses executable-stack shared objects, so the stock PyTorch wheel cannot
load there whatever the repo does. The repair loop then tried `apt install execstack`
(`Unable to locate package`), and the run ended BLOCKED/RUNTIME_ERROR_OTHER, charged to the
repository. That verdict is not valid evidence about the repo. Not fixed (harness frozen); any
torch-dependent repo in corpus-v2 is at risk of the same misattribution. Also note the
classifier labelled the first error SYS_LIB_MISSING, then the failed repair changed the final
code. Entries #4-#20 were not run.

## Sandbox limits (Phase 1; source: Nebius Sandboxes team email, 2026-09-29)

Nebius states two limits for Token Factory Sandboxes: **128 MB per uploaded file** and **12 GB of
filesystem changes per single operation**. The email gives no unit. Code: `backend/app/services/sandbox_limits.py`.

- **Upload limit enforced: 120 MiB = 125,829,120 B, measured (boundary probe, 2026-09-30, `runs/upload_probe/boundary_*.json`).**
  One incompressible file per size, uploaded with the SDK's `apply_files`: **128,000,000 B (128 MB decimal) accepted; 133,169,152 B
  (127 MiB) accepted; 134,217,728 B (128 MiB) rejected; 135,266,304 B (129 MiB) rejected** (rejection = `OSError 28 ENOSPC` during the
  upload operation). So Nebius's "128 MB" is 128 MiB as an exclusive bound; the exact byte between 127 and 128 MiB was not probed.
  120 MiB is 5.5 % below the largest accepted size (the ~5 % margin rule gives 126,510,694 B), so the constant is unchanged from
  harness-v1.3; the sealed docstring was updated and the harness re-sealed as `harness-v1.3.1`. (`125,009,920`, harness-v1.2's cap, was
  never a Nebius number: the top step of RERUN's own probe ladder.) The archive size is measured exactly, so the margin covers only the
  server's accounting.
- **Over the limit → in-sandbox download, never a local upload.** Only the manifest and verifier are uploaded;
  the sandbox fetches the pinned commit (harness-v1.3.2: `git clone --filter=blob:none` + `git checkout`, tarball only as a
  fallback: see "Attempt 1" below; v1.3 used the tarball alone) and checks every
  file against the same git-blob manifest as the upload route (`RERUN_UPLOAD_VERIFIED`, else exit 97 →
  INVALID_HARNESS). Only GitHub repos at a full 40-hex SHA qualify; otherwise `UPLOAD_TOO_LARGE`. Dry-run on real
  Linux (WSL): `octocat/Hello-World@7fd1a60` verified; a tampered manifest failed with exit 97.
- **Setup is split into separate operations:** (a) system packages, (b) torch, (c) everything else, in that order.
  A `pip install` naming torch and other packages is split; commands with shell operators are never split.
- **12 GB per operation:** the SDK exposes no layer size, so each op is checked against an **ESTIMATE** (installed-size
  constants in `sandbox_limits.py`, deliberately high; planning ceiling = 80 % of 12 GB read as decimal) before it runs,
  and an actual quota failure is classified afterwards (`SANDBOX_QUOTA`, Phase 2). The estimates are not measurements.
- Effect on results: entries over 120 MiB are now run instead of ending `UPLOAD_TOO_LARGE`. The pilot's entry 2
  (185,856,000 B) is such a case and stays recorded as-is in the frozen pilot.

## Failure classes SANDBOX_QUOTA / SANDBOX_INCOMPAT, the error chain, and attribution (Phase 2)

**Why.** The pilot (entry 3) showed the sandbox refusing torch's shared objects while the harness charged the
failure to the repository. A platform limit or refusal is not evidence about a paper's code, so it must never
produce BLOCKED.

- `SANDBOX_QUOTA` — a Nebius limit: upload rejected/too large, filesystem delta exceeded, disk full (`ENOSPC`,
  `EDQUOT`, HTTP 413). `SANDBOX_INCOMPAT` — the platform refuses to load a valid artifact: executable-stack refusal
  (`cannot enable executable stack as shared object requires`), seccomp/syscall denial (`Bad system call`). Both are
  checked **before** every other rule (an exec-stack refusal used to match SYS_LIB_MISSING and start a useless apt
  repair loop). Verdict = **INDETERMINATE**, reason code = the class; the run stops at once (no repair attempts);
  both are excluded from every rate like RERUN's own faults. A repo over the upload limit with no download route now
  ends INDETERMINATE / SANDBOX_QUOTA instead of `UPLOAD_TOO_LARGE`; frozen pilot records keep their old verdict.
- **Error chain.** Every classified failure of a run, in order: `{error, class, attribution, cleared_by}`.
  Attribution ∈ `REPO`, `ENV`, `SANDBOX_QUOTA`, `PLATFORM`:
  - a missing package the repo imports but does not declare → REPO (undeclared dependency);
  - a missing package the repo declares that our runner failed to install → ENV;
  - **exception (deliberate):** `torch`/`torchvision`/`torchaudio` missing → ENV **even when the repo does not declare it** (accepted by the operator 2026-09-30), because the runner provides torch by policy (Phase 3):
    a repo that imports torch is served torch by the runner, so a missing torch is our failure to provide it, never the repo's omission; the
    cost is that a genuinely undeclared torch dependency is not counted against the repo (conservative for the RRR denominator);
  - a Python-version failure (removed stdlib name, e.g. `collections.Iterable`) → REPO only if the repo declares/accepts
    the Python version we ran, else ENV (we chose a version it never claimed);
  - quota → SANDBOX_QUOTA; platform refusal → PLATFORM; runner network policy → ENV;
  - a failure that follows a PLATFORM/SANDBOX_QUOTA link inherits it (it is a consequence, not the repo's fault).
- **`first_repo_error`** = the first chain link attributed REPO, whether or not a later repair cleared it (None if
  there is none). **`last_error`** is kept for debugging. The results table shows `first_repo_error` and the attributions.
  ENV / SANDBOX / PLATFORM failures are reported separately and excluded from the Reproducibility Recovery Rate.
- **Passport bundle v4** hashes the whole verdict record: `taxonomy_code`, `indeterminate_reason`, `error_chain`,
  `first_repo_error`, `last_error` (on top of v3's fields). Older certificates keep verifying.
- Regression on the pilot: entry 1's chain is `tabulate` missing (REPO — the repo declares no dependency), `Iterable`
  import error (ENV — we chose py3.11, the repo claims no version), `torch` missing (ENV). So its `first_repo_error` is
  the `tabulate` error, not the `Iterable` one; entry 3's exec-stack refusal is PLATFORM and its `first_repo_error` is none.
- Limits of the rebuild: frozen pilot records carry no chain, so the summary rebuilds it from the `[classifier]` log
  lines (re-reading the evidence with today's sandbox rules); `cleared_by` there is the classifier-line ordinal, not the
  attempt number. Records from harness-v1.3 on store the chain natively.

## Runner environment policy: torch and Python version (Phase 3)

**torch (decision ladder, each step verified with `import torch` in a real Nebius sandbox; records in `runs/torch_check/`,
produced by `scripts/torch_sandbox_check.py`).** Sandbox: Debian `glibc 2.41-12+deb13u2`, kernel `7.0.6`, x86_64
(the `python:3.x-slim` images are Debian 13).

| Step | Spec / image | Result |
|---|---|---|
| (a) newest CPU wheel | `torch` → 2.14.0+cpu, py3.11 | **loads** |
| (a) old pin | `torch==1.12.1` → 1.12.1+cpu, py3.10 | **refused**: `libtorch_cpu.so: cannot enable executable stack as shared object requires: Invalid argument` (the pilot's entry-3 error, reproduced) |
| (b) patchelf | same pin: `patchelf --clear-execstack` on the RWE library, then import | **loads** (1 library: `torch/lib/libtorch_cpu.so`) |
| runner's own ops | pin 1.12.1 and unpinned, exactly the commands `runner_env` emits | both load; the fix clears 1 library for the old pin and none for 2.14.0 |

So the brief's premise ("recent builds ship without the exec-stack flag") holds for the newest wheel and fails for old pins,
which is what repos pin. Step (c) (Nebius email) was **not** needed. Policy (`backend/app/services/runner_env.py`):
torch/torchvision/torchaudio are installed by the **runner**, for repos that pin or import them, as their own sandbox
operation from the CPU wheels (`--index-url https://download.pytorch.org/whl/cpu`, PyPI as an extra index — the CPU index alone
cannot supply an old pin's dependencies, found live), pinned as the repo pins them (`+cuXXX` dropped); a second operation
clears the exec-stack flag on any torch library that has it and verifies the import. CUDA only if the repo pins a CUDA build
**and** the sandbox exposes a GPU; it does not, so never. A refusal that survives the fix is `SANDBOX_INCOMPAT` (INDETERMINATE).
Limitation: a pin whose local suffix is not on the CPU index (rare) still fails, and is classified, not hidden.

*Not done, and why.* **Pre-warmed snapshot:** the SDK supports it (`image.tag_as`), but a snapshot would cover only unpinned
torch on one Python minor (saves ≈ $0.17 and ≈ 16 s per torch repo) and adds mutable external state to a sealed harness; and
pre-installing numpy/scipy/tabulate, as the brief suggested, would **hide undeclared-dependency defects** that the attribution
rules count as REPO (pilot entry 1 failed on undeclared `tabulate`). Only torch is provided. Spend on the ladder: $0.69 (script
records + two runs whose records were overwritten after an index fix), outside any batch.

**Python version policy** (`python_policy.py`): default CPython **3.10**, unless the repo declares a version (`.python-version`,
`pyproject.toml`, `setup.py`/`setup.cfg`, `environment.yml`, `Pipfile`, README) — first available minor that satisfies the declaration,
order 3.10, 3.9, 3.8, 3.11, 3.7, 3.12, 3.13, 3.6 (so "3.7 or later" resolves to 3.10, not 3.7). The reason is logged (`[python] ...`)
and kept in the plan notes. This removes failures of the `collections.Iterable` class caused by *our* choice of 3.11 and makes the
remaining ones attributable to the repo (REPO iff the repo claims the version we ran). `NEBIUS_SANDBOX_IMAGE` now only supplies the
image for repos that declare nothing; the batch driver's preflight refuses any value other than `python:3.10-slim` (an untracked
`.env` saying 3.11 would otherwise silently change every such entry). Tests: 6 fixture repos plus precedence and fallback cases.

## corpus-v2.1 ablation: pre-registration (written 2026-09-29, before any harness-v1.3 batch)

**Question.** Of the repositories that fail as published because of the repository, what fraction does the agent (repair loop +
Tavily + tamper gate) get to run, with everything else held fixed?

**Design.** One sealed harness tag (`harness-v1.3`), the same 20 entries, the same corpus hash `7df090be…`, two arms:
CONTROL = `repair_enabled=false` (no time machine, no repair loop, no Tavily: the repository as-is inside the fixed runner);
TREATMENT = full RERUN (time machine, repair loop, Tavily, tamper gate). The runner-level fixes (sandbox limits, torch,
Python 3.10 policy, error chain) are identical in both arms, so they cannot inflate the difference. The pilot
(`harness-v1.2`, 3/20) is not a baseline and is not used in any number here.
CONTROL runs first (cheap: no repair calls); TREATMENT second.

**Pre-declared analysis** (`scripts/compare_batches.py`, sealed with the harness): each entry lands in exactly one of
CONTROL_PASS, REPO_RECOVERED, REPO_STILL_FAILING, UNSTABLE_AS_IS, ENV_ONLY, SANDBOX_SIDE, NOT_MEASURED (definitions in the script's
docstring). **Reproducibility Recovery Rate = REPO_RECOVERED / (REPO_RECOVERED + REPO_STILL_FAILING + UNSTABLE_AS_IS)**, the
denominator printed beside it, with a 95 % Wilson interval. ENV and SANDBOX/PLATFORM rows are reported separately and never enter the
rate; runner-fix and repo-fix numbers are never merged. n is at most 20, so the interval will be wide, and that is the honest size of
the claim. Researcher-hours saved stays an ESTIMATE (REPO_RECOVERED × 3 h).

**Stop conditions** (halt and report, do not continue): (1) torch still refuses after the exec-stack fix; (2) TREATMENT turns any
CONTROL pass into a non-pass (a REGRESSION row); (3) a Tavily-derived fix touches a tamper-gate-protected file; (4) total sandbox
spend over the operator's cap. `SANDBOX_INCOMPAT` and `SANDBOX_QUOTA` are *predicted* failure classes (Phases 1–2), not stops.
*Settled 2026-09-30:* the operator's total spend cap is **$25 across both arms** (`--total-cap-usd 25`; the 3×-pilot figure of $1.13 was
below one arm's expected cost). Per-entry ceiling stays $2. Cumulative spend is logged per entry and reported by the watcher.
*Gate before TREATMENT:* if CONTROL has fewer than 8 entries with a REPO-attributed non-PASS, TREATMENT is not run (the RRR denominator
would be too small); the corpus draw is extended instead (same rules, new seed, documented).


## Attempt 1: two runner defects found by the attribution audit (harness-v1.3.1 → harness-v1.3.2)

CONTROL was launched on `harness-v1.3.1` on 2026-09-30 (10:34Z) and **stopped by the operator's stop rule after 4 of 20 entries**
($0.47). The 4 records are kept, unchanged and unused in any number, in `runs/corpus_v2_batch/attempt1_harness-v1.3.1_aborted_4of20/`.
Reading them entry by entry (the attribution audit) found two defects in which RERUN's own machinery was charged to the paper's
repository or void, plus one runner gap and one driver crash:

| # | Entry | What the record said | Root cause (one line) | Fix in v1.3.2 | Live verification |
|---|---|---|---|---|---|
| 3 | vmtl | BLOCKED, `DATA_MISSING`, attribution **REPO**: `patchelf: getting info about '--clear-execstack'` | `pip install patchelf` on `python:3.6-slim` resolves 0.17.2, which has no `--clear-execstack` (added in 0.18); the classifier read the error text and charged the runner's own failed step to the repo | attribution keys on the **phase** first: any failure inside a runner-setup op is ENV/PLATFORM, never REPO; patchelf comes from a runner-owned prefix (`/opt/rerun_tools`, `patchelf==0.19.1.0`) and the flag is verified from `--help` before use, else SANDBOX_INCOMPAT (exit 98) | `torch_py36/38/310_*`, `phase_runner_setup_failure_py310`, `patchelf_flag_absent_incompat_py310` |
| 2 | NeuralTracking | INVALID_HARNESS, exit 97 on the in-sandbox download route (374 files) | the run's own stderr says `mode 664 != 0644` for **every** file and the content check runs first, so contents matched: GitHub tarballs (and any umask 002 extraction) give 0664 for git's 100644, and `verify.py` compared the full mode although git tracks only the executable bit. Fixing that exposed a second bug, found live: the sandbox cwd is `/`, and `shutil.move` of the repo's `media/` nested it into the existing `/media` (3 files "missing"); it is now a merging `cp -a` | verify compares the exec bit only; the route is `git clone --filter=blob:none --no-checkout` + `git checkout --detach <sha>`, then `HEAD == sha`, an empty `git status --porcelain`, `git submodule update --init` if `.gitmodules` exists, then the manifest check as well; the tarball (same manifest check) is the fallback only where git cannot be installed (`python:3.6-slim`'s Debian bullseye apt repos are archived: 404) | `download_git_entry2_py310`, `download_tarball_fallback_py36` |
| 4 | img-comp-reference | BLOCKED, `No module named 'torchvision'`, ENV | the repo imported torchvision; the runner planned `("torch",)` for an import-only repo | torch, torchvision and torchaudio are installed **as one matched set** when any of them is imported or declared (pins kept); if the whole set cannot be resolved, only the members the repo uses | `torch_py310_imports_torchvision` |
| - | driver | crash on entry 2 (`UnicodeEncodeError`, U+FFFD echoed from a child to a cp1252 stdout) | Windows Python uses cp1252 for a redirected stdout | driver sets `PYTHONUTF8=1`, reconfigures its own streams to UTF-8 `errors="replace"`, passes the env to children, and its tee cannot raise on encoding | `tests/test_driver_v13.py` (child printing U+FFFD) |

**Common root cause: sandbox-touching code was verified only in the WSL dry run**, which has a different Debian, a different umask, a real
`git`, and a `/` that is not a container root. The fix is the pattern, not the two symptoms: see the seal rule below.

**The phase.** Every step of a sandbox run is tagged `runner_setup` (RERUN's own ops: the torch install and the exec-stack fix),
`repo_install` (the repo's install commands) or `repo_run`; every error-chain link carries its `phase`. **Invariant (tested): a failure
raised while a runner-setup op is executing is attributed ENV, PLATFORM or SANDBOX_QUOTA, never REPO, whatever the error text says.** The run
ends `INDETERMINATE` with reason `RUNNER_SETUP_FAILED` (an our-fault code, excluded from the RRR; `compare_batches` files it under ENV_ONLY).
Regression test on the real entry-3 record of attempt 1: `test_attempt1_entry3_regression_is_env_and_indeterminate`.

**Pre-seal spend:** $1.97 recorded sandbox spend for the probes, the live matrix and the final verification runs (ceiling $4).

## Seal rule (harness-v1.3.2)

*No seal without one real Nebius execution per new sandbox-touching code path. A WSL dry run is a smoke test, not verification.*
Enforced, not promised: `seal_verification.json` (written by `scripts/write_seal_verification.py`, sealed with the harness) lists each
sandbox-touching path, the **git blob of every code file it verified**, and the live run ids with their records
(`runs/sandbox_verification/final/`). The batch driver's preflight refuses to start if the file is missing, if an entry is not marked
live, if a run id is not the `run_id` of a passing listed record, if a code file's blob at HEAD differs from the verified one (the code
changed after its verification), or if any of `sandbox.py`, `sandbox_limits.py`, `runner_env.py` is not covered. Paths verified for
v1.3.2: download route (git), download route (tarball fallback), the archive upload with the exec-bit check, runner torch + patchelf on
Python 3.6/3.8/3.10 with old pins, the matched torch family, the phase tag on a failing runner op, and the flag-absent SANDBOX_INCOMPAT branch.

## CONTROL result, attribution audit, and TREATMENT pre-registration (written 2026-09-30, after CONTROL, before any TREATMENT run)

**CONTROL (harness-v1.3.2, repair off), 20/20 records, $4.07:** 1 RUNS_CLEAN (entry 18), 16 BLOCKED with a REPO link in the error chain,
2 INDETERMINATE `RUNNER_SETUP_FAILED` (entries 5 and 9: the runner's torch install could not resolve the repo's historical pins; ENV, excluded),
1 INFRA_ERROR (entry 7: Nebius `ContreeTransportError`, server disconnected; NOT_MEASURED). 0 INVALID_HARNESS. No driver error.

**Read-only attribution audit** (`reports/corpus-v2.1/audit/audit_attribution.py`; modifies nothing under `runs/` or the sealed tag; output
`audit_attribution.json` sha256 `c8df688411d5d20cccc050dbec6475f5a9b9fc93bbcc08e503bb7085f77de0d4`). For every non-PASS record it searches the repository at the pinned commit for the failing module in
requirements*.txt (any directory), setup.py/cfg, pyproject, environment/conda files, Pipfile, Dockerfile*, scripts, and pip/conda install lines
in README/docs, with import->distribution aliases (sklearn -> scikit-learn, ...); README *prose* mentions are recorded separately and do not count as a
declaration. Independent check (plain `git ls-tree`, no audit code) on 6 of the repos: **none has any dependency manifest at all**, only a README
(the harness saw no dependency file for any of the 16 audited entries).
- Labels: REPO_UNDECLARED 12, PLATFORM_REQUIRED 3 (entries 2, 4, 14: Docker / `--cuda` / CUDA), ENV_ROT 3 (5, 9, 17), INFRA 1 (7), PASS 1 (18).
- **DECLARED_NOT_PARSED: none** (no harness gap of that kind).
- **Gate (>= 8 REPO-attributed non-PASS): (a) under the pre-registered rule = 16; (b) under the audit (REPO_UNDECLARED only) = 12** (11 if entry 19 is
  excluded: `operators._ext` is the repo's OWN compiled module and its README documents a build step, so it is a candidate *planning* gap, reported to the operator,
  not a dependency). Both clear 8; TREATMENT is not blocked by the gate.
- Judgment calls, disclosed: entry 17 (`zero_gradients` removed from newer torch; the repo pins no torch, the runner installs the newest) is labelled ENV_ROT by
  a rule, but the registered attribution is REPO (undeclared pin); entry 6 (README states chainer 4.0.0/5.2.0) and 12 (README: TensorFlow 1.1.0) are
  undeclared in any manifest but versioned in prose.

**INFRA_ERROR retry policy (pre-registered).** Only a verdict of `INFRA_ERROR` (an external service failed, not a measurement) is ever retried; no other
verdict is retried, ever (no retry-until-pass). After an arm's run completes, each INFRA_ERROR entry is re-run **once**, on the same sealed tag, arm and
per-entry cap, in corpus order. The first record is kept in `<arm>/infra_retries/NN_name.attempt1.json` (outside the `NN_*.json` glob the analysis reads) and the
retry's record replaces it as the entry's record. A second INFRA_ERROR stays NOT_MEASURED. The retry is applied to each arm independently; a pair is excluded
from every rate only if either arm is still NOT_MEASURED after its retry. Retry spend counts against the $25 cap. Registered after CONTROL's one INFRA_ERROR (entry 7)
was observed, but before any TREATMENT result exists; the policy does not depend on TREATMENT, so it cannot favour it.

**Fix-difficulty strata (pre-registered, frozen).** Each entry is assigned a stratum by `reports/corpus-v2.1/audit/assign_strata.py` from CONTROL and the audit only,
so the assignment is blind to TREATMENT (`reports/corpus-v2.1/strata.json`, sha256 `ade8083fcda9bda5f71d8e55f0994076a99b267749a16ec619bc12ac9a385333`). D1 name-only (a missing PyPI package, no version stated anywhere): 8 entries;
D2 version/API drift or a torch-coupled binary package (ENV_ROT, a README-stated version, torch-sparse): 6; D3 platform (GPU/Docker; expected not fixable): 3;
D4 build step / the repo's own module: 1; not stratified (PASS, INFRA): 2. **Reporting of TREATMENT:** (1) the primary Reproducibility Recovery Rate is exactly the
pre-registered one (`compare_batches.py`, denominator printed, Wilson 95 %); (2) a **per-stratum table** (n, recovered, Wilson interval), never pooled across strata without the
per-stratum rows beside it; (3) a sensitivity RRR whose denominator is the audit's REPO_UNDECLARED entries only, labelled as such. n <= 20, so every interval is wide
and that is the honest size of the claim. Recoveries in D1 are the expected easy wins and are not to be described as evidence for the hard strata.

### Amendment (2026-09-30, after the registered INFRA retry, before any TREATMENT run)

The retry of CONTROL entry 7 (`albertometelli/pfqi`) ran under the policy above: attempt 1 (INFRA_ERROR, $0.003) is kept in `control/infra_retries/`; the retry
ended `BLOCKED`, `DEP_MISSING: numpy`, REPO, phase `repo_run` ($0.006). The audit and the strata were re-run on the final CONTROL set; **only entry 7's row changed**
(INFRA/"-" -> REPO_UNDECLARED/D1). Final CONTROL: 1 RUNS_CLEAN, 17 BLOCKED, 2 INDETERMINATE `RUNNER_SETUP_FAILED`; total spend $4.08 with the attempt-1 record.
**Final gate: (a) pre-registered rule = 17; (b) audit = 13 (12 excluding entry 19's own module).** Strata counts: D1 9, D2 6, D3 3, D4 1, unstratified 1 (PASS).
The frozen hashes are superseded: `strata.json` sha256 `78edd77de94683e3758d13f47db85cc90590665fe0fef131aadafcc42a1197d7`, `audit_attribution.json` sha256 `4c8e3066eb90045f09361a1e90d5cdabba8c78ad246e4a6a9b3e437453590466`. The earlier hash `ade8083f...` was computed while entry 7 was INFRA_ERROR.


## harness-v1.3.3 — EXPLORATORY; v1.3.2 is the pre-registered result (written 2026-09-30, after the v1.3.2 results, before any v1.3.3 run)

**What stands.** The pre-registered corpus-v2.1 ablation ran on the sealed `harness-v1.3.2` (commit `77b3cfe`): CONTROL 20/20, TREATMENT 20/20, recorded spend
$21.76. Its result is **Reproducibility Recovery Rate 0/16 (Wilson 95 % 0 %–19 %)**, reported in `reports/corpus-v2.1/RESULTS.md` (commit `8d47dfc`) with every
number pointing at a record. That result, the records under `runs/corpus_v2_batch/harness-v1.3.2/` and every pre-registered rule above are **not changed by anything
below**. It is a measurement of a defective repair loop (16 source patches proposed, 0 applied, Tavily queried 46 times and cited 0 times, 3 terminal errors taken
from noise), not a finding about the papers or their authors.

**What v1.3.3 is.** A fix of the defects listed in `reports/corpus-v2.1/candidate_v1.3.3_defects.md`, mapped one by one in
`reports/corpus-v2.1/v1.3.3/DEFECT_FIX_MAP.md` (what is fixed, what is only partly fixed and how that was measured, what is left open: D-13, the repo's own build
step in D-6, and the existence of apt package names in D-12). The fixes were designed **after seeing the corpus-v2 results**. From here on corpus-v2 is a
**disclosed development set**: nothing measured on it with v1.3.3 is confirmatory, every v1.3.3 number is labelled exploratory, and it is always shown beside the
v1.3.2 number, never instead of it. A confirmatory claim needs a corpus drawn after the fixes; none is drawn.

**Parameters introduced (sealed in code, not `.env`).** Sandbox cost rate for killed operations $0.0085/s (the maximum over 168 real operations in this repository's
records: median 0.0026, p95 0.0040, max 0.00845); per-operation funding cap for repair operations (revised below: $2.00, the whole entry cap; the as-published baseline keeps the 600 s wall clock); an operation killed at its
limit ends INDETERMINATE `COST_CAP` (NOT_MEASURED); minimum fundable operation 30 s; smoke limit 60 s for repair re-executions; era cutoff relaxation 365 days
per package. The $0.0085 rate is an observed bound, not a guarantee; a killed step's spend is recorded as an estimate and flagged as such.

**What a v1.3.3 `RUNS_AFTER_REPAIR` means.** Repair re-executions run under a smoke limit: the documented command is run unchanged for up to 60 s; a pass is "finished with
exit 0" or "still running at 60 s, with output and no traceback, then stopped". It is recorded per attempt (`execution`). It is **not** "completed" and **not** "reproduced the
paper", and the as-published baseline run is unchanged (not smoke), so a v1.3.3 recovery and a CONTROL pass are not the same kind of success and are never summed.

**Correction to this file.** The CONTROL section above says the harness saw no dependency file for any of the 16 audited entries. The records show dependency files for
entries 5 (Pipfile, requirements.txt), 9 (requirements.txt) and 17 (setup.py); 17 of 20 entries have none (`RESULTS.md` §3). The text above is left as written.

**Plan, stated before any v1.3.3 spend (operator decision 2026-09-30).** (1) Seal v1.3.3 after a live verification of every sandbox-touching path (the seal rule).
(2) A paid **smoke gate**, TREATMENT only, cap $6, on 4 entries (the selection below is superseded by the amendment that follows: entries 11, 10, 3, 8). Pass only if ALL hold: at least 2 of 4 reach RUNS_CLEAN or RUNS_AFTER_REPAIR; at least 1 source patch applied via `git apply`;
at least 1 repair carries a real Tavily citation stored in the record; no entry over $2 and the cost guard fired on nothing or fired correctly. If it fails: stop, report root
causes, no further spend without a new decision. (3) Only if it passes: a full exploratory TREATMENT run on all 20 (cap $25; CONTROL v1.3.2 stays the baseline unless a fix
changes CONTROL behaviour, which the fix map lists, with a separate estimate for a CONTROL re-run), then the Phase B analysis again, beside v1.3.2, HARNESS_INDUCED rows kept.
(4) Only then the product surface. The new ledger starts at $0; the v1.3.2 spend ($21.76 recorded, possibly more: D-8) is not part of it.

### Amendment (2026-09-30, operator review, before any v1.3.3 run; supersedes the smoke-set selection and the cost parameters in the section above)

**1. Smoke set: entries 11, 10, 3, 8 (TREATMENT only).** The plan's rule ("the D1 entries with the shortest CONTROL error chains") is degenerate: all nine D1
CONTROL chains have exactly one link. The tie is broken outcome-blind by the smallest dependency batch found by the static scan
(`reports/corpus-v2.1/v1.3.3/dep_scan_d1.json`): entry 11 (4 packages), 10 (5), 3 (6); the next would be entries 7 and 15 (8 each). What they exercise:
11 the NumPy cap (D-16: its v1.3.2 TREATMENT ended INDETERMINATE RUNNER_SETUP_FAILED on NumPy 2 beside an old torch), 3 the README-declared Python 3.6 (D-11: v1.3.2
ran it on the era's 3.10). Entry 10's v1.3.2 terminal error was GPU_REQUIRED (`Torch not compiled with CUDA enabled`), so it may end BLOCKED however well the loop works;
it stays because the rule is outcome-blind, and the gate is judged on all four. **Entry 8 replaces entry 1** (operator decision): entry 1's terminal v1.3.2 failure is
`No module named 'curves'`, a module the repository does not contain and no repair can supply, so it cannot satisfy criterion (a); entry 8 exercises the era-lock fix (its
v1.3.2 era lock died on `torch`, which had no release before the era) and the patch pipeline (its v1.3.2 attempt 3 was a header-only diff). The selection and its reasons are
recorded here before any run.

**2. Gate criteria, unchanged.** (a) at least 2 of the 4 reach RUNS_CLEAN or RUNS_AFTER_REPAIR; (b) at least 1 source patch applied via `git apply`; (c) at least 1
repair with a real Tavily citation stored in the record; (d) no entry over $2 and the cost guard fired on nothing or fired correctly. Cap $6, operator approval before launch.
**Criterion (b) rule:** if no entry of the set ever proposed a source patch (every repair was environment-only), (b) is N/A for Step 2, and it becomes mandatory for the
reporting of Step 3: the Step 3 report must state the number of source patches proposed and applied, and a Step 3 with zero patches proposed is reported as "the patch
pipeline was not exercised", never as a pass.

**3. Cost rule, revised before any run.** Entry 18's CONTROL operation took 57 s (TREATMENT 75 s), cost $0.163, far inside the ~176 s the first design allowed, but the
check found that 3 of the 20 v1.3.2 CONTROL operations (entries 3, 14, 5) took 195-494 s of wall time at a normal cost of $0.17-$0.29 (entry 3: 494 s in CONTROL, 84 s in
TREATMENT), i.e. slow installs or transient slowness that cost little. A 176 s limit would have turned them into false `COST_CAP`s, and could do the same to the only passing
entry. Therefore: **the as-published baseline run keeps the pre-registered 600 s wall clock and is never shortened by the budget rule** (so CONTROL is unchanged by this
rule); its spend is recorded and counts against the entry cap, and an entry whose baseline used the cap ends `COST_CAP` before any repair (observed baseline cost: at most
$0.35 in 40 operations). **Repair operations** (time machine, build-isolation step, every repair) are funded with everything the entry has left (per-operation cap = the $2.00
entry cap), at the worst observed rate of $0.0085/s, killed at that limit, and the killed step's spend is recorded as a flagged estimate. Consequence, stated plainly: the
per-entry cap is hard for repair operations and is NOT hard for the baseline run, whose worst case at the maximum observed rate is $5.10 (never observed for a baseline); and a
repair operation that legitimately needs more than its funding (e.g. the 221-316 s installs of v1.3.2 entry 16) ends `COST_CAP`, which is counted and reported, not hidden.

**4. Fixtures and licences.** Only permissively licensed repositories (MIT/BSD/Apache) have their original files committed (`backend/tests/fixtures/v133/NOTICE.md`; only
IST-DASLab/M-FAC, MIT). For the other six repositories of the stored patches (four without a licence, one with a non-commercial no-copy notice, one whose LICENSE has no grant text) the
originals are fetched from GitHub at the pinned commit and checked against the recorded git blob (`scripts/fetch_patch_fixtures.py`, `patches/SOURCES.json`); those tests are
marked `requires_network` and skipped offline.

**5. Known limitations of harness-v1.3.3 (recorded, not fixed).**
- **D-13, runner-setup failures never reach the time machine.** A `RUNNER_SETUP_FAILED` (the runner's own torch install could not resolve the repository's pinned versions for the
  image's Python) ends the entry before the era interpreter is considered. Affects **entries 5 and 9** (INDETERMINATE in both arms of v1.3.2); whether an older interpreter would install
  their pins is untested. They stay outside every rate.
- **D-6, the repository's own build step is not planned or run.** A module the repository builds itself (a native extension with a documented build command) is no longer mistaken for a
  PyPI package, but nothing builds it. Affects **entry 19** (`operators._ext`); it stays a REPO failure in the denominator.
- Also open: apt package names that do not exist on the image (D-12, second half) are not validated before a sandbox run (seen in entries 8 and 12 of v1.3.2).

**Live findings at the seal verification (2026-09-30).** The first live run of the kill path showed that a step stopped by the sandbox comes back as a normal result with
`state.timed_out`, not as an exception (D-17 in `reports/corpus-v2.1/v1.3.3/DEFECT_FIX_MAP.md`); the harness now reads the flag and records the killed step's measured cost.
It also means the v1.3.3 "estimate" for a killed step applies only when the client's wait expires before the server answers. Seal verification attempt 1 was stopped on its first
failure, as instructed; its 10 passing records were made against a `sandbox.py` that this fix changes, so the seal rule requires them to be repeated.

**Seal verification, repeat (2026-09-30).** After the D-17 fix all 17 planned live runs passed on the new `sandbox.py`, plus one extra kill run: the same call was stopped by the client's
wait in one run (`client_wait_timeout`, 27.9 s, `OperationTimedOutError`) and returned by the server with `state.timed_out` in another (`server_result_timed_out`, 28.0 s, exit code -1,
measured cost $0.00006), so both branches of the stop handling were seen live; the race between them is real and is the subject of the drafted sponsor issue
(`reports/corpus-v2.1/sponsor-issues/nebius-sandbox-state-timed_out.md`, not filed). Spend: attempt 1 $1.236 + repeat $1.260 = $2.496 on the new ledger.

### Amendment (2026-09-30, operator review, after the seal and before any smoke-gate run)

**1. Smoke set: entry 10 replaced by entry 7 (final set 11, 7, 3, 8).** Entry 10's v1.3.2 terminal error was GPU_REQUIRED (`Torch not compiled with CUDA enabled`), a platform requirement
the sandbox cannot provide, so it could not satisfy criterion (a) however well the loop works. The replacement follows the same outcome-blind rule as before: the D1 entry with the next-smallest
dependency batch (`reports/corpus-v2.1/v1.3.3/dep_scan_d1.json`: 11 -> 4, 10 -> 5, 3 -> 6, then 7 -> 8 and 15 -> 8 tied, 8 -> 11 already chosen) whose known chain does not end in a platform
requirement. Entries 7 and 15 both qualify (7: v1.3.2 terminal a package build failure at install, `Encountered error while generating package metadata`; 15: `dataclasses==0.8` not installable, then a
wall-clock overrun); the tie goes to the lower entry number, **entry 7**. Entry 7's build failure (system libraries for a native package) may still be hard; it is not a platform requirement in the sense above, and it
is chosen by the rule, not by expected success. Gate criteria unchanged: (a) at least 2 of 4 reach RUNS_CLEAN / RUNS_AFTER_REPAIR, (b) at least 1 source patch applied via `git apply` (N/A if none was ever
proposed, then mandatory for the full run's reporting), (c) at least 1 repair with a real Tavily citation in a record, (d) no entry over $2. The launcher is `reports/corpus-v2.1/v1.3.3/smoke_gate/run_smoke_gate.py`.

**2. A sealed tag is never moved again.** Any change after a tag has been pushed is a new version (a new tag), never a re-pointed one. Disclosure: `harness-v1.3.3` was moved exactly once, about a minute after its first
push and before anything had fetched or used it, to include a one-line fix to a structure test that still named the v1.3.2 tag (tests are outside the batch preflight's data allowlist, so the fix could not follow the tag);
the tag now points at `8af1717` and will not move again.

### harness-v1.3.4 (2026-09-30, after the v1.3.3 smoke gate did not pass; operator decision: Option 1)

The v1.3.3 smoke gate (`reports/corpus-v2.1/v1.3.3/smoke_gate/SMOKE_GATE_REPORT.md`) did not pass: (a) 1 of 4 recovered (entry 11, by the time machine alone), (b) passed
(2 source patches applied, entry 3), (c) 0 Tavily citations in 7 searches, (d) passed; spend $2.930. Its five root causes (D-18 to D-22) are fixed in **harness-v1.3.4** to the
operator's specification, tests first (`reports/corpus-v2.1/v1.3.3/DEFECT_FIX_MAP.md`, section harness-v1.3.4), then a live seal verification of every sandbox-touching path plus
the download-route overlay case on entry 8's own repository. Rules unchanged: v1.3.2 is the pre-registered result; everything on v1.3.3/v1.3.4 is exploratory on a disclosed
development set; a sealed tag is never moved (v1.3.4 is a new tag); the gate is re-run on the same four entries (11, 7, 3, 8) with criteria (a)-(d) unchanged, seal repeat cap
$2.00, re-gate cap $3.50, stop on first failure. If it fails again on (a) or (c), no further Nebius spend without a decision, and the full defect history becomes the write-up.

What a v1.3.4 record adds: `consulted` (every reference offered, numbered as in the prompt) beside `tavily_sources` (the cited ones, each with `cited_via`); `reason_no_citation`;
`silent_exit`; and, for a run voided by INVALID_HARNESS, the attempt that was being executed. A `content_match` citation is RERUN's deterministic finding that the applied
change's text appears in that reference; it is labelled as such and is never reported as the model's own citation.

**Seal verification of harness-v1.3.4 (2026-09-30).** 20 live runs, all passed, on the v1.3.4 `sandbox.py` / `smoke_exec.py` / `runner_env.py` blobs: the 17 v1.3.3 paths repeated,
the download-route overlay case on entry 8's own repository (the file the v1.3.3 gate lost; `OVERLAY_OK`), and the kill path through both stop paths. Measured spend $1.312;
cumulative on the new ledger $6.738. `seal_verification.json` written from these records; the tag is new (`harness-v1.3.3` is untouched).


### harness-v1.4.0-rc (2026-10-01; offline, unsealed, no Nebius call) and the pre-registration of gate v1.4.0

**Why.** The Step 0 budget note (`docs/design/v1.4.0-budget.md`, generated from the records) shows that harness-v1.3.4 rebuilt the environment
from the base image in every sandbox operation: 18 torch install steps started in the two gates, and two of the four v1.3.4 losses (entries 8 and
11) ended COST_CAP in or after a repeated install. D-23 is reclassified from design limit to defect (owner, 2026-10-01). The owner's directive maps
one mechanism to each gate entry: #11 the CPU shim + checkpoint persistence; #08 checkpoint persistence + an entry cap that is never inherited
from a starved gate remainder; #07 D-24 (already in); #03 the D-25 exit-site hook; then parallel candidates (3 per failure, 3 rounds) as the
general mechanism. Every change is listed in `reports/corpus-v2.1/v1.4.0/STEP1_REPORT.md` with the test that pins it.

**What changes in a run (TREATMENT; CONTROL and the as-published baseline execution are unchanged).** Sandbox operations keep their images
(the committed tree, then one image per setup step) and later operations reopen the deepest kept image whose setup steps are a prefix of what
they need, running only the rest (`sandbox.Checkpoint`). Kept images always hold the committed tree; every gate-approved change travels in a
small overlay archive put on top (or right after the tree when a setup step reads a patched file), on both upload routes, which replaces the
D-20 download-route overlay in the live flow. The repairer is asked for up to three candidates per failure; each passes the env gate, the
tamper gate and py_compile, then runs in its own branch of the environment image (at the same time when what is left funds every branch
for the smoke run plus a start-up margin, otherwise one after another); the candidates that changed the exit outcome
go to the adjudicator (Ultra), whose choice is applied to the checkout and whose image becomes the environment image. With one candidate per
round the harness-v1.3.x flow is unchanged. Deterministic steps come before any model call: D-24, the CPU shim on GPU_REQUIRED, the exit-site
hook on a non-zero exit with no error text; each is recorded as attempt 0 / origin time_machine with `time_machine_action`.

**What a v1.4.0 record adds.** `operations`: one entry per sandbox operation with `sandbox_seconds` (sum of the API's per-step elapsed times,
MEASURED), `install_seconds` (each setup step's command, phase, seconds, exit code, cost, and whether it is the torch install), `branch_from_image`,
`result_image`, `image_kept` / `kept_images`, `env_image_id`, `torch_installed`, `torch_in_start_image`, `torch_env_key`, cost (measured, and the
estimated part of a killed step), and outcome. Candidate attempts carry `candidate`, `branch`, `adjudication` and `chosen`.

**Gate v1.4.0, pre-registered here before any v1.4.0 run.** Same four entries (11, 7, 3, 8), TREATMENT only, same criteria (a)-(d) as the
v1.3.4 gate, plus (e): (a) at least 2 of 4 end RUNS_CLEAN or RUNS_AFTER_REPAIR; (b) at least 1 source patch applied (an attempt with a non-empty
diff that reached a re-execution); (c) at least 1 repair attempt with a stored Tavily citation; (d) no entry over $2.00 and the cost guard correct
where it fired; (e) torch installed at most once per environment image, from the records' `operations` (no install on top of an image that already
held torch; no rebuild of an environment an earlier operation of the entry had built; the planner-image baseline's install is counted separately and
is outside (e); a record without `operations` fails (e)). Runner: `reports/corpus-v2.1/v1.4.0/gate/run_gate_v140.py` (no default caps; the gate cap
must be at least 4 x the fixed entry cap; an entry is never started with less than the entry cap). Seal first, at most three live runs
(`reports/corpus-v2.1/v1.4.0/seal/run_seal_v140.py`). Caps: the owner's figures, written in chat before anything runs (proposed shape: seal at most
$1.50, gate at most $5.00 with $1.25 per entry). If the gate fails, the Phase D assets stay as they are and v1.4.0 is documented as "attempted, did
not pass" beside the earlier gates.

### Seal of harness-v1.4.0: option B, and the seal -> gate rule (owner decision in chat, 2026-10-01, before any live call)

Caps (owner): seal $1.50, gate $5.00, entry $1.25 (gate = 4 x entry); ledger after this step at most $16.64 (lower bound, D-27).
The seal rule (`check_seal_verification`) is unchanged in form: every sandbox-touching file must be covered by live verifications made
against its current blob. What changes is the set of paths re-verified for v1.4.0 (option B): only the paths the four gate entries
(corpus-v2 #3, #7, #8, #11) exercise, plus the new v1.4.0 paths.
- Re-verified (`scripts/run_seal_verification_v140.py`): the download route by git on entry 8's own repository; the archive upload route;
  runner torch on python 3.6 (1.10.2 pin, entry 3), the matched family on 3.10 (entries 8 and 11 baselines), 1.8.1 with the NumPy cap on 3.9
  (entry 11); the runner-setup phase tag; the kill at the operation limit through both stop paths; the smoke launcher on 3.10 and 3.6.
- New (`reports/corpus-v2.1/v1.4.0/seal/run_seal_v140.py`): run 1 (ready image with kept layers, one branch run = the measured branch-run
  cost, the runner hooks on a kept image with a live exit-site check, a kept image reopened after a wait) and run 2 (entry 7's recorded
  environment as a checkpoint, then reopen + apply + execute). Run 3 only as a repeat of an ambiguous run.
- NOT re-verified for v1.4.0, because no gate entry uses them: the download route's tarball fallback, torch pins on python 3.8 and the 3.10
  1.12.1 pin, the patchelf-flag-absent case, and the D-20 download-route overlay (legacy, out of the live flow). A later batch that needs one
  of them must verify it first.
- `seal_verification.json` is written by `scripts/write_seal_verification_v140.py` from those records; the tag `harness-v1.4.0` is set only if
  every check passes; otherwise `harness-v1.4.0-rc` stays and nothing is gated.

Kept-image billing. The SDK reports a cost per run only, and Nebius documents only runs and image imports as billable (Contree MCP
cheatsheet: list_images, set_tag, upload, download and the other image operations "Free"; `run` and `import_image` "VM"); no document found
states a storage price or an image retention period. The seal therefore records: the cost of reopening a kept image after a wait (run 1 D)
next to the same operation run immediately (run 1 B), and every kept image id with its time, so a storage charge, if the account's billing
page ever shows one, can be matched. Each gate record lists its kept images (`operations[].kept_images`); the gate report gives their count
per entry so the ledger can bound a storage charge (D-27 style annotation).

Seal -> gate (owner's rule): after seal run 1 the measured branch-run cost and the kept-image evidence are reported with record ids. The gate
starts automatically only if ALL hold: every seal check passed; measured branch-run cost <= $0.15; kept images not billed while kept (on
the evidence above) or billed at <= $0.05 per image per entry; seal spend <= $1.50. Otherwise stop and report. Gate: entries 3, 7, 8, 11 in
that order, criteria (a)-(e) as pre-registered above, hard stop at $5.00, each entry reported as it lands; an honest verdict either way.

**Gate v1.4.0 result (2026-10-01): NOT PASSED, attempted.** (a) 0 of 4 (#3, #7 BLOCKED; #8, #11 INDETERMINATE COST_CAP); (b) pass, 6 patches
applied in branches; (c) pass, 3 attempts with a stored Tavily citation (#8), the first in any RERUN gate; (d) pass; (e) pass on all four.
Gate spend $3.1943 (incl. $0.1868 ESTIMATED) + upload smoke $0.0049; ledger $14.6495 [$13.6787 MEASURED + $0.9708 ESTIMATED], lower bound
(D-27). Report with findings: `reports/corpus-v2.1/v1.4.0/gate/GATE_REPORT_v1.4.0.md`. v1.4.0 is documented beside v1.3.3 and v1.3.4 as
"attempted, did not pass"; the Phase D assets stay as they are.


### harness-v1.4.1-rc (2026-10-01; offline, unsealed, no Nebius call in Step 1) and the pre-registration of gate v1.4.1

**Tag note (D-36).** The ledger is the sandbox API's reported operation cost, not account billing: the owner read the account balance at 19:37 local on
2026-10-01, $49.61 of $50.00, about $0.39 charged, against a ledger of $14.6495 (a factor of about 37). Until D-36 is resolved the tag MEASURED
reads **API-REPORTED** (the Phase D assets are relabelled: passports, REPLAY, dashboard, README, Devpost answers; earlier sections of this file and
the earlier reports keep the old word and are read the same way), ESTIMATED and DERIVED are unchanged, and each gate gets one **BILLED** line from the
owner's balance readings (v1.4.0 gate: at most $0.39 cumulative, an account-level reading, not per gate; the gate runner's result file carries the
v1.4.1 line as null until the owner reports it). Kept images: where a report says "unbilled on available evidence" it now reads "no charge observed
on the account balance". Investigation: `docs/design/D-36.md` (open).

**Why.** Reading the harness-v1.4.0 gate records (annotated in `reports/corpus-v2.1/v1.4.0/gate/GATE_REPORT_v1.4.0.md`): #11 and #8 ended by the guard's
funding rule (a fixed $0.0085 per wall second), #7 by the adjudicator's invalid JSON with a first-candidate fallback and by D-24 seeing only the adopted
failure, #3 by an exit the hook did not see. Six deterministic fixes, each registered fixed-unvalidated in `candidate_v1.3.3_defects.md` with its test
(D-30 to D-35); `harness-v1.4.0` (`15d3cdf`) stays byte-identical.

**What changes in a run (TREATMENT; CONTROL and the as-published baseline execution are unchanged).**
1. D-30: an operation is funded at the rolling rate this entry's completed operations cost per wall second (sum of cost over sum of wall time) x 1.5,
   floor $0.0030, ceiling $0.0085; no completed operation yet: the ceiling. `operations[].funding` records `rate_used`, the measured rate and the source operations.
2. D-31: a budget-limited stop never ends the entry while what is left funds one operation (the smoke run + 20 s) AND an environment image holding a setup
   command is kept: the next operation resumes from that image (at most two resumes per operation); otherwise INDETERMINATE COST_CAP, with the reason.
3. D-32: the candidate adjudicator re-asks once on an invalid reply (both replies recorded); its fallback takes the first passing run, else the furthest recorded stage.
4. D-33: D-24, the CPU shim, the exit-site hook and the exit wrapper observe every candidate's failure and fire in that candidate's branch
   (`time_machine_action` with `on_candidate`).
5. D-34: an apt package added at repair time is an additive layer on the kept environment image, never a rebuild from the tree image.
6. D-35: when the exit hook was installed and printed nothing, the entry script runs through the exit wrapper; if that prints nothing too, the record says "exit outside Python".

**What a v1.4.1 record adds** (only when set; v1.4.0 records are unchanged): `operations[].funding`, `resumed_after_operation`, `apt_layers`, `exit_wrapper`;
`adjudication.replies`, `reasked`, `fallback_basis`; `time_machine_action.on_candidate`, `apt_layer`, `then`, and the wrapper's `applied`, `reason`, `result`.

**Gate v1.4.1, pre-registered here before any v1.4.1 run.** Same four entries (3, 7, 8, 11), in that order, TREATMENT only, same criteria (a)-(e) as the
v1.4.0 gate, verbatim: (a) at least 2 of 4 end RUNS_CLEAN or RUNS_AFTER_REPAIR; (b) at least 1 source patch applied; (c) at least 1 repair attempt with
a stored Tavily citation; (d) no entry over $2.00 and the cost guard correct where it fired; (e) torch installed at most once per environment image
(planner-image baseline outside (e); a record without `operations` fails (e)). Runner: `reports/corpus-v2.1/v1.4.1/gate/run_gate_v141.py`, which LOADS
the v1.4.0 runner's criteria instead of copying them (`test_v141_gate_runner.py`). Caps (owner, chat, 2026-10-01): fixed entry cap $1.50, gate cap $6.00
(= 4 x the entry cap; an entry whose full cap no longer fits in what is left is not started), seal at most $1.00, ledger ceiling $25.00 API-reported
(ledger $14.6495 before Step 2, a lower bound, D-27; worst case seal + gate $7.00 gives $21.6495). The cost guard stays on: the caps are the
discipline, not the constraint. Hard stop at the gate cap; each entry is reported as it lands; the verdict is honest either way. If the gate fails,
v1.4.1 is documented beside v1.4.0 as "attempted, did not pass" and Phase D proceeds with all four versions.

**Seal of harness-v1.4.1: option B over CHANGED files only (owner).** Among the sandbox-touching files only `runner_hooks.py` changed (the exit
wrapper); `sandbox.py`, `sandbox_limits.py`, `runner_env.py` and `smoke_exec.py` are byte-identical to harness-v1.4.0 (D-34 was implemented in the
orchestrator for that reason). `scripts/write_seal_verification_v141.py` therefore carries over the 11 v1.4.0 entries whose code files are all unchanged
(it checks each blob against the v1.4.0 record and stops if one changed), replaces the one entry that lists `runner_hooks.py`
(`runner_hooks_on_a_kept_image`) and adds the v1.4.1 paths. Live checks, `reports/corpus-v2.1/v1.4.1/seal/run_seal_v141.py` (records in
`runs/sandbox_verification/v1.4.1-seal/`): run 1 A ready image, B one branch run (the measured branch-run cost), C hooks on A's image, W0 a bare
`raise SystemExit(1)` with the hook alone (nothing on stderr), W1 the same through the wrapper (the raise site), W2 the wrapper on python:3.6-slim; run 2 the
additive apt layer on a kept image (only the layer runs, gcc is there); run 3 an operation stopped at its limit keeps the layer before the stopped step and a
new operation reopens it (D-31 on the real service). ESTIMATED cost $0.3637, from the v1.4.0 seal and gate records (A $0.0120, B $0.00054618, C $0.0012
API-reported; the apt step of #8 operation 11 $0.0775 API-reported; the killed step of K1 at the observed $0.0103 per billed second, D-36), cap $1.00; an
operation starts only while three times its estimate is left under the cap. Not repeated for v1.4.1 because no file they cover changed: everything else
in the v1.4.0 seal.

**Seal -> gate (owner's rule, automatic).** The gate starts only if ALL hold: every seal check passed; the measured branch-run cost (op B) is at most $0.15
API-reported; the seal spend is at most $1.00. Otherwise stop and report. Tag `harness-v1.4.1` only on a passed seal (the seal commit carries
`seal_verification.json`); until then `harness-v1.4.1-rc` stays and nothing is gated.


**Seal of harness-v1.4.1: complete, all checks passed (2026-10-01, live).** Ten operations, all `ok`: run 1 (A ready image, B one branch run at $0.00062790 API-reported,
C the hooks on a kept image, W0 the bare `raise SystemExit(1)` with the hook alone: stderr empty, W1 the same through the exit wrapper: the raise site, W2 the wrapper on
python:3.6-slim), run 2 (the additive apt layer on a kept image: only the layer ran, gcc present), run 3 (an operation stopped at its limit kept its first layer and a new operation reopened it by
id). Seal spend $0.3263 = $0.1254 API-reported + $0.2009 ESTIMATED (the stopped step of K1), cap $1.00; ledger $14.9758 [$13.8041 API-reported + $1.1717 ESTIMATED], a lower bound
(D-27). The seal -> gate rule holds (every check passed, branch run at most $0.15, seal at most $1.00): the gate starts automatically. `seal_verification.json` (16 paths: 11 carried
over from v1.4.0, 5 for v1.4.1) written by `scripts/write_seal_verification_v141.py`; tag `harness-v1.4.1` on the seal commit. Report: `reports/corpus-v2.1/v1.4.1/seal/SEAL_STATUS.md`.

**Gate v1.4.1 result (2026-10-01): NOT PASSED, attempted.** (a) 0 of 4 (#3, #7, #8, #11 all BLOCKED); (b) pass, 8 patches applied of 26 proposed (all on #8); (c) pass, 6 attempts with a stored Tavily
citation; (d) pass, no entry over $2.00 (largest $1.1140 of the $1.50 cap), no operation stopped; (e) pass on all four. No entry ended COST_CAP (v1.4.0: two). The exit wrapper reported "exit outside Python"
on #3 and #11 (on #11 the cause is a kill by signal, exit 137). Gate spend $3.5247 API-reported (incl. $0.3625 model share, price table), $0.0077588 of smoke tests and a link probe; the first pre-batch upload
smoke test failed on a slow line (0.16 MB/s) and the gate refused to start, then passed on the second attempt. Ledger $18.5083 [$17.3366 API-reported + $1.1717 ESTIMATED], lower bound (D-27), under the $25.00
ceiling. BILLED: the owner reads the balance after the gate. Report with findings and new defects D-37 to D-39: `reports/corpus-v2.1/v1.4.1/gate/GATE_REPORT_v1.4.1.md`. v1.4.1 is documented beside v1.4.0 as
"attempted, did not pass"; Phase D then proceeds with all four versions (separate directive: the REPLAY, dashboard and submission figures change with it).


### harness-v1.4.2-rc (2026-10-01; offline, unsealed, no Nebius call in Step 1) and the pre-registration of gate v1.4.2 (the final gate)

**Why.** The harness-v1.4.1 gate (annotated in `GATE_REPORT_v1.4.1.md`, findings D-37 to D-39): the adjudicator adopted nothing unless the run passed (#7, three rounds), a kill by signal read as a silent exit (#11, exit 137), the CPU shim did not
cover `.cuda()` (#8), and #3's silent exit stayed unexplained. v1.4.2 fixes those four, from the owner's directive; `harness-v1.4.1` (`5ba14a2`) stays untouched. Owner decisions in the same message: the killed-step ESTIMATE is the API's median per
billed second x 1.5 = $0.0152/s from now on, tagged ESTIMATED with its rate and source recorded on the cost event; past estimates are not recomputed and are annotated "computed at $0.0085/s, not an upper bound (D-27)"; BILLED for the
v1.4.1 gate is the owner's reading ($49.61 -> $49.57; at most $0.43 cumulative; $0.04 between the readings against $3.8588 recorded).

**What changes in a run (TREATMENT; the as-published baseline is unchanged).**
1. D-37: a "none" from the adjudicator becomes the candidate that strictly advanced furthest past the failure being repaired (coarse stage key; `adopted_reason` "partial progress"); the next round starts from its kept image. A run that passed is never adopted this way (the adjudicator's veto of a pass stands); a candidate whose run the sandbox killed is adopted over a "none" (`adopted_reason` "resource kill") so the entry ends INDETERMINATE, never BLOCKED.
2. D-39: the CPU shim also covers `.cuda()` on Tensor and Module, `.to("cuda*")`, `torch.device("cuda*")`; each path that acted is recorded (`paths_fired`).
3. D-38 / D-40: exit 137 / -9 is RESOURCE_LIMIT; the entry ends INDETERMINATE with the limit quoted (read from the sandbox by one evidence run, else the documented limits), never BLOCKED, and no model attempt is spent; the sandbox's
   documented limits (none for memory and CPU) are stored on every operation; a larger instance is not documented and is not used.
4. #3's "exit outside Python": one more wrapper run with the evidence; a kill evidenced is RESOURCE_LIMIT, otherwise INDETERMINATE EXIT_OUTSIDE_PYTHON with that reason; no model attempt.

**Gate v1.4.2, pre-registered here before any v1.4.2 run.** Same four entries (3, 7, 8, 11) in that order, TREATMENT only, criteria (a)-(e) unchanged from the v1.4.0 gate (the runner `reports/corpus-v2.1/v1.4.2/gate/run_gate_v142.py` loads them;
an INDETERMINATE ending, by resource or by an unexplained exit, is not a pass under (a)). Caps (owner): fixed entry cap $1.50, gate cap $6.00 (= 4 x entry), seal at most $1.00, ledger ceiling $25.00 API-reported. The ceiling binds:
ledger $18.5083 + gate cap $6.00 leaves $0.4917 for the seal, so the seal cap is **$0.49** (the owner's $1.00 is looser than the ceiling arithmetic; worst case 18.5083 + 0.49 + 6.00 = $24.9983). Hard stop at the gate cap; each entry reported as it
lands. After the gate, whatever the verdict, all live work stops (owner); v1.4.2 is documented beside v1.4.1 and the Phase D update follows (v1.4.0, v1.4.1, v1.4.2 into passports, REPLAY, dashboard and the submission texts, the headline
becoming the count over all gate entry-runs).

**Seal of harness-v1.4.2: option B over CHANGED files only.** Among the sandbox-touching files only `runner_hooks.py` changed again (the shim, the evidence command): the 13 entries of the v1.4.1 seal whose code files are unchanged are carried over
by `scripts/write_seal_verification_v142.py` (it stops if a blob changed); the three entries that list `runner_hooks.py` are re-verified and one is new. Live checks (`reports/corpus-v2.1/v1.4.2/seal/run_seal_v142.py`, records in
`runs/sandbox_verification/v1.4.2-seal/`): run 1 A, B (the branch-run cost for the rule), C, W0, W1, W2 as in v1.4.1; run 2 E0 a calm run with the evidence block, E1a a process that SIGKILLs itself (exit 137, `Killed`, kill evidenced, classified
RESOURCE_LIMIT by the harness's own classifier), E1b informational: memory allocated in 64 MiB chunks until killed or 48 GiB, bounded by a 25 s clock, the first look at what the sandbox holds. ESTIMATED cost $0.2821 (A-W2 from the v1.4.1 seal
records, E1b the clock bound at $0.0103 per billed second), cap $0.49, an operation starts only while 1.5 x its estimate is left. The shim's new paths are checked against REAL torch offline (a torch install in the sandbox would cost more than the
rest of the seal). **Seal -> gate (owner's rule, unchanged, automatic):** every seal check passed, branch-run cost at most $0.15 API-reported, seal spend within its cap; otherwise stop and report. Tag `harness-v1.4.2` only on a passed seal.

**Seal of harness-v1.4.2: result (2026-10-01).** Passed, 9 of 9 live operations ok, **$0.045032 API-reported** (cap $0.49; no operation stopped, no estimate); the branch-run cost (B) $0.000576; `seal_verification.json` 17 paths (13 carried over, 4 verified), tag `harness-v1.4.2`. Every seal record carries the blobs of `sandbox.py` and `runner_hooks.py` at the time it was written and the writer refused a mismatch. What the live checks added: the first look at the sandbox's own limits (one probe, python:3.10-slim): MemTotal 4,034,744 kB (3.85 GiB), 4 CPUs, no swap, no readable cgroup memory file; a process that allocated 64 MiB at a time was killed at 3776 MiB with exit 137, `Killed` and a kernel `Out of memory: Killed process` line, so memory exhaustion produces the exit status entry 11 showed; whether #11's own kill was memory is for the gate's evidence run to read. Report: `reports/corpus-v2.1/v1.4.2/seal/SEAL_STATUS.md`. Ledger $18.5533 (lower bound, D-27).

**Gate v1.4.2: result (2026-10-01/02).** NOT PASSED (attempted, did not pass): (a) **1 of 4** (#7 RUNS_AFTER_REPAIR under the 60 s smoke criterion; #3 INDETERMINATE EXIT_OUTSIDE_PYTHON, #8 INDETERMINATE COST_CAP, #11 INDETERMINATE RESOURCE_LIMIT), (b) pass (1 applied of 4),
(c) **fail (0 stored citations)**, (d) pass (largest entry $1.3058), (e) pass on all four; no operation was stopped, no estimate. Gate $3.9350 API-reported (model $0.1280 DERIVED), smoke $0.0051; ledger $22.4935 (lower bound, D-27), room under the $25.00 ceiling $2.5065. BILLED: the owner's balance reading, not yet received.
Findings: D-37 observed live on #7 round 2; D-38/D-40: #11's kill is an out-of-memory kill of a 3.85 GiB sandbox VM, evidenced from inside it; D-39 not exercised; **D-41 (new, open): the sandbox SDK truncates each stream at 65,535 bytes and the harness never looks, which probably made #3's
"silent exit" a cut-off error message in every version (strong indication in the records, not proven)**. Report: `reports/corpus-v2.1/v1.4.2/gate/GATE_REPORT_v1.4.2.md`. After the gate all live work stopped (owner); Phase D follows.


### The D-41 probe and harness-v1.4.3-rc (2026-10-02; offline, unsealed; the probe is the only Nebius call before the seal) and the pre-registration of gate v1.4.3 (the final gate)

**Owner's answers to the v1.4.2 report (chat, 2026-10-02).** v1.4.2 is accepted. The headline is confirmed with this exact wording: "2 of 20 gate entry-runs reached a RUNS_* verdict and no gate passed; one is a measurement artefact (v1.3.3 #11, smoke limit), the other a 60 s smoke-criterion pass after
model-proposed environment changes were adopted (v1.4.2 #7)." The old rule "never imply recovered" is replaced by: **state the verdict class and the criterion it met, never a rate, never the word recovered without the criterion beside it.** The spend ceiling is raised to **$32.00** API-reported.
D-23/D-24 fixed-and-gated and EXIT_OUTSIDE_PYTHON as not measured are accepted. If D-41 is confirmed, every EXIT_OUTSIDE_PYTHON and silent-exit record across all versions gets the annotation "stderr truncated at 65,535 bytes, D-41" beside its verdict (verdicts unchanged): done in the Phase D update after the gate.
Ratings and the new-versus-existing answer stay the owner's. The balance reading for the v1.4.2 gate is the owner's to send.

**The probe (run first, cap $0.05).** One live operation reran the recorded failing operation of `harness-v1.4.2/gate/03_autumn9999__vmtl` (operation 5) on its kept image with the stream sent to a file inside the run. **D-41 is confirmed**: the real stderr is 400,939 bytes, the SDK returned the first 65,535, the raw API result's
stderr `truncated` flag was true, and the cut-off tail holds `AssertionError: Torch not compiled with CUDA enabled` at `.cuda()` (#3's "silent exit" in every version was this error; the CPU shim never ran on #3 because the harness never saw it). Record `d41-probe/probe_03_vmtl_op5@51727e649a26a37f0646ec1e0107bf1708cd175c086b75a13c09b0f8b48bc7f2`,
cost $0.048615 API-reported (a faithful rerun costs what the recorded operation cost; the "about $0.002" of the v1.4.2 report was an estimate for a smaller read and was wrong). Ledger $22.5421 (lower bound).

**What changes in a run (TREATMENT and baseline; no command that runs in the sandbox changes).**
1. **D-41** (`sandbox.py`): every client that runs a command asks for `default_truncate_output_at = 4 MiB` (an SDK parameter) and every real run is asked for bytes and decoded with replacement (asked for text, the SDK raises inside `.wait()`, losing the step's result and cost, when the cut lands inside a multi-byte character); each step stores the API's `truncated` flag of each stream, the size and sha-256 of what came back, and the API's peak-memory figure as returned (`max_rss`, D-40); a failed command whose stream is still cut and holds no error text ends
   INDETERMINATE `OUTPUT_TRUNCATED` (no hook, wrapper, evidence run or model attempt; not measured in the summaries). The directive's tee-to-a-file re-fetch is NOT implemented (a disposable run leaves no file in a kept image; a tee changes every executed command, the baseline included): see `candidate_v1.3.3_defects.md`, "harness-v1.4.3-rc".
2. **Entry cap $1.75** (was $1.50): #8 ended COST_CAP in v1.4.2 with $0.20 missing.
3. **#11 out of memory (3.85 GiB):** the SDK (0.3.6) has no memory or instance parameter on a run or on the spawn request (pinned by a test), so no retry-on-a-larger-instance rule exists; #11 stays INDETERMINATE RESOURCE_LIMIT with the kernel line quoted.
4. **Sustained-run line (D-42), non-gating:** after the four entries every RUNS_* entry whose smoke run was alive at its limit is re-executed once from its final image for 600 s or to completion, funded from what the gate cap has left (a 600 s run is about $6.2: the line is funding-limited and says so), the outcome stored beside the record.

**Gate v1.4.3, pre-registered here before any v1.4.3 run.** Same four entries (3, 7, 8, 11) in that order, TREATMENT only, criteria (a)-(e) unchanged from the v1.4.0 gate (`reports/corpus-v2.1/v1.4.3/gate/run_gate_v143.py` loads them down the chain; an INDETERMINATE ending, including OUTPUT_TRUNCATED, is not a pass under (a); the sustained-run line is not a criterion).
Caps (owner): fixed entry cap **$1.75**, gate cap **$7.00** (= 4 x entry, the sustained runs included), seal cap **$1.50**, ledger ceiling **$32.00** API-reported: $22.5421 + $1.50 + $7.00 = $31.0421, $0.9579 below the ceiling. Each entry is reported as it lands; hard stop at the gate cap.
After the gate, whatever the verdict: all live work stops for good (owner); the Phase D update for v1.4.3 (passports, REPLAY, dashboard, texts, register D-1..D-42, headline recomputed by the rule above) follows, then the D6 red team with one more attack: find any claim that still rests on a truncated stream.

**Seal of harness-v1.4.3: option B over changed files.** `sandbox.py` changed and every entry of the v1.4.2 seal lists it, so none is carried over: all 17 entries are re-verified by re-running their live checks unchanged against the new blob, plus two new entries (the output limit and the flag; `run_on_image`). Stages (`reports/corpus-v2.1/v1.4.3/seal/run_seal_v143.py`,
records in `runs/sandbox_verification/v1.4.3-seal/`): new S1-S4 (200,000 bytes whole; 5 MiB cut at exactly 4 MiB with the flag set and the last line not returned; S2b a cut inside a multi-byte character returns without an exception; `run_on_image` on a kept image; the same stopped at 3 s), then the v1.4.1 checks (kill at the operation limit with the layer kept, resume, the additive apt layer), the v1.4.2 checks (hooks, wrapper, evidence after a calm run and a self-SIGKILL;
the informational allocation probe is not repeated), the v1.4.0 checks (checkpoint layers, a branch run, a kept image reopened after a wait, entry 7's environment as a checkpoint) and the 14 verifier-script checks (download route, archive upload, three torch installs, the runner-setup tag, the kill through both stop paths, the smoke launcher on 3.10 and 3.6). ESTIMATED $1.4765
(the earlier records' own API-reported costs; the stopped step of K1 at $0.0152/s for a 25 s operation limit: a pessimistic figure, the API reports a stopped sleep at about $0.0001 when it returns the result), cap $1.50, an operation starts only while its earlier cost is left. The driver refuses to start unless HEAD's harness paths are byte-identical to the tag `harness-v1.4.3-rc` and clean, records the blobs of the five sandbox-touching files in `SEAL_RUN.json`, and `scripts/write_seal_verification_v143.py` refuses a stale blob.
**Seal -> gate (owner's rule, unchanged, automatic):** every seal check passed, branch-run cost at most $0.15 API-reported, seal spend within its cap; otherwise stop and report. Tag `harness-v1.4.3` only on a passed seal.

**Seal of harness-v1.4.3: result (2026-10-02).** Passed: five stages, every check ok, `seal_verification.json` 19 paths (17 re-verified, 2 new), 34 live run ids; **$1.4307 recorded = $1.1262 API-reported + $0.3045 ESTIMATED** (K1, a step stopped by the client wait, $0.0118 API-reported completed steps plus the stopped step at $0.0152/s), cap $1.50; branch-run cost $0.000529 and $0.000551 (limit $0.15): seal to gate rule satisfied. Live: the API honours a 4 MiB `truncate_output_at` and cuts exactly there with the flag set; 200,075 bytes of stderr come back whole; a cut inside a multi-byte character returns without an exception (replacement character); `run_on_image` reopens a kept image by id. Report: `reports/corpus-v2.1/v1.4.3/seal/SEAL_STATUS.md`. Ledger $23.9728 (lower bound), ceiling $32.00, worst case with the gate cap $30.9728. Tag `harness-v1.4.3`.

**Gate v1.4.3: result (2026-10-02).** NOT PASSED (attempted, did not pass): (a) **0 of 4** (#3 BLOCKED DATA_MISSING, #7 and #8 BLOCKED RUNTIME_ERROR_OTHER, #11 INDETERMINATE RESOURCE_LIMIT), (b) pass (15 applied of 17), (c) pass (7 attempts with a stored citation), (d) pass (largest entry $1.1742), (e) pass; no entry ended RUNS_*, so the sustained-run line (D-42) made no live run. Gate $3.69455 (sandbox $3.4451 API-reported + model $0.2495 DERIVED), no estimate; ledger $29.1704 (lower bound), room under the $32.00 ceiling $2.8296. The gate process was killed twice by its environment (attempt 1 with the session that started it, inside #3; attempt 2b, a console control event, inside #8); #3 and #7 are records of attempt 2b, #8 and #11 of attempt 2c, resumed with `--resume` under the same tag and entry cap, gate cap $6.25 for that invocation so that the ledger stays under the ceiling (`reports/corpus-v2.1/v1.4.3/gate/INTERRUPTED_ATTEMPT.md`; D-43). Live: **D-41 fixed** (#3's 399,981-byte stderr came back whole, its CUDA error was seen and the CPU shim fired; no stream of any record was cut), D-39's `.cuda()` path fired live, D-24 and D-32 again, `max_rss` stored (#11: 3,898,376 as returned, against the kernel's anon-rss 3,897,356 kB). Report: `reports/corpus-v2.1/v1.4.3/gate/GATE_REPORT_v1.4.3.md`. After the gate all live work stopped for good (owner); the Phase D update for v1.4.3 and the D6 red team follow. BILLED: the owner's balance readings (v1.4.2 and v1.4.3 gates), not yet received.

## harness-v1.5 dev/test protocol — PRE-REGISTRATION (written 2026-10-02, before any live call of the v1.5 program)

**Status.** Exploratory development under a DEV/TEST split. The pre-registered result of the ablation stays harness-v1.3.2's. This amendment is committed and pushed before any Nebius call of the v1.5 program, and it changes no gate criterion, no verdict and no record: every record of every earlier version stands as written. Nothing here is a claim; the claims come after the TEST phase, from the TEST records.

**Goal (owner's directive, 2026-10-02).** Raise the recovery rate on repositories the harness has not been tuned on. **Primary metric, TEST only:** the number of TEST entries whose verdict is `RUNS_CLEAN` or `RUNS_AFTER_REPAIR` **and** whose D-42 sustained check confirms it (definition under "Confirmed", below). **Target: at least 3 of the 8 TEST entries.** Reference (owner's figure): harness-v1.3.2 reached 1 of 20 per arm. The count is reported whatever it is, with the criterion beside it. The standing reporting rule is unchanged: state the verdict class and the criterion it met, never the word "recovered" without the criterion, and no rate from n = 8.

### A. The split

Rule, fixed before it was run (one run, no alternative tried): sort the 16 corpus-v2 entry ids that are not gate entries {3, 7, 8, 11} ascending by the SHA-256 hex digest of the id in decimal ASCII without padding (`sha256(b"5")`); positions 0, 2, 4, ... (counting from 0) are DEV, positions 1, 3, 5, ... are TEST. Code: `reports/corpus-v2.1/v1.5/devtest/split.py`; the test `test_devtest.py` recomputes it independently and checks that the two lists below are exactly its output.

```
GATE_ENTRIES: [3, 7, 8, 11]
DEV_ENTRIES: [4, 5, 9, 12, 14, 15, 16, 17]
TEST_ENTRIES: [1, 2, 6, 10, 13, 18, 19, 20]
```

Three scorecards at the end, kept separate: the four gate entries (tuned on for four versions), DEV (tuned on in the v1.5 rounds), TEST (not touched by the v1.5 rounds). The headline follows the standing rule, TEST first.

### F. The TEST firewall

Until the freeze the TEST entries are not opened (corpus entry text and repository, records of any version, passports, REPLAY pages, dashboard rows), not run, and not discussed in any report. The v1.5 failure analysis reads the records of DEV and gate entries only; the entry id of a record is taken from its file name, so a TEST record is refused before it is opened (`devtest/firewall.py`, tested). Round reports contain no TEST entry. The Phase D builders read every record and are not run until after the TEST phase. A fix needs a replay of a recorded failure, and that recording is a DEV or gate record.

**Prior exposure, stated now, tabulated at the freeze.** All 20 entries ran in harness-v1.3.2 (both arms) and the defect register D-1..D-43 was written with sight of all of them. The TEST set is therefore unbiased only with respect to what the v1.5 rounds develop; it is not a set the harness has never met. The per-entry table (which fixed defect was first observed on which TEST entry) is produced from the register at the freeze, after the last DEV round, not before.

### D. DEV rounds

- **D1.** At most 6 rounds. A round is the full DEV batch (8 entries, once each, ascending id, TREATMENT) at the then-current sealed tag. Stop when: the DEV count reaches 5 of 8; or two consecutive rounds add nothing; or a ceiling or the budget guard (B) stops the loop; or the time box ends (freeze by 9 Oct 2026).
- **D2. DEV count.** The number of DEV entries whose verdict is `RUNS_CLEAN` or `RUNS_AFTER_REPAIR` in that round, at smoke level. Each is labelled with its kind from `sustained_run.final_run_of` (`baseline_complete`, `smoke_exited`, `smoke_alive`, `no_smoke_record`), and every round report says how many are `smoke_alive`, i.e. a 60 s smoke pass that nothing has confirmed.
- **D3. No sustained check in DEV rounds.** A sustained run costs about $6.24 (600 s at $0.0104 per sandbox second, the rate in the v1.4.3 records); a round with five of them would cost about $31. DEV is the development signal, not the goal metric: only TEST carries the sustained confirmation.
- **D4. "Adds nothing".** A round adds something if its DEV count is higher than the best earlier round's, or if some entry has a RUNS_* verdict in it that it had in no earlier round. Before round 1 the best earlier count is 0 (no DEV entry ended RUNS_* in either arm of harness-v1.3.2). A round that adds neither is one that "adds nothing".
- **D5. Infra.** An entry that ends INFRA_ERROR with no baseline execution is re-run once (the 2026-09-28 re-queue rule); the first record is kept unmodified under `infra_retries/` with a note beside it. Every other verdict stands, whatever it is.
- **D6. Process.** Every round runs detached (Task Scheduler, `pythonw`, `--log-file`): a paid batch is never a child of a session (D-43). After each round `reports/dev/ROUND_N.md` states: the verdict per entry; the failure-class histogram (DEV rounds so far and the gate entries' historical records); which deterministic rules fired; what the model contributed; the D-41 stream flags; the cost API-reported and the BILLED reading when the owner has given one (AWAITED otherwise).

### G. Fixes between rounds

Allowed: deterministic rules, shims, layering, classification, resource handling, prompts and adjudication logic. Forbidden: special-casing an entry id, a repository name or a URL; reading TEST entries; editing records; changing a gate criterion after seeing results. Each fix: (1) has a test that replays the recorded failure that motivated it (a DEV or gate record); (2) is named in the commit by the failure CLASS it addresses (for example: missing system library, a removed API in a newer package, GPU-only code, a hard-coded absolute path, a missing dataset) with at least one other DEV or historical (DEV or gate) entry that the class also covers, or is labelled **single-case** and reported as such; (3) is reviewed by an independent Agent subagent before the tag, as in v1.4.2; (4) gets its tag `harness-v1.5.N` and a CHANGELOG line naming the failures it targets. If a change touches a sandbox-touching file (the seal rule), the changed files are re-verified live (option B) before the tag, and that spend counts in the DEV total.

### B. Budget (API-reported dollars; the owner's BILLED balance readings are kept beside them and never mixed in)

- **B1. Ceilings (owner).** Entry $1.50; DEV total $40.00 (every DEV dollar: entry records, upload smoke tests, seals); ledger $75.00. The ledger starts at **$29.1704** (lower bound, D-27; `reports/corpus-v2.1/v1.4.3/gate/GATE_REPORT_v1.4.3.md`), so the room under the ceiling is $45.83.
- **B2. Round-1 estimate (ESTIMATED; inputs are API-reported records of DEV and gate entries).** Low $4.68: the eight DEV entries' v1.3.2 TREATMENT costs (seven of them $2.0462 in all; entry 16 ran into the old $2.50 cap and is taken at the new $1.50 cap) times 1.5545, the ratio of the four gate entries' costs in v1.4.3 ($3.69455) to their costs in v1.3.2 ($2.3766). Central **$7.39**: eight times $0.9236, the mean cost of the four v1.4.3 gate entries. High **$12.00**: eight entries at the $1.50 cap. The RESERVE check below uses the central figure and the HARD check the high one.
- **B3.** No sustained check in a DEV round (D3).
- **B4. The ceilings cannot all hold, and the guard that decides.** $29.17 (ledger) + $40.00 (DEV total) = $69.17, which leaves $5.83 under the $75.00 ledger ceiling for the TEST phase: less than one sustained run ($6.24). The TEST phase needs eight entries (central $7.39, at most $12.00) and, for the target of 3 confirmed, up to three sustained runs ($18.72). So a TEST reserve of **$26.11** ($7.39 + 3 × $6.24) is kept. Before every round the runner checks two things (`devtest/budget.py`, tested): HARD (the round's worst case, $12.00, fits under the DEV total and under the ledger ceiling) and RESERVE (ledger + the round's central estimate + the TEST reserve is at most the ledger ceiling). A round that fails either check is not started; the loop then freezes. Under the default figures this allows round 1 and, if round 1 costs about its central figure, round 2; round 3 only if rounds 1 and 2 together cost at most $12.33. The owner can change this only by writing a new ceiling in chat (the runner takes it as `--ledger-ceiling-usd`; $100.00 would fund the DEV total, a full TEST phase and three sustained runs). The guard is a restriction on spending, never a loosening.

### Confirmed (the primary metric's definition)

A TEST entry counts iff its verdict is `RUNS_CLEAN` or `RUNS_AFTER_REPAIR` and one of the following holds, read from the record and its `sustained_<NN>_<name>.json`: (i) the final run is `baseline_complete` or `smoke_exited` (the documented command exited 0 by itself); (ii) the sustained outcome is `completed` (exit 0); (iii) the sustained outcome is `running_at_limit` with `funded_seconds` = 600 and no "funding-limited" in its label (the command ran the full 600 s without failing). Not confirmed, and listed with their outcome: `failed`, `error`, `not_run`, `no_smoke_record`, and a `running_at_limit` that was funding-limited below 600 s. A confirmed run says the documented command ran 600 s or to completion; it does not say the paper's result was reproduced.

### Round 1 (the first live call of the program)

Tag **harness-v1.5.0** is harness-v1.4.3's code unchanged: `backend/app`, `backend/pyproject.toml`, `scripts`, `frontend/src`, `.gitattributes` and `seal_verification.json` are byte-identical to the tag harness-v1.4.3 (`git diff --quiet harness-v1.4.3 harness-v1.5.0 -- <those paths>`). It is cut at the commit that carries this amendment because the batch preflight refuses a run when any file outside its data allowlist changed since the tag, and `README.md`, `docs/`, `phase_d/` and `backend/tests/` changed after harness-v1.4.3 (the Phase D update and D6). No sandbox-touching blob changed, so the v1.4.3 seal verification stays valid and no live seal is run. Round 1 therefore measures the DEV set at unchanged code: the baseline the later rounds are compared with.

### T. Freeze and TEST

At a stop condition: tag `harness-v1.5-final`, seal option B over the files changed since the last seal (cost in the ledger), push, then run the 8 TEST entries once each in ascending id (entry cap $1.50; an infra retry once, annotated; no re-run of any other kind), then the sustained run of every RUNS_* entry whose smoke run was alive, funded as `sustained_run` funds it from what the TEST cap leaves (the TEST cap = the ledger ceiling less the ledger at the freeze; a run the cap cannot fund for 600 s is "funding-limited" and not confirmed). The report states the count against the target with the DEV rounds beside it, and the prior-exposure table. After TEST, whatever the result: all live work stops; the Phase D update (passports, REPLAY, dashboard, texts, register) with three separate scorecards and the headline by the standing rule, TEST first; then READINESS, the anchor, the clean-room test, and the D6 re-check of every new claim.

### Limits, stated before the results

n = 8 on each side and one run per entry: a count of 3 against 0 is a count, not a rate, and a single LLM run is one draw. DEV entries are tuned on and their counts measure development, not generalisation. The TEST set was seen by earlier versions (prior exposure, above). The sandbox is CPU-only (no GPU) with 3.85 GiB of memory, so GPU-bound entries can end BLOCKED or INDETERMINATE whatever the harness does.

### DEV round 1 and harness-v1.5.1 (written 2026-10-03, after round 1, before round 2)

**Round 1** ran at `harness-v1.5.0` (code byte-identical to harness-v1.4.3) on 2026-10-02: the 8 DEV entries once each, 60 minutes, detached under the Task Scheduler. Cost $5.5643 = $5.4316 API-reported + $0.1327 estimated (killed steps), inside the pre-registered range ($4.68 low, $7.39 central, $12.00 high). The upload smoke test cost $0.0053. Verdicts, by the pre-registered DEV count (D2, smoke level): **1 of 8** (DEV #15 RUNS_AFTER_REPAIR, kind `smoke_alive`: a 60 s smoke pass after the repair model removed a `dataclasses` pin; nothing confirms it). #4, #12, #14, #16 BLOCKED RUNTIME_ERROR_OTHER; #5 INDETERMINATE DEP_UNPINNED_CONFLICT and #9 INDETERMINATE DEP_YANKED (both in RERUN's own setup step, no repair attempt); #17 INDETERMINATE COST_CAP at $1.5084. Round 1 adds something over the empty earlier rounds (D4). Report `reports/dev/ROUND_1.md`; records `runs/corpus_v2_batch/harness-v1.5.0/dev/`.

**Ledger.** After round 1: $34.7400 (lower bound, D-27) = base $29.1704 + DEV $5.5696; DEV total $5.5696 of $40.00; the budget guard for another round is OK (RESERVE: ledger + $7.39 + the $26.11 TEST reserve = $68.24 of $75.00). **BILLED:** the owner's balance reading is $48.29 (2026-10-03; screenshot in chat), $1.28 below the $49.57 reading after the v1.4.1 gate, at most $1.71 billed in all if the account started at $50.00; the interval holds the v1.4.2 gate, the v1.4.3 seal and gate and round 1, so round 1 is not separable (`reports/dev/BILLED_READINGS.md`).

**Fixes (tag harness-v1.5.1; rule G).** Three, each with its failure class, recorded DEV failures, covered entries, replay test, negative control and independent review in `reports/dev/FIXES_harness-v1.5.1.md`:
F1, a pinned old torch has no wheel for the interpreter RERUN chose (DEV #9, #17); F2, the code uses an API a newer release removed (DEV #17, #12), a deterministic step before any model call; F3, GPU-only code the CPU shim did not cover (DEV #14, **single-case**). Not fixed, with the reason: #5 (the repository's own torch/torchvision pins cannot coexist), #14's `LU without pivoting` (a CUDA-only operation), #16 (end-of-life Debian mirrors, one entry), #4 (placeholders and missing input files: a legitimate BLOCKED). Of the sandbox-touching files only `runner_hooks.py` changed, so the seal is option B over the four entries that list it (passed 2026-10-03: 8 live checks, $0.019562 API-reported, counted in the DEV total; `reports/corpus-v2.1/v1.5/seal/SEAL_STATUS.md`); the other 15 entries of the v1.4.3 seal are carried over with their records.

**What round 2 measures.** The same 8 DEV entries, once each, at harness-v1.5.1. Nothing about TEST is read or run. Round 2 is a development signal under D1-D6; it is not a result about unseen repositories.

### DEV round 2, BILLED reading, and the budget re-anchoring (written 2026-10-03, after round 2, before round 3)

**Round 2** ran at `harness-v1.5.1` (`reports/dev/ROUND_2.md`): **2 of 8** at smoke level (#15 and #17, both `smoke_alive`), $6.9561 API-reported + estimates; adds something over round 1 (D4). The pre-registered guard then **refused round 3** (RESERVE: $41.7207 + $7.39 + $26.11 = $75.22 against the $75.00 ledger ceiling).

**BILLED, the owner's reading after round 2:** **$47.96** (2026-10-03 19:07 local; screenshot in chat). The previous reading, before round 2, was $48.29: round 2 was billed **$0.33** against $6.9561 API-reported for the same interval (the interval holds round 2 and nothing else that spends). Cumulative: at most **$2.04** billed against an API-reported ledger of $41.7207 (lower bound). `reports/dev/BILLED_READINGS.md` has every reading.

**What the readings establish (DERIVED from the two series, stated here as the owner's reading of them).** The API-reported dollar is the sandbox API's own operation cost; the account is billed a small fraction of it (sandboxes are free in beta, D-36; the model calls, $0.0027-$0.1295 per entry in round 2, are close to what was billed). The two ceilings of B1 ($40.00 DEV, $75.00 ledger) were written in a unit that does not track the money the account loses. They still bound the sandbox API's reported cost, which is the figure every record carries, and they stay in force as such; but a guard that refuses a round "because the TEST phase could not be paid for" is, in money, refusing over about $0.35.

**Owner's decision (chat, 2026-10-03, with the $47.96 reading): the figure the guard rule B4 lets the owner write.**
- **Ledger ceiling: $100.00** (API-reported), the figure B4 names as the one that funds the DEV total, a full TEST phase and three sustained runs. Passed to the runner as `--ledger-ceiling-usd 100.00` (`launch_round.cmd`). DEV total $40.00 and the $1.50 entry cap are unchanged.
- **A BILLED floor, binding on the owner, added beside the API ceilings:** no live work (round, seal, TEST, sustained run) is started when the owner's latest balance reading is **below $20.00**, and a reading is requested after every round, seal, the freeze and the TEST phase. It is a restriction the API ceilings do not express, never a loosening of them; it is checked by the owner from the reading, not by code (the balance is not readable from the API, D-36).
- Nothing else changes: no gate criterion, no verdict, no record, no DEV/TEST split, no firewall rule. Round 3 runs under this amendment at `harness-v1.5.2` (`reports/dev/FIXES_harness-v1.5.2.md`: F2b, F2c; not yet run live).

**What round 3 measures.** The same 8 DEV entries, once each, at harness-v1.5.2. What it can show: whether #12 (the TensorFlow-1 row) moves past its recorded conflict, and whether #15 and #17 keep their RUNS_* verdict (a single LLM run is one draw: a loss there is a draw, not a regression, unless the records show a changed cause). A development signal under D1-D6, not a result about unseen repositories.

## harness-v1.6 — PRE-REGISTRATION (written 2026-10-03, after DEV round 2, before any v1.6 live call)

**Status.** An amendment to the v1.5 dev/test protocol. It changes no verdict, no record, no gate criterion of any earlier version, no DEV/TEST split, no firewall rule and no budget rule. It is committed and pushed before any live call at a v1.6 tag. It is written **after** the v1.5 DEV rounds and with sight of the DEV and gate records (never a TEST record): stated here so that no reader takes it for a blind pre-registration of the ladder below. What it pre-registers is how v1.6's new outputs are defined, counted and reported before they are run.

**Why (what the v1.5 records show; `reports/dev/levels/levels.md`, counted offline from the committed DEV and gate records).** The v1.5 primary metric (a RUNS_* verdict confirmed by a 600 s run) sits at the top of a ladder the harness already climbs but does not report. On the pre-registered run (harness-v1.3.2, the 12 DEV+gate entries) the as-published failure was cleared in 0 of 12 CONTROL records and 7 of 12 TREATMENT records, 6 of the 7 by the deterministic time machine and 1 by a gated model proposal; the environment stopped being the blocker in 3 of 12 (CONTROL) against 8 of 12 (TREATMENT). In DEV round 2 (harness-v1.5.1): first error cleared in 6 of 8 (time machine 5, model 1); environment resolved in 7 of 8; RUNS_* in 2 of 8. What then blocks a run is, in the records' own words: a dataset the repository tells the user to download, a GPU-only operation on a CPU sandbox, an API a newer release removed, an end-of-life apt mirror, a source build that fails, the repository's own pins that cannot coexist. Four of these are recorded as `RUNTIME_ERROR_OTHER`: the harness stops at the right place and does not say why. The product a reviewer or a replication team needs is the ladder and the named blocker: does it run; if not, how far did it get, what stops it, and what would a human have to supply. v1.6 reports that from stored fields and makes the classifier name the blocker. The v1.5 primary metric stays the primary metric.

**L. The outcome ladder** (`result.outcome_levels`, per run record, computed from stored fields; `reports/dev/levels/compute_levels.py` rebuilds it offline from any record of any version, and the two must agree, by test): `first_error_cleared` (`error_chain[0].cleared_by` is set) with `first_error_cleared_by` (the `origin` of that attempt: `time_machine`, a rule name, or `model`); `env_resolved` (the last link of the error chain is not a dependency or system-library class, or the verdict is RUNS_*); `entrypoint_runs` (the verdict is RUNS_CLEAN or RUNS_AFTER_REPAIR: the smoke criterion as before; the D-42 sustained check confirms it only in TEST). A level is a count of stored fields (API-REPORTED by the tagging rule). Levels never change a verdict.

**B. The blocker report** (`result.blocker`, deterministic, written for every run that does not end RUNS_CLEAN): the last link of the error chain with its class and family, the phase, the attribution (REPO / ENV / SANDBOX_QUOTA), the evidence line quoted from the record, `fixable_by` (`deterministic` when a v1.x rule exists for the class; `model` when only a model proposal could; `human` when the run needs something the sandbox cannot supply; `platform` for a sandbox limit) and `what_a_human_must_supply`, one sentence from a fixed per-class table. The table is code (`backend/app/services/blocker.py`) with a test per class on a recorded DEV or gate failure.

**C. Classifier rules for the recorded blockers** (rule G: class-level, each replaying a recorded DEV or gate failure, no entry special-casing): `API_REMOVED` (new code, family Dependencies: `ImportError: cannot import name 'X' from 'pkg'`, `AttributeError: module 'pkg' has no attribute 'X'` where `pkg` is a third-party package, not the repository's own module and not a standard-library one; recorded: DEV #17, DEV #12, gate #08; the time machine's removed-API rows F2/F2b already act on some of these, the code lets the record say what the blocker is when they do not); `DATA_MISSING` widened (`AssertionError:` whose message names a dataset or a download, DEV #9; a `FileNotFoundError` inside a DataLoader worker, gate #03); `GPU_REQUIRED` widened (`Cannot access accelerator device when none is available`, `is not implemented on the CPU`, a CUDA default tensor type on a CPU build; DEV #14; a GPU-only operation is `fixable_by: human`); `APT_MIRROR_GONE` (new code, family Environment, attribution ENV, so INDETERMINATE and never BLOCKED: `E: Failed to fetch http://...debian... 404`, DEV #16: the base image's distribution has left the mirrors, not the repository's fault; it moves #16's class only in v1.6 records, the v1.5 records stand); `DEP_BUILD_FAILED` (new code, family Dependencies: `Encountered error while generating package metadata`, `subprocess-exited-with-error` in a build step; gate #07). All other rules and their order are unchanged; a new code is appended to the taxonomy and to every list that enumerates codes.

**S. A source for a missing dataset (Tavily, at runtime).** When the blocker is `DATA_MISSING`, one Tavily call with the dataset name or path and the repository name; up to three results (url, title) stored on `result.blocker.sources` with the query. No model reads them; they are for the human the report is addressed to. A run with no Tavily key stores `sources: null` and the reason.

**Not in v1.6** (stated so it is not read in): no new repair, no new shim, no change to the smoke criterion or to "confirmed", no data-preparation step run in the sandbox (a candidate for v1.7), no change to any sandbox-touching file (the harness-v1.5.1 seal carries over; if that turns out false the seal is re-run, option B).

**Measured and reported, before it is run.** For every round or phase at a v1.6 tag the report adds, beside the existing counts, the ladder per entry and the blocker table (class, fixable_by, what a human must supply, sources found). The v1.5 primary metric (TEST, confirmed RUNS_*, target 3 of 8) is unchanged and reported first. The ladder for TEST is reported with it, as counts, with the words "the ladder was defined after the DEV rounds" beside them. No rate from n = 8.

**Fix process** (rule G, unchanged): a replay test per rule on the recorded failure; an independent read-only review before the tag; tag `harness-v1.6.0`; a CHANGELOG line naming the failures targeted. If round 3 (harness-v1.5.2) runs before the tag, its records are a DEV round of v1.5 and are reported as such.

## harness-v1.7 — PRE-REGISTRATION (written 2026-10-04, after DEV round 4, before any v1.7 live call)

**Status.** An amendment to the v1.5 dev/test protocol and to the harness-v1.6 pre-registration. It changes no verdict, no record, no gate criterion of any earlier version, no DEV/TEST split and no firewall rule. It is committed and pushed before any live call made for v1.7 (the probe of rule R1 included). It is written **after DEV rounds 1-4** and with sight of the DEV and gate records only (never a TEST record, never a TEST repository): every rule below was designed by reading the recorded failures it names and, for the DEV and gate repositories those failures came from, the repository at its recorded commit. It is therefore not a blind pre-registration of rules; what it fixes in advance is what each rule does, what it may not do, how it is tested and what round 5 measures and reports.

**Where DEV stands (`reports/dev/ROUND_1.md` .. `ROUND_4.md`, smoke level, D2).** Round 1 1 of 8, round 2 2 of 8, round 3 3 of 8 (harness-v1.5.2), round 4 3 of 8 (harness-v1.6.0; ladder 7 / 6 / 3 of 8). Round 4 **adds nothing** under D4, so under D1 the DEV loop stops after round 5 unless round 5 adds something. The stop condition stays as pre-registered: 5 of 8, or two consecutive rounds that add nothing, or a ceiling or the guard, or the time box (freeze by 9 Oct 2026).

**Owner's decisions (chat, 2026-10-04).**
- **Entry cap $2.50** (API-reported) for DEV round 5 and for the TEST phase (was $1.50). Reason: #9 ended INDETERMINATE COST_CAP at $1.3466 in round 4 and #16 reached the $1.50 cap in round 3; a data-preparation or archive-mirror step adds sandbox time to an entry. `devtest/budget.ENTRY_CAP_USD`, `launch_round.cmd` and the TEST launcher change with it, in the same commit as the v1.7 tag's records, never after a round has started.
- **Ledger ceiling $100.00** (API-reported), unchanged. The BILLED floor ($20.00) is unchanged.
- **Consequence the owner has not yet decided (stated here so that nobody reads it in later).** Rule B4's HARD check also bounds a round's worst case by the **DEV total ($40.00)**: after round 4 the DEV total is $23.7632 (`reports/dev/ROUND_4.md`), and a round's worst case at $2.50 is 8 x $2.50 = $20.00, so $43.76 > $40.00 and **the guard refuses round 5** unless the owner writes a new DEV total in chat (at least $43.77 plus the v1.7 seal and probe; $50.00 would fund both). The guard is not loosened by code or by me: until the owner writes a figure, round 5 does not start. RESERVE at the new cap: $52.9336 + $7.39 + $26.11 = $86.43 of $100.00 (OK); HARD on the ledger: $52.9336 + $20.00 = $72.93 of $100.00 (OK).

**The rules (rule G: class-level, named by the failure class, a replay test on a recorded DEV or gate failure, an independent read-only review before the tag, no entry, repository or URL special-cased).** Each rule is a deterministic step: it runs at repair time (except where said), before any model call, once per run, and is recorded on the attempt as `time_machine_action` with its `rule`, the `matched_error` and every input it used. A rule that does not preserve the program's semantics is labelled so in the verdict, the ladder and the blocker, and is never applied silently.

**R1. RESOURCE_LIMIT (the sandbox kills the process for memory).** Recorded: DEV #17 round 3 (`exit code 137`, dmesg `Out of memory: Killed process 78 (python3) ... anon-rss:3864856kB`), gate #11 v1.4.1, v1.4.2, v1.4.3 (`Killed process 76 (python) ... anon-rss:3895992kB`). MemTotal 4034744 kB (3.85 GiB), nproc 4, SwapTotal 0 in every evidence block. What the records show, stated before any fix: each kill names **one** Python process holding about 3.86 GB anonymous memory, so the kill is the main process itself, not a pool of DataLoader workers; #11's code already passes `num_workers=0`; #17's passes `num_workers=2` and runs through `sh ./fs_train.sh`.
- **(a) Probe, the first live call of v1.7** (one detached run launched by the owner, cap $0.10 API-reported, recorded under `runs/sandbox_verification/v1.7-probes/`, its cost a row of `ledger_extras.json`). On `python:3.10-slim`: `free -m`, `ulimit -a`, `/proc/sys/vm/overcommit_memory`, the cgroup memory files (v2 `memory.max`, v1 `memory.limit_in_bytes`), `/proc/swaps`, the root file system type; then `fallocate -l 4G` (else `dd`) a swap file, `mkswap`, `swapon`, and if it took, a 5 GiB touch-every-page allocation in Python to show whether the swap carries a process past 3.85 GiB. On `python:3.6-slim` (for R4): `/etc/os-release` and whether `archive.debian.org/debian` serves `Release` for `<codename>` and `<codename>-updates`, and `deb.debian.org` / `security.debian.org` for the same suites. Raw outputs committed.
- **(b) `swap_file`, only if the probe shows that swapon works and the 5 GiB allocation survives.** A RERUN-owned command, run in the same shell immediately before the documented command on every operation that executes it (the file is created at execution time, outside every kept image, so no image grows by 4 GiB): create a 4 GiB swap file, `mkswap`, `swapon`, print `RERUN_SWAP_FILE <result>`; a failure prints the reason and the documented command runs anyway. Written into the build plan as a note and into every execution record. Semantics: unchanged (the same program, the same inputs; only paging). If the probe shows swap cannot be enabled, (b) is not built and the pre-registration says so in the round report.
- **(c) `memory_hook`, regardless of (b).** A `.pth` hook (runner_hooks, Python 3.6-compatible, base64 like the others), installed at repair time on a run whose failure was classified RESOURCE_LIMIT (as the CPU shim is installed on GPU_REQUIRED), before the RESOURCE_LIMIT stop: after `torch` is imported it wraps `torch.utils.data.DataLoader.__init__` so that an **explicit** `num_workers > 0` becomes 0 and `pin_memory=True` becomes False, printing one line `RERUN memory_hook: DataLoader num_workers N->0` to stderr per process; an argument the caller did not pass is left to torch. The re-execution also gets `MALLOC_ARENA_MAX=2` and `OMP_NUM_THREADS=4` in its environment (runner_env). Semantics: preserved (the same samples in the same order, loaded in the main process; the sampler's shuffling does not depend on the worker count; arena count and thread count change no result beyond floating-point summation order of multi-threaded kernels, which OMP_NUM_THREADS=4 on a 4-CPU sandbox leaves as it was). Expected effect, stated before the round: none on #11 (already `num_workers=0`), some on #17 (two workers fewer); the kill is the main process, so (c) alone is not expected to clear either.
- **(d) `resource_adapt`, the fallback, NOT semantics-preserving.** Only when (b) and (c) are in place (or (b) was not buildable) and the re-execution still ends with a kill evidenced (exit 137 / -9 or an OOM line). Only for a documented command that runs a Python entry directly (`[VAR=value ...] python [flags] script.py ...` or `python -m module ...`, the exit wrapper's parser; a shell script such as `sh ./fs_train.sh` is not adapted). The batch-size options are the argparse options of the entry script and of the repository modules it imports directly, read statically (AST, no execution, no paid `--help` run; the owner's draft named `--help`: the AST read finds the same options and their literal defaults without a sandbox operation) whose name matches `^--(train[-_]|test[-_]|eval[-_]|val[-_])?(batch[-_]?size|bs)([-_](train|test|eval|val))?$`; the value is the one on the command line, else the literal `default=` of the `add_argument` call; an option with neither is not adapted. Each such option is set to half its value (integer, at least 1) on the re-execution, at most twice (1/2, then 1/4). The verdict text carries **RESOURCE-ADAPTED** with the exact arguments (`--batch_size 256->128`), the ladder adds `resource_adapted: true`, the blocker (if any) says so, and the certificate and dashboard print it beside the verdict. A RESOURCE-ADAPTED RUNS_* verdict counts in the DEV count but is always reported with the count of adapted entries beside it ("N of 8, of which K resource-adapted"), and in TEST the confirmed count is reported with and without them.
- **Tests:** replays of DEV #17 round 3 and gate #11 v1.4.2 and v1.4.3 (the recorded evidence classifies RESOURCE_LIMIT; the hook is installed before the stop; resource_adapt finds `--batch_size` and `--test_batch_size` with defaults 256 in #11's entry and refuses #17's shell-script command); real-torch tests of the hook (WSL). **Seal:** option B over `runner_hooks.py` and `runner_env.py`.

**R2. GPU_REQUIRED where the operation has no CPU kernel (CPU reference kernels).** Recorded: DEV #14, rounds 1-4: `RuntimeError: linalg.lu_factor: LU without pivoting is not implemented on the CPU` (the repository calls `torch.lu(x, pivot=False)` and keeps `triu` of the factor). The CPU shim gains a table of torch kernels that have no CPU implementation and a pure-torch reference implementation of each, starting with LU without pivoting: `torch.lu`, `torch._lu_with_info`, `torch.linalg.lu_factor`, `torch.linalg.lu_factor_ex` and `torch.linalg.lu` with `pivot=False` (Doolittle elimination, batched, the input's dtype and device, returning the tuple torch returns: the packed LU, pivots `1..min(m, n)` as int32, and the info tensor where torch returns one). Each wrapper calls the original first and uses the reference only when the original raises an error containing `not implemented on the CPU`, printing `RERUN_CPU_SHIM_PATH: <kernel>` once per process. Semantics: preserved: LU without pivoting is unique (unit-diagonal L) whenever it exists, so the reference computes the same factorisation the CUDA kernel computes, up to floating-point rounding; it is not the pivoting `lu_factor` the round-3 model patch substituted (D-44). Tests: on random well-conditioned matrices (diagonally dominant, float32 and float64, batched and not, square and rectangular) `L @ U == A` within 1e-5 (float32) and equals `scipy.linalg.lu_factor`'s factor where partial pivoting makes no row exchange (column-diagonally-dominant matrices); a replay of #14's round-3 and round-4 records (the recorded stderr classifies GPU_REQUIRED; the shim is installed for it; the reference path fires on the call). **Single-case**: GPU_REQUIRED with no CPU kernel is recorded on #14 only. Seal option B over `runner_hooks.py`.

**R3. DATA_MISSING where the repository documents a preparation step (`data_prep`).** Recorded: DEV #9 round 4 (`AssertionError: Download cifar10 dataset!!`, then COST_CAP); gate #3 v1.4.3 (`FileNotFoundError: Caught FileNotFoundError in DataLoader worker process 0.`); DEV #4 rounds 1-4 (`original.png`, placeholders `[model_path]`). At repair time, on a failure classified DATA_MISSING, before any model call:
- **(a) a documented script.** The README files read are the root `README*`, `docs/*.md`, and the `README*` of any directory the root README links to or names (`./data/cifar10`, "follow the instructions in `README.md`"). A script qualifies if a README names it, it exists in the repository, and its file name matches `^(download|prepare|get|fetch|generate|make|build|create)[_-]?(the[_-]?)?(data|dataset)s?\.(sh|py)$` (the owner's draft listed download/prepare/get/fetch; generate/make/build/create are added because DEV #9's documented step is `data/cifar10/generate_data.py`; no other name is added). The invocation is the first command of the first fenced code block of that README that runs the script (backslash-continued lines joined), verbatim, in the script's directory; a script no README invokes in a code block runs with no arguments. When several datasets have scripts, the one whose directory name appears in the evidence line (`cifar10`) is chosen; with none named, the rule does not fire.
- **(b) else a documented archive.** An `http(s)` URL in a README ending in `.tar.gz`, `.tgz`, `.zip` or `.npz`, within 3 lines of the word download or dataset, downloaded into the directory the evidence path names, else the one the README names, else not fired; archives are extracted there.
- **Caps and limits.** 180 s wall clock for the step; at most 500 MB written (measured after the step; over the cap, the step's output is deleted and the step is recorded as over cap); a command containing `sudo` is refused, never rewritten; nothing is fetched that the README does not name; no file is created to satisfy a path (never fabricate inputs).
- **Record** (`time_machine_action.data_prep`): the README file and line quoted, the command or URL, bytes written or downloaded, sha256 of the script or archive, seconds, exit code. The Tavily dataset lookup of v1.6 item S queries with the dataset name the README gives when it gives one.
- Semantics: the authors' own documented preparation; no code changes. Tests: replay of #9's round-4 record (the rule finds `data/cifar10/generate_data.py` and the README's first invocation, `python generate_data.py --n_tasks 80 --n_components 3 --alpha 0.4 --s_frac 1.0 --tr_frac 0.8 --seed 12345`, run in `data/cifar10`); gate #3 v1.4.3 and DEV #4 as **negative controls** (#3's README links an HTML page, not an archive, and names no script; #4's inputs are placeholders): the rule must not fire. Firing is single-case (#9); the class is covered by three recorded entries. Not sandbox-touching unless a listed file changes.

**R4. APT_MIRROR_GONE (the base image's Debian release has left the mirrors; `apt_archive`).** Recorded: DEV #16 round 4 (`E: Failed to fetch http://security.debian.org/debian-security/pool/updates/main/p/perl/perl-base_5.32.1-4%2bdeb11u5_amd64.deb 404`, python:3.6-slim, bullseye) and earlier rounds of #16; DEV #9 round 3 (python:3.7-slim, the same `bullseye-security ... 404 Not Found` lines). At repair time, on APT_MIRROR_GONE, instead of the INDETERMINATE stop (once per run): every apt command of the plan and of the time machine is prefixed by one RERUN-owned shell step that reads `VERSION_CODENAME` from `/etc/os-release` and, only for an end-of-life codename (stretch, buster, bullseye), writes `/etc/apt/sources.list` as `deb http://archive.debian.org/debian <codename> main` (plus `<codename>-updates` only if the probe shows the archive serves it), drops the security line, writes `Acquire::Check-Valid-Until "false";`, and prints `RERUN_APT_ARCHIVE <codename>`; then the apt command runs as before. A live codename is left alone. Recorded in the build plan. Semantics: the same Debian release's packages from its official archive. If the re-execution still ends APT_MIRROR_GONE, the INDETERMINATE stop applies as before. Tests: replay of #16 round 4 and #9 round 3 (the classification, the step, the rewritten command); a live check in the seal (`python:3.6-slim`: `apt-get install -y build-essential` succeeds after the rewrite). The step is a command string built by `runner_env` and run inside the sandbox: option B over `runner_env.py`.

**R5. DEP_UNPINNED_CONFLICT between a framework and its companion (`companion_relax`).** Recorded: DEV #5, every record since v1.3.2: the runner's torch-family install `pip install torch==1.2.0 torchvision==0.5.0 torchaudio 'numpy<2' ...` ends `ResolutionImpossible` in phase `runner_setup` (torchvision 0.5.0 requires torch 1.4.0; the repository's own `requirements.txt` pins both). When the failing command is the runner's torch-family install, the output says ResolutionImpossible, and the command pins torch and torchvision exactly to a pair the companion table lists as incompatible: keep the torch pin (the primary: it decides the numerics) and replace the torchvision pin by the release the table lists for that torch; re-execute. The table is a dated snapshot of the torchvision compatibility table (pytorch/vision README), generated beside the CPU wheel table by `scripts/build_torch_wheel_table.py`, never read at run time. TensorFlow/Keras pairs are not in the table (no recorded failure). The swap and the reason are recorded on the attempt and in the build plan. Semantics: the repository's torch is kept; its torchvision is not (the authors cannot have run the pinned pair together); labelled `dependency change: companion relaxed` in the certificate. Test: replay of #5's round-4 record. **Single-case** (#5 only).

**R6. D-44, a model patch that changes what the code computes (reporting only, no repair).** In the tamper gate, a patch that passes is marked `semantic_change: true` when its diff touches a call in a fixed list: `torch.lu`, any `linalg.*`, `solve`, `inverse`/`inv`, `eig`/`eigh`/`eigvals`, `svd`, `cholesky`, `qr`, `det`, random seeds (`manual_seed`, `random.seed`, `np.random.seed`, `set_seed`), dtype casts (`.float()`, `.double()`, `.half()`, `.to(dtype`, `astype`), and loss functions (a call whose name ends in `loss` or `Loss`, or `criterion`). The verdict text becomes `RUNS_AFTER_REPAIR (semantic change)` in the certificate, the dashboard and the ladder; the flag does not change the verdict code or the counts, and every round report counts flagged entries beside the DEV count. D-44 is registered in the defect register. Test: the round-3 record of #14 (its passing patch swapped `torch.lu(..., pivot=False)` for `torch.linalg.lu_factor`).

**Not in v1.7.** No change to the smoke criterion, to "confirmed", to the DEV/TEST split, to the firewall or to any verdict of a recorded run. #4 (placeholders `[model_path]` in the documented command) is a legitimate BLOCKED and no rule targets it.

**What round 5 measures and reports (DEV, at harness-v1.7.0, entry cap $2.50, after the owner's DEV total decision).** The pre-registered DEV count (D2) with its kinds; D4 against rounds 1-4 (round 5 must add something or the loop stops); the ladder and blocker per entry; for each rule R1-R5, the entries it fired on, what it recorded, and the entry's ending; the number of RESOURCE-ADAPTED and semantic-change verdicts beside the count; the cost API-reported and the BILLED reading. No rate from n = 8. Expected, stated now and not a target: R2 and R5 can each move one entry (#14, #5) past its recorded blocker; R3 and R4 can move #9 and #16 past theirs; whether any of them then reaches a RUNS_* verdict is what the round measures. The v1.5 primary metric (TEST, confirmed RUNS_*, target 3 of 8) is unchanged and reported first.

> Annotation, 2026-10-04 (before the probe ran): the probe's "$0.10 API-reported" is enforced as follows, stated so nobody reads it as a hard ceiling: the script refuses a cap above $0.10, does not start operation 2 if operation 1 cost more than the cap, and records any overshoot (`cost_over_cap_usd`); an operation's own cost is only known after it ends, so the hard bound is the operation timeouts (60 s memory, 45 s apt), at most about $1.21 API-reported at the recorded $0.0115 per sandbox second. Script and launcher: `reports/corpus-v2.1/v1.7/probe/` (Task Scheduler, owner).

> Annotation, 2026-10-04 (after the independent review of the v1.7 code, before the release-candidate tag, before any v1.7 live call except the probe): where the implementation differs from the text above, stated so the round-5 report is read against what actually runs. Nothing above is edited.
> - **R1 (c) is not fully semantics-preserving, and is now labelled** (review H2). Same samples, same order; but with no workers, random augmentations draw from the main process's random stream, so a seeded run does not repeat its random draws. A loader over an IterableDataset (iterated once per worker unless it shards itself) or with a `worker_init_fn` is left as is. Wherever the verdict is shown, a run where the hook changed a DataLoader carries `memory hook: DataLoader num_workers N->0`.
> - **R1 (d)** waits for the swap decision (`runner_env.SWAP_FILE_DECIDED`, False until the probe's record is read). It acts only on a kill of the documented command itself (phase `repo_run`), never on an install-phase kill. It edits only the value of the batch option (under any alias the add_argument call declares), keeps every other character of the command, and refuses a command that uses an abbreviation of a batch option.
> - **R3**: the over-cap clean-up deletes the files the step CREATED (by a path snapshot, whatever their timestamps) and never deletes a file that existed before; the record counts changed files it could not restore. On the time cap, the step's whole process group is killed. Archive members other than plain files and directories are refused. Bytes are counted inside the repository tree only. A command that fails the safety check is refused; the rule does not go on to the next code block.
> - **R4**: the step runs in a subshell. Prefixed to the apt command, it moves that command after the runner's torch step (the setup splitter in `sandbox_limits.py`, unchanged, files it with the requirements). A baseline APT_MIRROR_GONE goes to the apt-archive step first: the era lock does not run before it, and therefore not at all for that entry (the time machine runs at the baseline only). v1.6 stopped there with no time machine either.
> - **R5** fires only when pip's own `ResolutionImpossible` text is in the output, and is labelled as a dependency change on the verdict, the ladder, the blocker and in the build plan (review H1). The table is PyPI's `Requires-Dist` per torchvision release, not the pytorch/vision README (whose table pairs torch 1.2 with torchvision 0.4.1, which requires torch 1.3.0). torchvision 0.12.0's metadata does not pin torch, so torch 1.11 has no entry and the rule does not fire for it.
> - **R6**'s list as implemented also includes lstsq, pinv, symeig, logdet, `default_rng`/`RandomState`, `.int()/.long()/.short()`, `.type(torch.` and `set_default_dtype`, all of the same kinds as the list above.
> - **The blocker** never claims `deterministic` for a kernel without a CPU implementation. It says whether this run's CPU shim carried the reference kernel, so a certificate served after v1.7 does not rewrite what an older run could do (review M5).

> Annotation, 2026-10-05 (after the probe and an independent review of what was drawn from it, before the release-candidate tag; nothing above is edited). The probe ran once, launched by the owner at 06:42 UTC (07:42 local): `runs/sandbox_verification/v1.7-probes/probe_20261005T064245Z.json` (commit ace4aa3), $0.0162 API-reported of the $0.10 cap, no overshoot. Two pre-registered readings returned nothing: `free` is not installed on the image, and no cgroup memory file was readable (`/proc/self/cgroup` is `0::/`); `/proc/meminfo` gives MemTotal 4034744 kB, SwapTotal 0.
> - **R1 (b) `swap_file` is not built, and the probe does not settle whether it could be.** The root file system is virtiofs; `fallocate -l 4G` returned 0, `mkswap` returned 0, `swapon` returned 255 (`Invalid argument`; kernel line `swapon: swapfile has holes`); the allocation was skipped. The script takes dd only when fallocate fails, and fallocate did not fail, so a fully written file was never tried; "has holes" is what the kernel says of a file whose blocks it cannot map, which an unwritten fallocate'd file can be. The record therefore shows that the pre-registered positive condition was not met; it does not show "swap cannot be enabled".
> - **R1 (d) `resource_adapt` stays off** (`runner_env.SWAP_FILE_DECIDED = False`). Its pre-registered condition is "(b) in place, or (b) was not buildable", and neither is shown. A first draft of this change set the flag to True under the second clause; the independent review named that an over-claim and it was withdrawn before any commit. **Deviation from the pre-registration, stated:** a follow-up probe, not pre-registered ("one detached run"), is added to settle it: `reports/corpus-v2.1/v1.7/probe/run_v17_probe_dd.py`, one operation on python:3.10-slim, a 2 GiB file written with dd, mkswap, swapon, and the 5 GiB allocation if swapon takes; cap $0.10 API-reported, hard bound its 90 s timeout; launched by the owner, its record committed beside the first. If swapon takes and the allocation survives, (b) is built before the release-candidate tag; if it fails again, (b) is recorded as not buildable on this sandbox and (d) is switched on, labelled RESOURCE-ADAPTED as pre-registered. The owner may instead decide in chat to switch (d) on without the follow-up; that would be recorded here as a deviation, not as the pre-registered clause.
> - **R4 suites.** The probe (python:3.6-slim, bullseye) got 200 for the Release file of `bullseye`, `bullseye-updates`, `buster` and `buster-updates` on `archive.debian.org/debian`, and `apt-get update` against the archive's `bullseye main` returned 0 with a `build-essential` candidate (12.9). So bullseye and buster are written as `main` plus `<codename>-updates`; stretch was not probed and stays `main` only. The security line is dropped as pre-registered; the archive also answered 200 for `debian-security bullseye-security`, which is not used. What has not run live: `apt-get update` with a `-updates` line (the seal's check N3, on bullseye, is its first live run), and anything at all on a buster image (two Release-file statuses are the whole evidence for buster; N3 does not cover it). **An observation that does not match the rule's premise, reported as it is:** `deb.debian.org` and `security.debian.org` also answered 200 for the bullseye Release files on 2026-10-05, so the release has not left those mirrors' indexes; the recorded failures (DEV #16, DEV #9) are 404s on package files under `pool/`. The rule fires on the recorded class (APT_MIRROR_GONE), not on the Release files, and whether the archive rewrite clears those 404s is what N3 and round 5 measure.
> - **Not pre-registered, reported:** the one-time Task Scheduler entries of rounds 3 and 4 fired again at 23:58 local on 2026-10-04; both returned exit 4 (the budget guard's refusal) within a second (`dev_round3_launcher.txt`, `dev_round4_launcher.txt`; each round's stdout log, which is not committed, ends `REFUSED: HARD: DEV spent $23.7632 + a round's worst case $20.00 passes the $40.00 DEV total`); nothing ran, nothing was spent. The probe's scheduler entry was set to fire a second time at 23:59 local on 2026-10-05 and was disabled in the session of that morning (no record of this exists in the repository).
> - **Owner's decision (chat, 2026-10-05): DEV total $50.00** (API-reported; was $40.00). HARD check for round 5: $23.7632 + 8 x $2.50 = $43.7632; with the probe ($0.0162) and the seal at its cap ($1.50), $45.2794 of $50.00, before the follow-up probe (cap $0.10). Ledger ceiling $100.00 and BILLED floor $20.00 unchanged.

> Annotation, 2026-10-05, later (after the follow-up probe, before the release-candidate tag; nothing above is edited). **Deviation from the pre-registration, stated:** the follow-up probe was not pre-registered (the pre-registration names one probe). The owner approved it in chat and it was launched from this session through Task Scheduler at 08:00 UTC: `runs/sandbox_verification/v1.7-probes/probe_dd_20261005T080007Z.json`, $0.0043 API-reported of the $0.10 cap, no overshoot. It wrote a 2 GiB file with dd (`dd rc=0`, 2097152 KiB allocated on disk, so no unwritten blocks), `mkswap rc=0`, and swapon returned 255 again (`Invalid argument`; kernel `swapon: swapfile has holes`); the allocation was skipped. Reading: the sandbox root (virtiofs) cannot back a swap file however it is written, which is the pre-registered "(b) was not buildable".
> - **R1 (b) `swap_file`: not built, not buildable on this sandbox.** **R1 (d) `resource_adapt`: active** (`runner_env.SWAP_FILE_DECIDED = True`). It is NOT semantics-preserving; every verdict it touches carries RESOURCE-ADAPTED with the exact arguments, and round 5 reports its count with and without adapted entries. Owner's instruction (chat, 2026-10-05): switch on the labelled fallback if swapon fails, recorded as a deviation; this paragraph is that record.
> - Not tested: a block device or zram swap (the image lists no zram/loop module; `/proc/modules` is absent). A larger instance is not offered by the SDK (v1.4.3 finding).
> - DEV total check after both probes: $23.7632 + 8 x $2.50 + $0.0162 + $0.0043 + seal cap $1.50 = $45.2837 of $50.00.

> Annotation, 2026-10-05, after the harness-v1.7.0 seal (nothing above is edited). **The seal of harness-v1.7.0-rc failed; deviation from the plan, stated.** Attempt 1 (owner-approved, Task Scheduler, 08:08 UTC, `runs/sandbox_verification/v1.7-seal/`, commit baf4dce): stages v142 and runner_env passed; in stage v17, N1 (LU reference, memory hook), N2 (data_prep) and N3 (apt_archive on bullseye: archive main + bullseye-updates, build-essential installed, gcc ran) passed, and **N4 (R5) failed**: torch==1.2.0 with torchvision==0.4.0 installed, then `import torchvision` raised `ImportError: cannot import name 'PILLOW_VERSION' from 'PIL'` (pip had resolved the newest Pillow). Spend $1.1071 API-reported. No harness-v1.7.0 tag exists or will exist; the next version is harness-v1.7.1.
> - **Owner's decision (chat, 2026-10-05), option 1b:** R5 pins Pillow beside the old torchvision, DEV #5 scope only, labelled as part of "dependency change: companion relaxed", never called semantics-preserving. If the re-seal fails again, R5 is dropped from v1.7 (no further paid iteration on it).
> - **What R5 does at harness-v1.7.1.** A swap to torchvision 0.4.0 also pins `Pillow==6.2.2` (`runner_env.REPLACEMENT_NEEDS`; only that release is listed, rule G). Checked offline from the wheels before any paid run: torchvision 0.4.0's `transforms/functional.py` imports `PILLOW_VERSION`; Pillow 6.2.2 defines it; Pillow 9.5.0 does not (its source: "PILLOW_VERSION was removed in Pillow 9.0.0"). Pillow 7.x and 8.x were not checked; 6.2.2 is the pin the wheels prove. A pip dry run for Python 3.7 manylinux reproduces the seal's set exactly (Pillow 9.5.0 without the pin, 6.2.2 with it; numpy 1.21.6, six 1.17.0, torchaudio 0.3.0 either way). `future`, which PyPI lists for torch 1.2.0, is not required by the CPU wheel, whose only such import is `from builtins import bytes` (standard library on Python 3).
> - **A second defect in R5, found by the offline review, fixed in the same change.** R5 changed only the runner's torch step; the repository's own `pip install -r requirements.txt` runs after it, unchanged. DEV #5's file (at its recorded commit 203e94a) pins `torchvision==0.5.0` and `Pillow==9.0.0` itself, so the as-built R5 would have reached the same torch/torchvision conflict one step later, and Pillow 9.0.0 lacks the name too. At harness-v1.7.1 the swap's pins also go into RERUN's copy of the requirements (`.rerun-requirements.txt`, env_repair; the repository's file is never edited), for each package the file already names. The label names every pin: `dependency change: torchvision 0.5.0->0.4.0, Pillow 9.0.0->6.2.2`. The seal's N4 now runs that whole path (torch step, then the requirements copy, then the imports).
> - **An expectation for round 5, stated before it runs:** DEV #5's `requirements.txt` pins `requests==2.22.0` (which requires `urllib3<1.26`) and `urllib3==1.26.5`. The file cannot be installed as published, whatever R5 does. R5 can at best move #5 past the runner-setup blocker to a repo-install conflict; a RUNS_* verdict on #5 is not expected from R5.
> - **Independent review of the harness-v1.7.1 diff (2026-10-05):** no high finding. Two medium findings, both fixed before the tag: the line that makes later requirements edits start from the swap's copy was untested (test added, and a mutation that removes the line now fails it), and the seal's N4 estimate left about $0.05 of the guard's headroom (re-based on attempt 1's recorded N4 cost, $0.1073 API-reported, to $0.20 ESTIMATED). Low findings fixed: the label for a ranged, bare or absent requirement line; the reason text; stale N4 descriptions; a comment that presented the dry run's Pillow 9.5.0 as recorded. **Open, stated:** the swap's runner pins stay in force for the rest of the run, so if a later model change re-pinned Pillow in the requirements copy and the run then succeeded, the label would still name 6.2.2; such a run fails at install today (the torch step and the copy disagree), so no verdict can carry a wrong label without a failure first.
> - **Live UI check (2026-10-05, before the tag; frontend and backend on localhost, demo mode, a fresh database):** two defects found and fixed. (1) The demo replayed DEV round 3, not the latest round: the record patterns stopped at harness-v1.5.x (`demo_seed.RECORD_PATTERNS`, now every tag; test added). (2) The certificate download omitted the five bundle-v4 fields, so every downloaded v4 certificate failed `scripts/verify_passport.py`; with them, the bytes the button produces verify (checked in the browser against three certificates; frontend test added). Display only: no record, verdict or passport hash changes.

> Annotation, 2026-10-05, after the harness-v1.7.1 seal (nothing above is edited). **Seal attempt 2 passed** (Task Scheduler, 09:13 UTC, `runs/sandbox_verification/v1.7.1-seal/`, against harness-v1.7.1-rc = c2f34fc): v142 $0.0194, runner_env 4 of 4 $0.6063, v17 4 of 4 $0.5066; total $1.1322 API-reported. N4 installed through the torch step and RERUN's requirements copy and imported torch 1.2.0+cpu, torchvision 0.4.0+cpu and Pillow 6.2.2. N3 rewrote bullseye to the archive (main + bullseye-updates) and gcc ran. `seal_verification.json`: 23 paths, 8 re-verified live, 11 carried over, 4 new, 38 live run ids. The writer's release-candidate check was corrected before it was run: the driver records `git rev-parse <tag>`, which for an annotated tag is the tag object; both sides are now peeled to the commit (the record is unchanged). Tag harness-v1.7.1 follows on the commit that carries these records. Spend: the two seal attempts cost $2.2393 API-reported together.

> **FREEZE for the TEST phase (2026-10-05; nothing above is edited).** The DEV loop stopped after round 5 by its own rule (D1/D4: two consecutive rounds that add nothing). **Owner's decision, typed in chat on 2026-10-05:** run the TEST phase exactly as pre-registered: the 8 TEST entries (never opened, run or tuned on), TREATMENT, once each, at the frozen harness, then the D-42 sustained run for each RUNS_* entry that needs one; **ledger ceiling $130.00** API-reported (was $100.00; `devtest/budget.LEDGER_CEILING_USD`, which the TEST runner reads), **TEST cap $30.00** (entries and sustained runs together), entry cap $2.50, BILLED floor $20.00 unchanged. The result is reported whatever it is, fewer than 3 of 8 confirmed included; no entry is re-run to improve the count (the one pre-registered exception, an INFRA_ERROR entry with no baseline execution, stays as written in section T); nothing is tuned on a TEST result.
> - **What is frozen.** The harness paths are byte-identical to the sealed `harness-v1.7.1` (`seal_verification.json`, seal attempt 2); the freeze tag `harness-v1.5-final` is its own commit (this one), not the tag of any DEV round, and carries only records, reports, documentation, Phase D assets, the deployment files of `deploy/hf-space/` and the ceiling constant above beside the sealed code. The labels of harness-v1.7 (RESOURCE-ADAPTED, semantic change, memory hook, dependency change) apply to TEST verdicts as to DEV ones, and the confirmed count is reported with and without resource-adapted entries.
> - **Worst case at the freeze**, from the ledger reader (`devtest/budget.read_spend`): ledger $65.9273 + TEST cap $30.00 = $95.9273, and with the owner's one live UI run (cap $2.50, outside the protocol, a DEV entry, labelled REAL and DEV) $98.4273, of $130.00.

## harness-v1.7.2, the out-of-sample scan and TEST-B — PRE-REGISTRATION (written 2026-10-05, before the harness-v1.7.2 seal, before any corpus-v3 draw or scan pick)

**Owner's decisions, typed in chat on 2026-10-05:** paid runs allowed within an API-REPORTED ledger ceiling of **$300.00** and a BILLED floor of **$10.00** (balance read by the owner: $45.81 BILLED, `reports/dev/BILLED_READINGS.md`); entry cap $2.50; the worst case is printed before every paid phase (`reports/ledger_total.py`); anything that burns money unexpectedly stops its phase. Order: UI check, offline engineering, a paid seal and the tag, one out-of-sample scan, TEST-B, texts. Devpost stays a draft; the owner submits.

**What harness-v1.7.2 is.** The D-46 / D-47 fixes, module-level entrypoint discovery, entry blockers, the sole-candidate rule (a POLICY CHANGE, labelled SOLE CANDIDATE on the certificate), the self-inflicted-candidate rule (`reports/dev/FIXES_harness-v1.7.2.md`), then D-45, D-48 and D-49 (`reports/corpus-v2.1/candidate_v1.3.3_defects.md`), the new UI and the corpus-v3 tooling. **None of the five sandbox-touching files differs from the sealed harness-v1.7.1.** The changes are tested offline (tests that fail on the old code, an independent review). The owner asked for a real paid seal anyway: every live stage of the harness-v1.7.1 seal runs again at `harness-v1.7.2-rc` (`reports/corpus-v2.1/v1.7.2/seal/`, cap $1.50); the tag `harness-v1.7.2` is cut only if every check passes.

**Status of the earlier evidence, fixed now.** The TEST numbers (2 of 8 confirmed as pre-registered; 1 of 8 actually ran after the D-46 audit) belong to harness-v1.7.1 code only. The first 5-repo live scan and its two re-scans (`runs/live_scan/`, `v1.7.2/`, `v1.7.2b/`) are EXPLORATORY: v1.7.2's fixes were tuned on those repositories, so they are not independent evidence. D-45 to D-49 and the other scan-driven fixes were found, fixed and tested offline; none is re-measured on the TEST set.

**Out-of-sample scan (5 new repositories).** Selection rule: `reports/live_scan/oos_v172/select_repos.py` (its docstring is the rule: five GitHub topics, one repository each, the first search result that passes RERUN's firewall and has Python code), committed before it runs, run once after the tag. The repositories are scanned once each at `harness-v1.7.2` through RERUN's own API (`reports/live_scan/run_live_scan.py`, entry cap $2.50), reported as found, labelled "out-of-sample for harness-v1.7.2", and never used to tune anything; a defect it shows is a known limit.

**TEST-B (corpus-v3, 8 new papers' repositories).** Everything is fixed in `backend/app/batch/corpus_v3/prereg.json` (sha256 in `prereg.sha256`), committed in the release candidate before any corpus-v3 candidate is screened: the population and eligibility of corpus-v2, seed 20261005, 8 entries, a firewall against every repository RERUN has ever recorded or screened (checked again after the draw), the run (TREATMENT, once each, at `harness-v1.7.2`, entry cap $2.50, TEST-B cap $95.00 including the D-42 sustained runs) and the analysis: the primary measure **RAN** (rules R1-R4: a RUNS_* verdict, confirmed as in the TEST phase, not a silent exit 0, and not struck by the D-46 audit, whose strike rules are written there), with semantic-change, resource-adapted and sole-candidate entries reported beside it and a second line without semantic change. No target. Run by `reports/test-b/run_test_b.py`; nothing is re-run (one INFRA_ERROR retry, as in TEST) and nothing is tuned on a TEST-B result; the old TEST set is not re-run and is never pooled with TEST-B.

## harness-v1.8 and TEST-C: PRE-REGISTRATION (written 2026-10-07, before the harness-v1.8.0 tag, before any corpus-v4 draw)

**Owner's directive, 2026-10-07:** ship harness v1.8 and a fresh pre-registered held-out test (TEST-C) by Oct 16. The "no tuning after a held-out set" rule is lifted ONLY for this new version, which gets its own untouched held-out set. TEST, TEST-B and the out-of-sample scan stay frozen as published and are never re-run or re-scored under their old names. Budgets as already authorised (ledger ceiling $300.00 API-reported, BILLED floor $10.00, entry cap $2.50; the BILLED balance read by the owner on 2026-10-07 was $44.37, $0.77 billed over the whole harness-v1.8 DEV interval that recorded $31.66), every billed reading recorded (`reports/dev/BILLED_READINGS.md`).

**What harness-v1.8 is** (`reports/dev/FIXES_harness-v1.8.0.md`; triage `reports/dev/V18_TRIAGE.md`): T1 (narrowed as the owner wrote it), T2, T3, T5, T6 (naming only), T7, T9, T10, T11, T15, T17 (label only), T19, and the evidence-driven diagnosis. **The tamper gate's rules are unchanged** (`tamper_gate.py` and `env_repair.py` are identical to harness-v1.7.2) and **no sandbox-touching file changed**, so by the v1.7.2 precedent no paid seal is needed; `check_seal_verification` passes at HEAD (every sandbox-touching blob equals the one the seal verified). The 21 old held-out entries were re-run as DEV-CONTAMINATED (`runs/dev_v18/`: the fixes were written from them; no number from them is attributed to TEST, TEST-B or the OOS scan): RAN 3 of 16 (2 audited), the same as before; no blocked entry became a run. The DEV run found defects in the new diagnosis itself (D-68), fixed and tested; the DEV score of the diagnosis is 9 of 18 as the runs stored it and 16 of 18 as the corrected rules derive it (a fit).

**The diagnosis as a result** (`reports/dev/v18/DIAGNOSIS_RUBRIC.md`, committed before TEST-C is drawn): "actionable diagnosis" = four criteria (A1 verbatim, A2 right cause, A3 concrete next action, A4 anchored in the final state), scored by `score_diagnosis.py` against a key written from each record's raw log BEFORE any blocker text is read and committed before scoring; reported beside RAN, never merged, per blocker family. The frozen sets are not scored by it.

**TEST-C (corpus-v4, 10 new repositories).** Everything is fixed in `backend/app/batch/corpus_v4/prereg.json` (sha256 in `prereg.sha256`): the population and eligibility of corpus-v2 and corpus-v3 UNCHANGED (E1-E4, E5_v2; nothing in them looks at what a command needs, so docker, conda, licensed-data, GPU or credential repositories are not excluded; `test_v18_test_c.py` pins that), seed 20261007, 10 entries, the firewall extended with corpus-v3 and every record under runs/ and reports/, the run (TREATMENT, once each, at `harness-v1.8.0`, entry cap $2.50, TEST-C cap $100.00 including the D-42 sustained runs; an entry the cap stops is reported as such and the cap is not raised), and the analysis: RAN under R1-R4 and the D-46 audit exactly as in TEST-B, the actionable-diagnosis count beside it, the blocker-family strata, the per-set medians and the recovery rate. **Thresholds from the DEV evidence, committed now:** the claim "the diagnosis is actionable" only if at least 50 percent of the non-running entries are actionable (the DEV as-stored 9 of 18); a claim that RAN improved only if RAN is at least 3 of 10 (the earlier fresh sets: 1 of 8 and 1 of 8; the DEV re-run 2 of 16); otherwise TEST-C says the claim is not supported. Run by `reports/test-c/run_test_c.py`; nothing is re-run (one INFRA_ERROR retry, as before) and nothing is tuned on a TEST-C result; no change to a harness path after the draw.

**TEST-C result (2026-10-07; `reports/test-c/TEST_C_RESULT.md`).** Drawn once at the pushed tag `harness-v1.8.0` (35 candidates screened, 10 eligible; corpus_hash `b7cd56d4...`) and run once: **RAN 1 of 10** against the registered claim threshold of 3 of 10 (not met: no improvement in RAN is shown); **actionable diagnosis 7 of 9** non-running entries against the registered 50 percent (met as scored, with the caveats stated there: six of the seven are class sentences, none of the DEV-written evidence rules fired, and the same key applied to harness-v1.7.2's reports gives 4 of 9). Published as it came out; nothing re-run, nothing tuned.

## harness-v1.9 (2026-10-08): the anti-cheat claim measured, four TEST-C defects fixed — what was written down before what

Owner's limits: a $25.00 ledger cap for the pass (the pass spent $1.3851 API-reported, all on steamctl), BILLED floor $20.00 (reading before the pass $43.70). TEST-A/B/C are frozen and never
re-scored as a headline; a v1.9 re-derivation of any of their records is labelled post-hoc and never merged. Order and pre-commitments (each commit precedes the measurement it governs):
rubric for "genuine fake" vs "honest patch rejected" `reports/v1.9/counterfactual/RUBRIC.md` (eed2809, amended before any judgement in 1f7e12c to judge adopted patches too); steamctl plan and
driver (5f7d372, before the first run; decision rule: bisect only if v1.7.2 runs at least 2 of 3 and v1.8.0 0 of 3); planted corpus, seeded split and protocol (6caf274, before the gate ran on
either half); the held-out half gated with the harness-v1.8.0 gate (a4fb8c4); the harness-v1.9 code (ba356f5) committed before the held-out half was gated again, once (73c2865). Rules kept:
the fixes were developed on the five DEV rounds' records and the dev half only (the four records the owner named are the regression fixtures); no change was made to the gate in response to a
held-out row; an independent review of the diff preceded the held-out re-run and its findings were fixed first; no sandbox-touching file changed (no paid seal); the tamper gate's rules existing
before v1.9 are unchanged, and the v1.9 additions are one new rule (`SKIPPED_MISSING_INPUT`) and the documented-file exemption from the test-file naming rule. Results: `reports/v1.9/RESULT.md`.

## harness-v1.10 (2026-10-08): the full pipeline measured against planted cheats, an independent cheat set, behavioural checks measured once — what was written down before what

Owner's limits: a $60.00 ledger cap for the pass (start $162.6946), BILLED floor $20.00 (reading before the pass $43.24 at 2026-10-08 10:59 Africa/Algiers), measurement closed by 2026-10-14, TEST-A/B/C frozen, no new
fresh draw; after Task 1 the old held-out half is development material only. Order and pre-commitments (each commit precedes the measurement it governs): the full-pipeline protocol, claim rule, cost rule,
scenarios and driver (3b945d3, before the held-out half ran at harness-v1.9.0); the Task 1 result file (76da9c2); the independent set, its verbatim author instructions, provenance and hash (dded732, before it
was measured; PROVENANCE.md discloses what the assistant read of it and every change to the checks after it was copied in); the measurement protocol and summary-sentence rule for the behavioural checks
(`reports/v1.10/behaviour/PROTOCOL.md`, committed with release candidate 1, 982423f); the confirmation of the set (af9f5ba); release candidates 2, 3 and 4 after three independent reviews, each by a fresh reviewer who could
not see the independent set (`reports/v1.10/behaviour/REVIEW.md`); the two measurements of the independent set (7089843) at the tags `harness-v1.9.0` and `harness-v1.10.0-rc4`, with no rule changed after the first look at either.
Rules kept: the checks were developed on the planted corpus's DEV half and its spent held-out half only; every cheat of the independent set that did not reach exit 0 was dropped and listed, none edited; the v1.9.0 run
step of each patch is its confirmation run (same tag, image, overlay and launcher; four ids whose reconstructed text differed by a character were run again); the summary-sentence rule's branch (false refusals above
30%) was applied as written. A sandbox-touching change (`smoke_exec.py`, the new `behaviour.py`) needs a live seal: rc4's did not pass (`runs/sandbox_verification/v1.10-seal-rc4/`: a tracer defect on Python 3.10, found after the measurement and fixed in rc5 with a regression test; the defect changes no measured outcome, shown record by record in `NOTE.md`); rc5's passed its `smoke` and `v110` stages and its `v140` stage could not upload its 56 MB tree over this machine's link (`runs/sandbox_verification/v1.10-seal/`), so no `harness-v1.10.0` tag was made. The post-hoc wiring check's plan recorded its move from rc4 to rc5 before the attempt that would count; both attempts ended INFRA_ERROR before any model call. Results: `reports/v1.10/RESULT.md`.

## harness-v1.10 flag mode (owner's directive of 2026-10-09): DECISIONS, recorded before any code of this pass

* **Verdicts stay harness-v1.9.0.** No verdict rule changes in this pass. The pre-registered branch of the v1.10 measurement (false refusals above 30%, `reports/v1.10/behaviour/PROTOCOL.md`) stands: the
  behavioural checks do not refuse anything in the submission harness.
* **The v1.10 checks become advisory (a review flag).** A patch they would have refused keeps its harness-v1.9.0 verdict, and its certificate carries `REVIEW_REQUIRED` with the named reason
  (`COMPUTATION_CHANGED`, `EXIT_FROM_ADDED_LINE`, ...). The mode sits beside the existing ones (off, refuse). **This use was chosen after the results were seen** (2026-10-09, after the
  measurement of 2026-10-08); every place that shows a number of the flag says so. The flag-mode numbers are derived offline from committed records, not measured by a run of the flag mode.
* **Anti-cheat leaves the headline.** harness-v1.9.0 adopted 14 of the 50 independent cheats aimed at repositories whose run really fails (28%), above the 25% line: the headline is what RERUN
  does and 3 of 26, then diagnosis 7 of 9 (6 of 9 strict); the benchmark and its per-layer tables follow, then the limits.
* **Fallback.** If the flag mode is not sealed and tagged (`harness-v1.10.0`) by **2026-10-14**, harness-v1.9.0 is the submission harness and v1.10 is reported as an experiment. An unsealed mode is
  not shipped.
* **Budget.** $25 ledger cap for this pass (ledger at its start $186.2082, stop at $211.21), BILLED floor $20. No paid run before the owner sends a BILLED reading; everything before the seal is offline.
* **Where the paid checks run.** The seal and the live wiring check of the flag-mode release candidate run on a GitHub Actions runner (owner's choice, because this machine's upload link cannot carry
  the seal's 56 MB upload): a `workflow_dispatch`-only workflow outside the sealed harness paths, actions pinned by commit SHA, read-only repository permissions, the Nebius key from a repository secret
  the owner adds. Its records come back as an artifact and are committed; then the seal verification is written and the tag made. This replaces D-43's Task Scheduler for these two runs only.
* **Independent review** of the flag-mode diff by a fresh reviewer before the seal, as in the earlier release candidates.
* **The adaptive cheat set** (a separate author given the allow-list, 50 cheats that fit it, honest controls, hashed, measured once in flag mode) is attempted only if the flag mode, the workflow,
  the benchmark package and the regenerated texts are pushed by 2026-10-12; otherwise it is listed under "not measured".
