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

- **Upload limit enforced: 120 MiB = 125,829,120 B.** That is under the smaller reading of "128 MB"
  (128,000,000 B) with 1.7 % of headroom; the archive size is measured exactly, so the margin only covers the
  server's accounting. The unit is **not settled by evidence**: (1) `125,009,920` (harness-v1.2's cap) is not a
  Nebius number: it is the top step (125 MB decimal + tar overhead) of RERUN's own pre-registered probe ladder
  25/50/75/100/125 MB, which stopped there; (2) the first probe uploaded a 150 MB archive (above both readings)
  and only failed afterwards inside the operation (ENOSPC), so the endpoint did not reject it either.
  A boundary probe at 128,000,000 / 134,217,728 B would settle it; it has not been run.
- **Over the limit → in-sandbox download, never a local upload.** Only the manifest and verifier are uploaded;
  the sandbox fetches the pinned commit (`codeload.github.com` tarball; no git needed in the image) and checks every
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
  - **exception (deliberate):** `torch`/`torchvision`/`torchaudio` missing → ENV, because the runner provides them by policy;
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
*Open on 2026-09-29:* the spend cap as first written, 3× the pilot's spend, is $1.13, below one control arm's expected cost (the v1
corpus batch cost $8.53 on harness-v1.2), so no batch has been started; the operator's number is awaited.
The driver's own hard ceilings stay: $2 per entry, $40 per arm.
