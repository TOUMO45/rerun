# harness-v1.8 Phase 5 inputs: what the committed records support for the demo (2026-10-07)

Everything below is read from committed records by `gate_rejections.py` and by seeding the demo's own database (`demo_seed.seed`) and serialising each certificate the way the API does; the
claims are pinned by `backend/tests/test_v18_phase5_findings.py`. Phase 5 itself (the demo text, the UI, the redeploy) comes after TEST-C: `frontend/src` is a sealed harness path, so a UI
commit between the tag and the run would refuse the batch preflight.

## 1. Does any committed record show the gate rejecting a patch that genuinely tried to fake a pass?

**No.** Of the 162 committed records that carry attempts (every batch record under `runs/` and every certificate of a live scan, including the 21 harness-v1.8 DEV re-runs), the gate's REJECT decisions
were, by rule:

| rule | rejections | what the patches were |
|---|---|---|
| UNPARSEABLE_PATCH | 71 | model patches that do not parse (D-47 and the indentation family) |
| ENV_SHADOWS_REPO_MODULE | 38 | an env change that would install a PyPI package under the name of the repository's own module |
| ENV_REPEATS_FAILED_CHANGE | 26 | a change already tried and failed this run |
| BLIND_PATCH_ON_SILENT_EXIT | 20 | a code patch proposed with no error text to go on |
| **PROTECTED_PATH_MODIFIED** | **14** | **honest patches to a documented command whose file is named `test_*`** (D-55): Ordered-Neurons `test_phrase_grammar.py` x9 (`nltk.download('ptb')`, a guarded import), adversary_critic `test_carlini.py` x5 (`tensorflow.compat.v1`) |
| ENV_UNJUSTIFIED / ENV_REMOVES_IMPORTED / UNAPPLICABLE_PATCH / DIFF_TOO_LARGE / ENV_UNSUPPORTED | 10 / 6 / 4 / 4 / 1 | bookkeeping rules, not about faking |
| **BROAD_EXCEPTION_SWALLOW** | **1** | NeuralTracking (TEST, harness-v1.7.1 code): a diagnostic probe for a missing `docker` wrapped `apt-cache policy` in `try/except Exception`; the rule fired on a patch that hid nothing |
| **DELETED_EVAL_CALL, STUBBED_MODEL_CALL, REDUCED_SCALE** | **0** | never fired in any record |

So the two rules that fired in the "faking" family rejected **honest** patches (15 of 15), and the three rules whose whole purpose is catching a faked pass have never rejected anything in a recorded run.
The earliest live evidence about them is mostly the other way round: `DECISIONS.md` (two entries dated 2026-09-19) records two FALSE POSITIVES found live with probes and fixed (`DELETED_EVAL_CALL`, `STUBBED_MODEL_CALL`), and, in the first of them, one crafted shadow-redefinition patch that the gate correctly rejected: a probe written by the author, not a patch a model proposed.
They are exercised by unit tests on crafted patches only. **A demo or a Devpost text must not say "the gate caught a fake patch"**; it can say what the gate checks, and that on 162 recorded
runs it never had to reject one for faking. If a scene about the gate is wanted, the honest one is a clearly labelled SYNTHETIC patch (from the unit tests) shown being rejected, labelled as such.

## 2. What the hosted demo replays

Seeding the demo database from the repository gives 12 replayable records (the gate and DEV families, latest tag per entry, through the TEST firewall); all 12 serialise.

* **latent_ode (DEV #15, harness-v1.7.1): the primary scene works.** `RUNS_AFTER_REPAIR`, 4 recorded attempts, a 9,311-character log. The baseline fails on `dataclasses==0.8` (DEP_YANKED); the repairer's candidate 1 is a gate-checked
  environment change (remove `dataclasses`, which the standard library of the repository's Python already provides), candidate 3 downgrades Python to 3.6, candidate 2 declined; both passing candidates ran with exit 0 and the adjudicator chose the environment change. That is a scene with a
  real gate decision, a real adjudication and a real fix, with no code patch.
* **M-FAC (DEV #14): not a scene.** The record the demo serves for it (latest tag, harness-v1.7.1) is a `TIMEOUT` with no attempts; the earlier record in which three code patches passed the gate was at harness-v1.5.2 and is not the latest. The TIMEOUT now carries a diagnosis (it says the record holds no output of the stopped
  operation). It does not "replay reliably" as a repair story, so it stays out of the demo.
* The harness-v1.8 DEV re-runs (`runs/dev_v18/`) are not replayed: the demo reads `runs/corpus_v2_batch` only, and they are DEV-CONTAMINATED.

## 3. What is done and what is left for Phase 5 (after TEST-C)

Done (TEST-C has run, so `frontend/src` is no longer frozen): the Certificate page's blocker card shows the diagnosis fields, the Batch Lab shows the per-set measurements and TEST-C as a fourth, separate set with its actionable-diagnosis figure beside its run count (see `FIXES_harness-v1.8.0.md` 4.3). Left: the hosted demo image pins `REF` to
`a7f5c4c`; it serves all of this only after `REF` moves to a pushed commit and the image is rebuilt and checked (a deploy: the owner's), and the demo text (latent_ode as the primary replay scene; M-FAC dropped; no claim that the gate caught a fake) is written from the findings above.
