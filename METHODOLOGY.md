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
