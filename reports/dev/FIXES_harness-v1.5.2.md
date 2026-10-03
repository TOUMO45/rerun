# harness-v1.5.2 — fixes between DEV round 2 and the next step

Protocol: METHODOLOGY.md "harness-v1.5 dev/test protocol", rule G. Round 2 ran at `harness-v1.5.1` (`reports/dev/ROUND_2.md`): 2 of 8 at smoke level (#15, #17; both `smoke_alive`). This batch fixes
what round 2's records show about the F2 step. It has NOT been run live: whether it is run depends on the budget guard (the ledger ceiling is the owner's) — the code is reviewed and
replay-tested, not validated by a DEV round. No sandbox-touching file changed (`runner_hooks.py`, `sandbox.py`, `sandbox_limits.py`, `runner_env.py`, `smoke_exec.py` are byte-identical to harness-v1.5.1),
so `seal_verification.json` is the v1.5.1 seal and no live check is needed.

| fix | failure class | recorded failure (DEV) | covered by the class | label |
|---|---|---|---|---|
| F2b TensorFlow row completed | the code uses an API a newer release removed (F2): the older release needs its OWN family | #12, round 2 (`harness-v1.5.1/dev/12_Mehran-k__SimplE.json`): the step pinned `tensorflow==1.15.5` on top of an era lock written for TensorFlow 2.1 (`tensorboard==2.1.0`, `tensorflow-estimator==2.1.0`); pip: `Cannot install -r .rerun-requirements.txt (line 29) and tensorboard==2.1.0 ... conflicting dependencies`, and the model's own tries (`tensorflow-estimator==1.15.0`, then unpinning) failed the same way | #12 (and any TensorFlow-1 repository whose lock was written for TensorFlow 2); the torch row has no companions | class-level; the companion rows are **single-case** (only #12 shows them) |
| F2c put-back on any setup-phase failure | a deterministic step must never leave the run worse than not taking it | same record: the conflict surfaced in the `repo_install` phase, the put-back (then `runner_setup` only) did not apply, and every model candidate ran from the broken plan | #12 (the torch row's companion-pin conflict of the first review is the same shape) | class-level |

## What changed

- **F2b.** `api_removals.Companion` / `companion_actions`: beside `tensorflow==1.15.5` the step now (a) swaps `tensorboard`, `tensorflow-estimator` and `gast` for the releases TensorFlow 1.15.5 requires
  (`1.15.0`, `1.15.1`, `0.2.2`) when the requirements or the era lock hold them; (b) swaps a `numpy` pinned `==` at or above 1.19 for `1.18.5` (an unpinned or ranged numpy is left to pip); (c) ensures a
  `protobuf` pinned `==` below 3.21 (`3.20.3`, `3.19.6` on Python 3.6), replacing an unpinned, ranged or newer one; (d) REMOVES `tensorflow-gpu` / `tensorflow-cpu` lines (the pinned `tensorflow`
  provides the import; PyPI has no tensorflow-cpu 1.15.5), never pinning them. The data is TensorFlow 1.15.5's PyPI metadata (gast==0.2.2, numpy<1.19, protobuf>=3.6.1, tensorboard>=1.15.0,<1.16.0,
  tensorflow-estimator==1.15.1, h5py<=2.10.0; retrieved 2026-10-03). The decision is a pure function (tested without a sandbox).
- **F2c.** The put-back applies when the changed environment fails in `runner_setup` OR `repo_install` (the repository's command is always the last step, so it cannot have run). The recorded
  `time_machine_action` says why (`put_back`) and which companions were added, swapped or removed.

## Independent review of this batch (a read-only subagent, as in v1.4.2)

No HIGH. Findings and answers: (1) MEDIUM, a lock naming `tensorflow-gpu` / `-cpu` still conflicted → the alias lines are removed (tested with a `tensorflow-gpu` lock); (2) MEDIUM-LOW, an unpinned or
`>=` protobuf counted as held → "ensure": only an exact pin below 3.21 is kept (tested); (3) LOW-MEDIUM, a late-2020 lock (`gast==0.3.3`, numpy 1.19) → gast and numpy are swapped (tested); (4) LOW, the
put-back discards the conflict text, so the model may recreate the conflict → **not done**: it needs new text in the repair prompt and the earlier conflicts are now handled deterministically; recorded as a
limit; (5) LOW, tests: the swap test now reads the lock from the committed round-2 record, the recorded build plan after a put-back is asserted, an invalid companion mode is refused, mutation checks
(ensure / alias / numpy limit) fail the tests as they should. Unverified by the reviewer and still so: a `SandboxTimeoutError` during the changed install raises without a put-back (as for every other
deterministic step); that the swapped environment imports and runs (needs a live sandbox).

## Seen in round 2 and deliberately NOT fixed

- **#9**: with F1 it now runs on Python 3.7 and stops at `assert os.path.isdir(cifar10_path), "Download cifar10 dataset!!"` — the repository's own data-preparation step (documented in its README, outside
  the corpus entry's one command) was never run. A missing-dataset class (DEV #4 and #9). No deterministic, general, non-invasive fix.
- **#14**: `LU without pivoting is not implemented on the CPU` (a CUDA-only operation). Two more shim gaps appear in the candidates' stderr (`torch.set_default_tensor_type(torch.cuda.FloatTensor)`,
  `torch.accelerator` device lookups), but the stored tails do not show a clear call site for the second, and neither changes #14's verdict: no shim path was added on thin evidence (rule G).
- **#16**: the end-of-life Debian 11 mirrors again (`python:3.6-slim`, two rounds). The exact package that 404s on `security.debian.org` IS served by `archive.debian.org` (HTTP 200, checked), but
  `archive.debian.org/debian-security/` has no `bullseye-security` suite and `security.debian.org`'s `bullseye-security` Release is emptied: there is no mirror configuration that gives a consistent
  index. One entry; not fixed.
- **#5**: the repository's own `torch==1.2.0` / `torchvision==0.5.0` cannot coexist (unchanged).
- **#4**: placeholders and missing input files (unchanged; a legitimate BLOCKED).
