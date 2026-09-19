# DECISIONS.md — Autonomous build log

Every non-trivial decision made while executing `RERUN_BUILD_DIRECTIVE.md` is logged
here, in chronological order, with what was chosen, what was rejected, and why. This is
the audit trail for the human to review the agent's judgment after the fact.

---

## 2026-09-19 — Repo bootstrap

**Decision:** Initialized a plain `git init` repo at `B:\Desktop\RERUN_Nvidia` (no
existing VCS state found — the directory only contained `RERUN_BUILD_DIRECTIVE.md`).
Created the full directory skeleton from §4.2 of the directive up front, before writing
any implementation code, so every file has an obvious home as it's built.

**Rejected:** Waiting to create structure lazily, file-by-file. Rejected because the
directive's architecture (§4) and repo layout (§4.2) are already fully specified —
there's no discovery step needed, so building the skeleton first avoids later
reshuffling.

---

## 2026-09-19 — Local toolchain

**Observed:** Local machine has Python 3.14.4, Node v24.15.0, npm 11.12.1. The
directive pins **Python 3.11** for the backend (§4.1). Decision: target Python 3.11 in
`pyproject.toml` (`requires-python = ">=3.11,<3.13"`) and in the sandbox execution
image, since 3.11 is the stack the directive fixes and what target paper repos will
most reliably support — but development/test execution on this machine will run under
whatever interpreter is actually installed (3.14) unless a 3.11 interpreter or venv is
provisioned. This does not violate rule §2.7 (fixed stack) since the *target* runtime
for FastAPI/sandbox stays 3.11-declared; it only affects which interpreter runs pytest
locally during this build. Flagged: if any 3.11-only syntax/behavior assumption turns
up, a local 3.11 venv should be installed via `pyenv`/`uv` before Phase 0's live gate.

---

## 2026-09-19 — Order of implementation within Phase 0/1/2

**Decision:** Within a single build pass, implement and test the **pure, deterministic,
no-network, no-credential** modules first — `classifier.py` (§5.2), `tamper_gate.py`
(§5.3), and `passport.py` (§6.3) — ahead of `sandbox.py`'s live Nebius Token Factory
integration, even though Phase 0 is nominally "first" in §11's table.

**Why:** Phase 0's actual gate (`pytest tests/test_sandbox_smoke.py` green with 3 real
sandboxes created and destroyed) requires a live Nebius Token Factory API credential
that is not present in this environment yet (no `.env`, no key supplied). Rule §2.4
("never invent a method signature and hope") and the anti-fake-result rule in §0 both
forbid writing a sandbox test that claims to pass without hitting the real API. Writing
the deterministic modules first produces real, independently-runnable green tests
*today* (`pytest tests/test_classifier.py`, `pytest tests/test_tamper_gate.py`,
`pytest tests/test_passport.py`) while the sandbox client code is written to the real
Nebius API shape (verified via docs, not guessed) and left ready to run the moment a
`NEBIUS_API_KEY` is supplied in `.env`.

**Blocker surfaced to human (not a stop, just a note):** Phase 0's live gate cannot be
marked green until `NEBIUS_API_KEY` (and any Token Factory sandbox/project id) is
provided. This is tracked, not blocking forward progress on Phases 1–2's deterministic
cores, batch corpus research, and frontend scaffolding.

---

## 2026-09-19 — classifier.py implemented and green (Phase 1 core)

**Decision:** Implemented `backend/app/services/classifier.py` as pure regex/rule
matching over `(exit_code, stderr, stdout, declared_deps)` — no network, no model call,
per §2.1. All 12 taxonomy codes from §5.2 are represented; `ENTRYPOINT_UNCLEAR` is kept
as a shared constant only (never emitted by `classify()`) since that verdict is decided
pre-execution by recon, per §6.1 — a dedicated test
(`test_entrypoint_unclear_is_not_reachable_from_classify`) locks this in so a future
edit can't accidentally wire a post-execution regex to it.

**Result:** `pytest tests/test_classifier.py -v` — 26/26 passed. Every taxonomy code has
≥1 positive test and ≥1 negative-control test, satisfying the Phase 1 gate in §11.

**Rejected alternative:** Classifying by parsing tracebacks structurally (e.g. via
`traceback`/`tokenize`) instead of regex. Rejected because target repos' failures come
back as opaque captured stderr text from a sandboxed subprocess, not a live exception
object — regex over text is the actual available signal, and it is fully deterministic
and auditable, which is what §2.1 requires.

---

## 2026-09-19 — tamper_gate.py implemented and green (Phase 2 core, the differentiator)

**Decision:** Implemented `backend/app/services/tamper_gate.py` using `unidiff` for
diff parsing and stdlib `ast` (not `libcst`) for structural analysis, per the explicit
"unidiff + libcst (or ast)" alternative in §4.1's stack table — chosen because the gate
only ever needs read-only structural analysis (does this call still get reached, is
this except-handler new and broad), never lossless source rewriting, so the heavier
`libcst` CST dependency buys nothing here. `libcst` was therefore dropped from
`backend/pyproject.toml`.

**All six §5.3 rejection rules implemented:** `DELETED_EVAL_CALL`,
`STUBBED_MODEL_CALL`, `REDUCED_SCALE`, `BROAD_EXCEPTION_SWALLOW`,
`PROTECTED_PATH_MODIFIED`, `DIFF_TOO_LARGE`. One defensive rule was added beyond the
six: `UNPARSEABLE_PATCH` — if a patch doesn't even parse as valid Python after
reconstruction, the gate rejects rather than silently skipping its other checks on that
file, since a deterministic gate must never PASS something it cannot actually verify.

**Reachability analysis (closes a §14 red-team gap up front):** rules 1 and 2 don't just
count textual occurrences of a matched call — they compare the set of calls *reachable*
from module-level execution (a best-effort, single-file call graph: module-level
statements → transitively into any locally-defined function they call) before and after
the patch. This specifically catches the exact failure mode §14 calls out: "wrapping
the eval call in a function that's never called" would leave a naive text/AST-count
check unchanged, but drops the call out of the reachable set, and the gate correctly
rejects it (see
`test_deleted_eval_call_wrapped_in_never_called_function_is_rejected`). Documented
limitation: this call graph does not follow imports or track dynamic dispatch
(`getattr(obj, name)()`, decorators that rebind a function, etc.) — it is best-effort
within a single file, not a soundness guarantee.

**REDUCED_SCALE heuristic:** implemented as regex pairing of removed/added lines
matching `<scale-keyword> = <int>` (epochs, samples, dataset_size, etc.) within the same
diff hunk. The "unless already parameterized via CLI" exception (§5.3) is checked by
searching the *original* file for an `argparse.add_argument('--<key>', ...)` call
naming the same key. This is intentionally a bounded heuristic, not a general dataflow
analysis — logged here rather than silently shipped as if it were exhaustive.

**Result:** `pytest tests/test_tamper_gate.py -v` — 22/22 passed, including the exact
Phase 2 gate requirement from §11: "a hand-crafted 'delete the eval call' patch is
asserted REJECTED" (`test_deleted_eval_call_direct_removal_is_rejected`), a passing
negative control for every one of the six (now seven, with the defensive addition)
rules, and two integration tests (`test_legitimate_minimal_fix_passes_with_no_violations`
proves the gate doesn't over-reject; `test_multi_violation_patch_records_every_rule_hit`
proves multiple violations on one patch are all surfaced, not just the first).

**Bugs caught by the tests themselves, fixed before commit:** (1) the broad-exception
new-code-span check initially crashed on `ast.walk()` nodes lacking a `lineno` attribute
(e.g. `ast.Load`) — fixed by only considering nodes that actually have one; (2) the
Mock-injection detector originally required the mocked name to appear *after*
`Mock(`/`MagicMock(` in the same line, which missed the common `name = MagicMock(...)`
assignment form — fixed to a per-line co-occurrence check instead of an ordered regex.

---

## 2026-09-19 — passport.py + scripts/verify_passport.py implemented and green (§6.3)

**Decision:** `backend/app/services/passport.py` computes a SHA-256 hash over a
canonical (sorted-keys, no-whitespace, ASCII-only JSON) bundle of exactly seven fields:
`repo_url`, `commit_sha`, `build_plan`, `full_log`, `diffs`, `verdict`, `timestamp`. The
standalone judge-facing verifier, `scripts/verify_passport.py`, **intentionally
duplicates** this canonicalization logic rather than importing the backend package —
the point of an independent verifier is that it doesn't require installing or trusting
RERUN's own codebase to check RERUN's own claim. A cross-check test
(`test_standalone_script_hash_matches_backend_module`) guarantees the duplicate can
never silently drift from the original without a test failing.

**Result:** `pytest tests/test_passport.py -v` — 10/10 passed, including a subprocess
invocation of the actual standalone script against a real tamper-then-detect scenario
(`test_standalone_script_cli_detects_tampering`), not just an in-process function call.

---

## 2026-09-19 — cost_guard.py implemented and green (§9)

**Decision:** `backend/app/services/cost_guard.py` is a plain in-memory `CostGuard`
dataclass enforcing three ceilings in code (not just docs): a daily USD spend ceiling
(rolls over at local midnight), a per-run repair-attempt ceiling (§5.4's max 3,
counting REJECTs as consumed attempts, matching the repair loop's real behavior), and a
per-attempt token ceiling. Persisting the day's running spend across process restarts
is left to the orchestrator (e.g. the SQLite store) — this module owns only the
arithmetic and the refusal, not durability, to keep it a pure/simple unit.

**Result:** `pytest tests/test_cost_guard.py -v` — 9/9 passed.

---

## 2026-09-19 — intake.py implemented and green (§3 must-have #1, half of recon)

**Decision:** `backend/app/services/intake.py` splits repo intake into a thin
network/subprocess boundary (`clone_repo`: shallow `git clone` + `git rev-parse HEAD`,
read-only per §2.5 — never pushes or authenticates) and pure parsing functions for
`requirements.txt`, `setup.py` (`install_requires`), `environment.yml` (conda + nested
pip deps), `pyproject.toml`, notebook discovery, and entrypoint-candidate detection
(name hints like `train.py`/`main.py` plus a regex for `if __name__ == "__main__":`).
The *semantic* judgment of which candidate is the real entrypoint is deliberately left
to `recon.py`'s Nemotron Nano call (not yet built) — this module only gathers facts a
human could read directly off disk, matching the "explicit code, not a hidden
abstraction" spirit of §2.8's anti-goals.

**Test approach:** `clone_repo` is tested against a **real local git repository**
created on disk in the test (`git init` + real commits in a pytest `tmp_path`), not a
mock — proving the subprocess/git integration actually works end-to-end, consistent
with the directive's "never report done without a command that actually runs" rule.

**Result:** `pytest tests/test_intake.py -v` — 16/16 passed. Full backend suite:
`pytest -v` — **83/83 passed** across classifier, tamper_gate, passport, cost_guard,
and intake.

---

## 2026-09-19 — Nebius Token Factory Sandboxes SDK researched from installed source

**Action:** Before writing `sandbox.py`, per §2.4 ("read the actual installed library
source/docs when unsure of an API — never invent a method signature and hope"),
installed the real PyPI package (`pip install contree-sdk`, resolved to v0.3.6) into
the backend venv and read its source directly, rather than trusting the hosted docs
alone (`docs.tokenfactory.nebius.com/sandboxes/...`), which a WebFetch pass had already
shown to be incomplete/inconsistent in places (e.g. the getting-started page's
`Contree(api_client)` construction pattern does not match the installed package's
actual `ContreeSync(token=...)` constructor — likely stale docs vs. a newer SDK
version). Files actually read: `sdk/client/_base.py`, `sdk/client/_sync.py`,
`sdk/managers/images/_base.py`, `sdk/managers/images/_sync.py`,
`sdk/objects/image_like/_base.py`, `sdk/objects/image_like/_sync.py`,
`sdk/objects/image/_sync.py`, `sdk/objects/image_like/result.py`, `config.py`,
`sdk/exceptions/__init__.py`.

**Key ground-truth facts this changed vs. my initial assumption from the directive:**

1. **There is no explicit `sandbox.destroy()` call in this SDK.** The execution
   primitive is `image.run(..., disposable: bool = True).wait()`, and `disposable=True`
   is the library's *own default* — the resulting image and its backing compute are
   discarded automatically the instant that run completes. Chaining steps (upload
   files -> install -> execute, each building on the previous result) requires
   `disposable=False` on every non-final step so the backend doesn't discard the
   intermediate image before the next step can reference it.
2. Given fact 1, §2.6 ("every sandbox session must be destroyed after use... enforced
   with a finally/context-manager, not discipline") is satisfied by: (a) always running
   the *last* command in a chain with `disposable=True`, and (b) wrapping the whole
   chain in try/finally, where `finally` explicitly disposes of every intermediate
   `disposable=False` image via a trivial `disposable=True` no-op run — so a
   mid-chain exception (e.g. install times out) can never leave a retained image
   behind. This is what `sandbox.py`'s `retained_images` list + `finally` block does.
3. `client.images.docker(ref)` (aliased `oci`/`podman`/`pull_by_oci`) is the right call
   for a public Docker Hub base image like `python:3.11-slim` — it tries `use(strict=True)`
   first and imports only if not already resolvable, which is cheaper than always
   forcing an import via `import_from()`.
4. Every completed step's `ContreeResult` carries a real `cost: float` (USD) — wired
   directly into `sandbox.py`'s `StepResult.cost_usd`, so `cost_guard.py` can eventually
   record actual measured sandbox spend, not an estimate.
5. Inference base URL from the real Token Factory quickstart docs is
   `https://api.tokenfactory.nebius.com/v1/` via the standard OpenAI Python client —
   **not** `https://api.studio.nebius.com/v1` as originally guessed in `.env.example`;
   corrected.

**What is still not verified:** the *async* client's public method names (this
research and `sandbox.py`'s implementation both use the synchronous `ContreeSync`
client, called from FastAPI's async routes via a threadpool executor rather than the
async client, specifically because the sync surface's method names were confirmed by
reading real source while the async naming was not independently re-confirmed in this
pass — a reasonable, boring choice per §0's "prefer boring, maintained" guidance, not a
stack renegotiation since both are the same SDK). Also unverified: real per-run cost
magnitudes, real timeout/wall-clock enforcement behavior, and whether `python:3.11-slim`
is already resolvable without an import round-trip — all of which require the actual
API key this environment doesn't have.

**Result:** `backend/app/services/sandbox.py` implements the full build-and-execute
chain against this real, source-verified API shape.
`pytest tests/test_sandbox.py -v` — 6/6 passed (pure mapping/aggregation logic and the
fail-fast credentials check, using a duck-typed stand-in for `ContreeResult` since a
live image object can't be constructed without the real API).
`tests/test_sandbox_smoke.py` — the actual Phase 0 kill gate (3 real sandboxes created
and destroyed) — is written but **honestly skipped** (`pytest.mark.skipif`, not fudged
or hardcoded to pass) until `NEBIUS_API_KEY` is supplied; this is the one remaining
must-do before Phase 0 can be marked green. Full backend suite: **89 passed, 3 skipped**.

---

## 2026-09-19 — FastAPI skeleton wired up (§4, start of Phase 3)

**Decision:** Built `config.py` (pydantic-settings, one field per `.env.example`
variable, `nebius_configured`/`tavily_configured` computed properties so routes never
re-derive "is this feature usable" logic themselves), `db.py` (SQLAlchemy engine +
session, SQLite per §4.1), `models.py` (`Run`, `RepairAttempt`, `Certificate` — shaped
directly around §5.1's verdict grades and §5.4's bounded repair loop), `schemas.py`,
and `main.py`, plus real routers:

- `POST /runs` / `GET /runs/{id}`: performs **real** S1 intake today — `git ls-remote`
  pre-flight (distinct errors for "not reachable" vs the empty/whitespace-URL case),
  then a real `intake.run_intake()` clone + parse, then a real "has Python code" check
  — all backed by the already-tested `intake.py`. It does **not** fake the
  recon/planning/sandbox/repair stages: a created run is persisted with
  `stage="RECON_PENDING"` and stops there honestly, since those stages need
  credential-backed model/sandbox calls that don't exist yet. Added
  `validate_repo_accessible`, `repo_has_python_code`, and the `RepoNotFoundError` /
  `RepoPrivateError` exception split to `intake.py` to support this (4 new intake tests).
- `GET /batch/results`: implements §7's "never render a zero or placeholder if
  `batch_results.json` is missing — fail loudly instead" as a real 502 with a specific
  message, plus an internal-consistency check (`n` must equal `len(repos)`) that
  directly forecloses the §14 red-team question "does any code path let
  `batch_results.json` render a percentage without the raw N visible/consistent?".
- `GET /healthz`: reports whether Nebius/Tavily are actually configured, for §12's
  "`/healthz` all green" Phase 6 gate.

**Verification beyond TestClient:** booted the real server with `uvicorn app.main:app`
and hit `/healthz` and `POST /runs` (against a deliberately bad URL) with `curl` — real
process, real HTTP, real git-not-found error message — not just an in-process
TestClient call. Both matched expectations exactly.

**Result:** `pytest -v` — **104 passed, 3 skipped** (the sandbox smoke test, still
honestly blocked on `NEBIUS_API_KEY`).

---

## 2026-09-19 — model_client.py, recon.py, planner.py implemented and green

**Decision:** Introduced one shared `model_client.py` as the *only* place
`openai.OpenAI(...)` is ever constructed (confirmed constructor and
`chat.completions.create` signatures by reading the installed `openai` package's
source, per §2.4, not guessed). Every model-calling service takes an injected client
object satisfying a one-method Protocol (`chat_completion`) rather than importing
`openai` directly — this is what makes `recon.py` and `planner.py`'s decision logic
fully unit-testable without a live API key: tests inject a small fake object, never a
mock of the real SDK's internals. `call_json_model()` centralizes response parsing
(including stripping a markdown code fence some models wrap JSON in) and raises
`ModelResponseParseError` — never guesses a partial result — on malformed output.

**recon.py implements §6.1's calibrated abstention as actual enforced code, not just a
prompt instruction:** the model's chosen entrypoint is checked against the candidate
list `intake.py` itself already found — a confident-sounding hallucinated entrypoint
not in that list is still rejected into `INDETERMINATE` (see
`test_parse_recon_response_rejects_hallucinated_entrypoint_not_in_candidates`). A
confidence below `MIN_CONFIDENCE = 0.6` is likewise `INDETERMINATE`, and so is any
model-call failure (bad credentials, timeout, unparseable JSON) — recon never lets an
infrastructure problem get misreported as a taxonomy failure against the repo, which is
exactly the protection §6.1 asks for.

**planner.py is deliberately mostly deterministic, plain code:** which install command
to run is decided purely by which dependency file `intake.py` found (a lookup table, no
model call), per §2.8's anti-goal that the pipeline must be explicit code a judge can
read, not a hidden framework/LLM decision. Nemotron Super is consulted for exactly one
narrow, genuinely-ambiguous thing — inferring apt packages a declared pip dependency
might need (e.g. `opencv-python` -> `libgl1`) — and a small deterministic table
(`_KNOWN_APT_NEEDS`) covers the common cases as a floor even when no model client is
supplied or the call fails, so a valid build plan is never blocked on model
availability the way recon's entrypoint choice legitimately is.

**Result:** `pytest tests/test_model_client.py tests/test_recon.py tests/test_planner.py -v`
— 7 + 11 + 12 = 30/30 passed. Full backend suite: **134 passed, 3 skipped**.

---

## 2026-09-19 — repairer.py implemented and green; closes the model-to-gate loop

**Decision:** `repairer.py` asks Nemotron Super for one candidate unified diff given a
`Classification` and the one target file's content, and **never** decides whether that
diff is acceptable — `parse_repair_response`/`propose_repair` only ever produce a
`RepairProposal` (diff text + explanation, or `declined=True`). Acceptance is
exclusively `tamper_gate.check_patch()`'s call, keeping §2.1's purity boundary intact:
the model proposes, the deterministic gate disposes. The system prompt does list the
§5.3 rules in plain language (so Nemotron isn't blindly trying shortcuts it could avoid
for free), but the prompt is explicitly *not* trusted as the enforcement mechanism —
proven by `test_repair_proposal_that_deletes_eval_call_is_caught_by_the_real_gate`,
which feeds a proposal that violates the very rule the prompt just told it not to
violate, straight through the real (not mocked) `tamper_gate.check_patch`, and asserts
it's REJECTED. This directly answers §14's first red-team question ("can a
rejected-then-corrected repair reach RUNS_AFTER_REPAIR without the gate ever seeing the
final diff?") for the proposal-generation half of the loop: no, because nothing short
of a passing `check_patch()` call ever would be applied — the orchestrator that will
call both in sequence doesn't exist yet, but the two pieces it will wire together are
now proven to compose correctly.

**Result:** `pytest tests/test_repairer.py -v` — 7/7 passed. Full backend suite:
**141 passed, 3 skipped**.

---

## 2026-09-19 — adjudicator.py implemented and green; completes the Nano/Super/Ultra trio

**Decision:** `adjudicator.py` (Nemotron Ultra) writes certificate prose but is
explicitly barred from ever improving on the verdict deterministic upstream logic
already fixed — the architecture diagram's own annotation is "certificate prose; may
only downgrade." This is enforced as plain code (`_VERDICT_RANK` + `_clamp_verdict`),
never as a prompt instruction trusted on faith: `test_adjudicator_rejects_a_model_attempted_upgrade`
feeds a fake client that dishonestly returns `"verdict": "RUNS_CLEAN"` for an actually
`BLOCKED` run, and asserts the clamp holds — the certificate still says `BLOCKED`, and
`model_attempted_upgrade=True` is recorded so this event is itself visible/auditable
rather than silently swallowed. An unrecognized verdict string from the model is
treated the same as an upgrade attempt (never given the benefit of the doubt).

**Templated fallback (§5 cut ladder item 1 — "Adjudicator prose polish -> fall back to
templated certificate text"):** `templated_certificate_prose()` is used whenever no
client is supplied, the model call fails, or the model returns empty prose — so this
stage is a genuine should-have, never a hidden dependency for producing a valid
certificate. The §8 S3 scope-boundary line ("Verifies that the artifact executes. Does
not verify the paper's numerical results.") is force-appended to any model-written
prose that omits it, so it is structurally impossible for a certificate to ship without
it — directly closing one of §14's red-team questions ahead of time.

**Result:** `pytest tests/test_adjudicator.py -v` — 8/8 passed. Full backend suite:
**149 passed, 3 skipped**. All three Nemotron-routed roles (Nano/recon, Super/planning
+ repair, Ultra/adjudication) required by §12's compliance checklist now have real,
tested integration code — none has been exercised against the live API yet (still
blocked on `NEBIUS_API_KEY`), but all are structurally ready the moment it's supplied.

---

## 2026-09-19 — orchestrator.py: the full pipeline wired together and proven end-to-end

**Decision:** `orchestrator.py` is the first module that actually runs the whole
sequence from §4's architecture diagram in one place: recon -> (§6.1 INDETERMINATE
short-circuit) -> planner -> sandbox execute -> classifier (on failure) -> bounded
repair loop (repairer proposes, `tamper_gate.check_patch` — the real, unmocked one —
decides, PASS applies via `git apply` and re-executes, REJECT records and asks again,
both consuming one of `cost_guard`'s attempt-budget slots per §5.4) -> adjudicator ->
`passport.compute_passport_hash`. Every model/sandbox call is injected via a
`PipelineDeps` dataclass rather than imported concretely, which is what makes the
*whole loop* — not just each piece separately — testable without a live API key.

**This directly answers §14's first red-team question with a real test, not an
argument:** "Can a rejected-then-corrected repair actually reach RUNS_AFTER_REPAIR
without the gate ever seeing the final diff? (It must not — trace the code path.)"
`test_reject_then_pass_reaches_runs_after_repair` scripts a fake repair model that
proposes exactly the shortcut forbidden by its own system prompt (delete the
`evaluate()` call) on attempt 1, and a legitimate fix on attempt 2. The test asserts:
attempt 1 is recorded `REJECT` by the real gate, attempt 2 is recorded `PASS`, the
run reaches `RUNS_AFTER_REPAIR`, exactly one re-execution happens (only after the
PASS, never after a REJECT), and — the strongest check — **the file on disk still
contains the `evaluate(None)` call**, proving the bad diff was genuinely never
applied, not just logged as rejected while sneaking through some other path.

**Other properties proven, not just implemented:** `test_indeterminate_recon_never_calls_sandbox`
confirms §6.1's abstention actually prevents any sandbox spend, not just a label change
after the fact; `test_blocked_after_exhausting_attempts` confirms a fully-declining
repair model still consumes exactly `max_attempts` budget slots and produces `BLOCKED`
with zero re-executions; `test_final_certificate_passport_hash_verifies` /
`test_tampered_certificate_fails_verification` confirm the orchestrator's own output
round-trips through `passport.verify_certificate` correctly, both for an honest
certificate and a tampered one.

**Design choice — no direct database writes in this module:** `run_pipeline()` takes
plain data in and returns a `PipelineResult` dataclass; SQLAlchemy persistence is left
to the FastAPI layer (not yet wired to this module — `POST /runs` still only performs
intake). This keeps the orchestrator testable with zero DB fixtures and keeps the
purity boundary between "what happened" (this module) and "how it's stored" (the
router layer) explicit.

**What remains unverified:** the real Nebius sandbox/model calls themselves (still
blocked on `NEBIUS_API_KEY`, per every prior entry), and the FastAPI route that would
call `run_pipeline()` with real credentials and persist the result into
`Run`/`RepairAttempt`/`Certificate` — that wiring is the next piece, not yet built.

**Result:** `pytest tests/test_orchestrator.py -v` — 7/7 passed. Full backend suite:
**160 passed, 3 skipped**.

---

## 2026-09-19 — orchestrator wired into the API: POST /runs/{id}/execute

**Decision:** Added `POST /runs/{id}/execute` and `GET /runs/{id}/certificate` to
`routers/runs.py`. Execute re-clones the repo fresh (a run's original `POST /runs`
workdir is a throwaway tempdir, not persisted — re-cloning by URL is simpler and no
more expensive than tracking/reusing a stale checkout), builds a `PipelineDeps` from
real settings (one `NebiusChatClient` instance reused across all three model roles,
since only the `model` argument differs per call), and calls
`orchestrator.run_pipeline()` for real. A missing `NEBIUS_API_KEY` returns a clear 503
*before* any clone or client construction happens — never a crash, never a silently
empty/fake result, per §0.

**Persistence split cleanly at the router boundary:** `_persist_pipeline_result()`
writes the `Run` row's verdict/taxonomy/attempts_used, one `RepairAttempt` row per
attempt (PASS/REJECT/DECLINED all recorded, matching what the certificate itself
shows), and one `Certificate` row carrying the real passport hash — keeping
`orchestrator.py` itself free of any SQLAlchemy dependency, as decided in the prior
entry.

**Testing approach:** the 503 fail-fast path is tested for real (no monkeypatch,
no credentials needed — this is honest, not faked). The persistence path is tested by
monkeypatching only the one credential-gated boundary (`run_pipeline` itself, plus
`get_settings` to simulate `nebius_configured=True` without a real key) — everything
downstream of that (the real clone via `fake_paper_repo`, the real DB writes, the real
`GET /runs/{id}/certificate` read-back) is exercised for real. This mirrors the same
testing discipline used everywhere else credentials are the boundary (sandbox.py,
model_client.py): mock exactly the thing that needs a live network/API key, nothing
more.

**Result:** `pytest tests/test_runs_execute_router.py -v` — 4/4 passed. Full backend
suite: **164 passed, 3 skipped**. Every piece of the pipeline described in §4's
architecture diagram now has real, tested code reachable from an actual HTTP endpoint —
the only remaining gap before a live end-to-end S1→S3 run is a real `NEBIUS_API_KEY`.

---

## 2026-09-19 — Bug found and fixed: certificate_prose was never persisted; timestamp round-trip risk

**Bug 1 (missing field):** while building the frontend's S3 certificate screen, noticed
`Certificate` (the SQLAlchemy model) and `CertificateOut` (the API schema) had no
`certificate_prose` field at all — `adjudicator.py`'s entire output (the human-readable
summary §8 S3 explicitly requires) was computed in `orchestrator._finalize` and then
silently dropped on the way into the database. Fixed: added the column, the schema
field, and the assignment in `_persist_pipeline_result`. This is exactly the kind of
gap that only surfaces when you build the consumer (the UI) of a producer's output —
logged here as a reminder that a green test suite for each piece separately doesn't
guarantee the wiring between them is complete.

**Bug 2 (found by a new test, not inspection — real correctness risk, not yet
manifested in the wild):** `Certificate.timestamp` was a SQLAlchemy `DateTime(timezone=True)`
column, populated by parsing `result.timestamp` (the exact ISO string `passport.py`
hashed) with `datetime.fromisoformat()`. Re-serializing that `datetime` object back out
through Pydantic's JSON encoding on `GET /runs/{id}/certificate` is not guaranteed to
reproduce the *exact same string* that was originally hashed (microsecond/timezone
formatting is an implementation detail of the serializer, not a contract) — which would
make a real certificate's own passport hash fail to verify against itself the moment a
judge downloaded it, directly breaking §13's definition-of-done item 6 and the entire
point of §6.3. Fixed by changing `Certificate.timestamp` to a plain `String` column
storing the exact hashed string verbatim, with zero parse/reformat round-trip, and
removed the now-unnecessary `datetime.fromisoformat()` call in the router.

**How this was caught:** `test_certificate_fetched_via_api_still_verifies_against_its_own_passport_hash`
(added specifically to test the DB-round-trip, not just the in-memory
`orchestrator.PipelineResult`, which `test_orchestrator.py`'s existing passport tests
already covered) exercises the full path: create a run, execute it (with `run_pipeline`
monkeypatched but the DB layer real), fetch the certificate back over the real API, and
assert `passport.verify_certificate()` on the *reconstructed-from-JSON* certificate.
This test initially failed for an unrelated reason (a test-construction bug — a
hardcoded fake `commit_sha` that didn't match what the router's real re-clone produces,
since `execute_run()` always overwrites `run.commit_sha` from a real `intake.run_intake`
call, not from the possibly-monkeypatched `PipelineResult`), which was itself a useful
finding: it confirmed the real production invariant (`intake_result.commit_sha` and
`PipelineResult.commit_sha` must always agree, since the orchestrator only ever echoes
the value it's given) and the test was corrected to respect it rather than the
production code being changed to satisfy a wrong test.

**Result:** `pytest -v` — **165 passed, 3 skipped**.

---

## 2026-09-19 — Frontend scaffolded: React + Vite + Tailwind, all 4 screens wired to the real API

**Design approach:** ran the `frontend` skill's design process before writing any UI
code. Concept: RERUN is an audit instrument, not a product pitch — the design leans
into a technical "lab instrument / terminal" aesthetic (near-black teal-tinted
background, phosphor-teal signal color, monospace evidence/log text, Space Grotesk for
UI chrome) rather than a generic SaaS look, specifically because the project's whole
credibility rests on looking like something a skeptical engineer would trust. The one
deliberate animated moment is a single strobe pulse on the tamper-gate REJECT card —
everywhere else stays quiet by design, per §8 S2's explicit requirement that a REJECT
"must be visually loud."

**Stack:** Vite + React 18 + TypeScript + Tailwind (scaffolded by hand, not
`create-vite`, since the interactive CLI prompt doesn't work in this non-interactive
shell) + TanStack Query for data fetching/polling (per §4.1's fixed stack) +
react-router-dom for the 4 screens (S1 Intake, S2 RunTimeline, S3 Certificate, S4
BatchLab).

**All 4 screens call the real backend, no mocked data:** verified live against a
running `uvicorn` + `vite dev` pair in the browser, not just code review —
  - S1: submitted a real invalid path (got the real git error message back verbatim)
    and a real public repo (`github.com/pypa/sampleproject` — real network clone, real
    commit SHA shown).
  - S2: clicked "Start reproduction run" against the real `/execute` endpoint with no
    `NEBIUS_API_KEY` configured and got the real, honest 503 message rendered — proving
    the fail-fast path end-to-end through the UI, not just at the API layer.
  - S4: confirmed the real fail-loud 502 state renders as a loud, distinct panel (not a
    silent 0%) when `batch_results.json` is absent, per §7 — then temporarily wrote a
    sample `batch_results.json` to verify the populated-data rendering (headline
    Recovery Rate + N, the "Estimate — not measured" label at equal visual weight to
    the estimate itself, the taxonomy breakdown bar chart, the repo table with
    click-to-expand rows), and deleted the fixture afterward — it was never committed,
    since no real batch run exists yet and committing a fake one would violate §0's
    "never fake a result."
  - The REJECT/PASS repair-attempt cards (the differentiator's visual centerpiece) were
    verified via a temporary debug route with representative sample data, since no live
    Nebius credentials exist yet to produce a real one — confirmed the REJECT card
    renders with a thick alarm-red border and the strobe animation, visually
    unmistakable from the PASS card's quiet signal-teal styling. The debug route and its
    file were removed before committing; nothing built for that check ships.

**A `.claude/launch.json` config was added** so the frontend dev server can be started
via `preview_start` (`npm --prefix frontend run dev`) in future sessions, and a Vite
dev-server proxy (`/api` -> `http://localhost:8000`) avoids CORS friction against the
local backend.

**Verified beyond dev-server behavior:** `npx tsc -b` (strict mode, no errors) and
`npm run build` (a real production Vite build) both succeed cleanly.

**What's not yet built:** an actual S2 live-streaming view (no SSE endpoint exists yet
— `POST /runs/{id}/execute` is a single blocking call, so S2 currently shows a
"Running…" state with an elapsed-time counter while the request is in flight, then
renders the full timeline retrospectively by parsing the completed run's `full_log` —
this is an honest simplification of §8 S2's "live screen" given the current backend
architecture, not a fake live stream). Also not yet built: `docker-compose` verification
of the frontend service, and hosting on Nebius Serverless Endpoints (§12).

---

## 2026-09-19 — Batch Lab corpus assembled: 20 real repos, every fact verified live

**Decision:** Rather than recall candidate paper repos from memory or trust an LLM web
search's prose summary of what a repo contains, every one of the 20 entries in
`backend/app/batch/corpus.yaml` was checked with two independent, real, live calls
during this session: `git ls-remote --exit-code <url> HEAD` (confirms the repo is
genuinely public and reachable, and captures the real commit SHA now pinned in the
corpus) and a GitHub API root-directory listing (confirms which dependency files are
actually present). This caught two real problems before they became false claims: (1) a
web-search-suggested repo (`zhutengjie/Ref-MC2-Code`) initially looked like it might
lack real code at all from a shallow root listing — direct inspection of its
`learning_materials/` subfolder confirmed genuine train.py + requirements.txt nested
there, so it was kept, accurately described as "entrypoint nested, not at root," rather
than dropped on a wrong assumption or kept with a wrong claim; (2) `facebookresearch/moco`
returned an inconsistent/empty GitHub API file listing despite reporting nonzero repo
size, and was dropped in favor of `google-research/simclr` (independently verified
complete) rather than included on unverified faith. See `METHODOLOGY.md` for the full
selection rationale.

**Explicit non-claim:** no `selection_note` in `corpus.yaml` predicts which taxonomy
code or verdict a repo will receive — the Batch Lab has not been executed (needs
`NEBIUS_API_KEY` + Nebius Serverless Jobs, `batch/runner.py` itself is not yet built).
Presenting a guessed outcome as if it were a measured one would violate §0's "never fake
a result" — `METHODOLOGY.md` says this explicitly and up front, not as a footnote.

**Structural guarantees added, not just documentation:** `backend/app/batch/corpus.py`'s
`load_corpus()` enforces exactly the invariants a real batch run needs — unique names,
unique URLs, full 40-character commit SHAs, and (per §7's "never shrink silently" rule)
a test (`test_corpus_loads_with_exactly_twenty_entries`) that fails loudly the moment the
corpus count changes, forcing any future shrink to be a deliberate, visible edit rather
than an accidental drift. A separate, explicitly-opt-in test
(`test_every_corpus_repo_is_still_reachable`, gated behind `RERUN_VERIFY_CORPUS_NETWORK=1`
so the normal suite stays network-free) re-verifies all 20 URLs live — run once during
this session and confirmed **all 20 still reachable** as of 2026-09-19.

**Known gap flagged, not solved:** `corpus.yaml` pins an exact commit SHA per repo, but
`intake.py`'s `clone_repo()` only shallow-clones the *current* HEAD of the default
branch — it does not yet support fetching an arbitrary older pinned SHA. `batch/runner.py`
will need `git fetch --depth 1 origin <sha>` plus a checkout, not a plain shallow clone,
to actually honor the pin if any corpus repo is pushed to between now and the real batch
run. Documented in `METHODOLOGY.md` rather than silently left for whoever builds
`runner.py` to discover the hard way.

**Result:** `pytest tests/test_corpus.py -v` — 7/7 passed (plus the network test, run
manually and passing). Full backend suite: **172 passed, 4 skipped**.

---

## 2026-09-19 — batch/runner.py: scoped honestly, since this is genuinely less-verified ground

**Decision:** Unlike `sandbox.py` and `model_client.py`, which were built against real
*installed SDK source* per §2.4, no Python SDK with ready-made Job-management bindings
was found for Nebius Serverless Jobs: the `nebius` PyPI package was installed and
inspected directly, and its `nebius.api.nebius.ai.v1` module exists but is an empty
stub in the installed version. The documented path is the `nebius` CLI or the raw REST
API (`docs.nebius.com/serverless/jobs/manage`, which does quote real curl examples —
`POST /ai/v1/jobs` with `Authorization: Bearer <token>`, `metadata.parentId` for the
project, `spec.image`/`containerCommand`/`args`/`resources`/`timeout`). Given this is
real but meaningfully less-verified ground than everything else built so far, the
module's docstring says so explicitly rather than presenting it with the same
confidence as `sandbox.py`.

**Scoped to what's actually solid today:** `NebiusJobsClient` implements the documented
REST shape behind the same injected-HTTP-client seam used everywhere else (tested with
a fake, no live call). `aggregate_batch_results()` — the part that turns a list of
per-repo results into the exact `batch_results.json` shape `routers/batch.py` validates
— is fully real, pure, and tested end-to-end against that real validator
(`test_aggregate_batch_results_output_passes_the_real_batch_router_validation`), refuses
to produce a result for an empty batch (never a fake 0/0), and derives the estimated
researcher-hours line strictly from the `RUNS_AFTER_REPAIR` count per §6.2's formula.

**Explicitly NOT built, flagged rather than glossed over:** the actual job container
entrypoint — a script that runs inside a Nebius Job, clones one corpus repo pinned to
its recorded commit SHA, executes `orchestrator.run_pipeline`, and reports a structured
verdict back (e.g. via stdout) for the runner to collect. `run_single_repo_job()` only
submits the job *request* in the real shape; the corresponding entrypoint script and the
full submit-and-poll-all-20 orchestration loop remain future work, alongside the actual
account-level auth flow (the `access_token` the REST API expects was not confirmed to be
the same static `NEBIUS_API_KEY` used for Token Factory inference/sandboxes — this needs
a real account to resolve, not more documentation reading).

**Result:** `pytest tests/test_runner.py -v` — 10/10 passed. Full backend suite:
**182 passed, 4 skipped**.

---

## 2026-09-19 — Bug found and fixed: orchestrator never actually enforced the daily cost ceiling

**Bug:** A self-audit re-read of `orchestrator.py` against §9's own requirement ("hard
daily cost ceiling on model + sandbox spend... enforced in `cost_guard.py`, not just
documented") found that `run_pipeline()` only ever called
`cost_guard.check_attempt_budget()`/`record_attempt()` — the per-run attempt-count
ceiling. It never once called `check_daily_budget()` or `record_spend()`, even though
`sandbox.SandboxRunResult.total_cost_usd` already carries a real cost figure straight
from Nebius's own `ContreeResult.cost` (see the `sandbox.py` entry above). The daily USD
ceiling was fully implemented and unit-tested in isolation in `cost_guard.py` and simply
never wired into the one place that actually spends money — exactly the same shape of
gap as the `certificate_prose` and cost-ceiling-adjacent bugs found earlier this
session, caught the same way: by re-reading the code that claims to satisfy a directive
requirement and checking whether it's actually true, not by re-reading the requirement's
prose.

**Fixed:** `_execute()` (the orchestrator's single sandbox-call chokepoint) now calls
`cost_guard.check_daily_budget(0.0)` before every sandbox invocation — refusing to start
a step at all once today's recorded spend has already reached the ceiling — and
`cost_guard.record_spend(result.total_cost_usd)` immediately after, so every subsequent
check reflects real spend. There is no pre-flight cost quote from the sandbox API, so
"has the ceiling already been reached" (checking `+0.0`) is the correct question to ask
before a step, not an estimate of that step's own cost. A `CostLimitExceeded` on the
very first execution finalizes as `NOT_ATTEMPTABLE` (closest existing verdict to "an
operational limit, not a code defect, stopped this"); one raised on a mid-repair-loop
re-execution stops the loop gracefully (mirroring the existing attempt-budget-exhausted
pattern) and finalizes as `BLOCKED` with the last known taxonomy code, rather than
crashing or silently continuing to spend past the ceiling.

**Tests added, not just the fix:** `test_sandbox_cost_is_actually_recorded_in_the_cost_guard`
asserts the guard's own running total reflects the sandbox's real reported cost, not just
that a method was called; `test_daily_cost_ceiling_already_exhausted_refuses_to_start_execution`
proves the sandbox runner is never even invoked when the budget is already blown;
`test_daily_cost_ceiling_hit_mid_repair_stops_the_loop_without_crashing` proves a
mid-loop ceiling breach stops the re-execution that would have exceeded it, with the
real reason recorded in the certificate's log — not a crash, not a silent continuation.

**Result:** `pytest tests/test_orchestrator.py -v` — 10/10 passed. Full backend suite:
**185 passed, 4 skipped**.

---

## 2026-09-19 — Bug found and fixed (again): the per-attempt token ceiling was also orphaned

**Bug:** Immediately after fixing the daily-cost-ceiling wiring gap, checked the other
half of §9 ("per-run token/attempt caps") the same way: `grep -rn "check_token_budget"
app/` found exactly one hit — the definition in `cost_guard.py` itself. Nothing in the
codebase ever called it. Same shape of gap as the daily ceiling: fully implemented,
fully unit-tested in isolation, never wired into anything that actually calls a model.

**Fixed at the single real chokepoint, not at each of the four call sites separately:**
`model_client.call_json_model()` — already the one place every model-calling service
routes through — now takes an optional `cost_guard` parameter and checks
`check_token_budget()` against an *estimated* token count (via `tiktoken`'s
`cl100k_base` encoding over the combined system+user prompt; Nemotron's own tokenizer
isn't available locally, so this is a stated estimate, not a billing-accurate count)
before the network call is made, never after. The new `ModelCostLimitError` is
deliberately a `ModelCallError` subclass, so `recon.py`/`planner.py`/`repairer.py`/
`adjudicator.py`'s existing `except ModelCallError:` fallbacks (§6.1 INDETERMINATE, a
declined repair proposal, templated adjudicator prose) already handle a cost-guard trip
correctly with **zero changes** to their exception-handling structure — only a
pass-through `cost_guard=cost_guard` parameter was added to each. `orchestrator.py`
threads the one `cost_guard` instance it already owns into all four call sites
(`recon.run_recon`, `planner.build_plan`, `repairer.propose_repair` inside the repair
loop, `adjudicator.adjudicate` inside `_finalize`).

**Tests:** `test_model_client.py` gained direct proof the check happens *before* the
network call (`test_call_json_model_never_calls_the_network_when_over_budget` uses a
fake client that raises `AssertionError` if ever invoked at all), that omitting
`cost_guard` changes nothing (backward compatibility for every existing call site), and
that `ModelCostLimitError` really is a `ModelCallError` subclass (the property every
existing caller's fallback logic depends on). `test_orchestrator.py` gained
`test_token_ceiling_already_exhausted_makes_recon_indeterminate_not_a_crash`, proving
the wiring reaches all the way from `run_pipeline`'s `cost_guard` argument through to a
graceful `INDETERMINATE` verdict with the sandbox never even touched.

**Pattern worth naming:** this is the second cost-guard-shaped gap and fifth real bug
this session's self-audits have caught (`certificate_prose` dropped; the passport
timestamp round-trip risk; `requires-python` blocking this machine; the daily ceiling;
now the token ceiling) — in every case a component was fully correct and fully tested
in isolation, and the actual defect was in the *wiring between* components, which no
amount of isolated unit testing could ever have caught. Worth remembering for whatever
gets built next: test the seams, not just the pieces.

**Result:** `pytest tests/test_model_client.py tests/test_orchestrator.py -v` —
12 + 11 = 23/23 passed. Full backend suite: **191 passed, 4 skipped**.

---

## 2026-09-19 — Bug found and fixed: Tavily was never actually called anywhere (§12 prize eligibility)

**Bug:** Continued the self-audit pattern one step further, this time checking a
directive requirement tied directly to hackathon prize eligibility, not just internal
safety: §12's checklist requires "Tavily called at runtime, cited in the certificate —
Best Use of Tavily eligibility" (a named $3,000 track). `grep -rn "tavily" app/`
found `tavily_api_key`/`tavily_configured` in `config.py` (used only by `/healthz`) and
a `PipelineDeps.tavily_context: str | None` field referenced exactly once in
`orchestrator.py` — but **nothing anywhere ever called the Tavily API or set that field
to anything other than `None`**. Had this shipped as-is, the certificate would never
cite a real source, and the project would have been ineligible for the track it's
explicitly built to compete in, despite `tavily-python` sitting in `pyproject.toml`
the whole time.

**Root design flaw, not just a missing call:** the original `tavily_context: str | None`
field modeled Tavily as a single precomputed string handed to the pipeline before it
starts — but a real, meaningful Tavily query needs the failure's *classification*
(taxonomy code + evidence line), which only exists mid-repair-loop, after a sandbox
execution has actually failed. A precomputed-string design could never have been wired
correctly no matter how hard the missing call was searched for.

**Fixed:** built `tavily.py` against the real installed `tavily-python` package
(confirmed via source: `TavilyClient.__init__`/`search()` signatures, and that
`search()` always returns a dict with a `"results"` key defaulting to `[]`; the exact
keys *within* each result item aren't independently source-confirmed — this client has
no bundled response schema — so they're read defensively). `build_query()` constructs a
deterministic, explainable query directly from the taxonomy code and evidence — never
left to a model to phrase, so a reviewer can see exactly what was searched and why,
right next to the citation it produced. Replaced `PipelineDeps.tavily_context` with
`tavily_client: object = None` (a real injectable client, matching every other
credential-gated dependency in this codebase) and wired `tavily.fetch_context()` into
the repair loop itself, called fresh for each attempt's current classification, with
its result threaded into the repair prompt as citable context AND recorded structurally
on `AttemptRecord.tavily_sources` — so the certificate's `diffs` JSON carries real,
structured citations, not just prose a judge has to trust was actually looked up. A
Tavily search failure is caught and logged, never crashes the pipeline (§5 cut ladder:
Tavily-cited repair context is a should-have — repair must still function without it).
`routers/runs.py::_build_pipeline_deps` now constructs a real `TavilyClient` whenever
`settings.tavily_configured`.

**Frontend also updated** (`RepairAttemptCard.tsx`): cited sources now render as
clickable links under any attempt that has them (DECLINED, REJECT, and PASS cards
alike) — verified visually via the same temporary-debug-route technique used earlier
in the session, removed before committing.

**Tests:** `test_tavily.py` (9 tests) covers `fetch_context`/`build_query` in isolation
against a fake client. Three new orchestrator-level integration tests prove the whole
chain for real: `test_tavily_is_called_during_repair_and_cited_on_the_attempt` asserts
the actual query sent, that the cited URL appears in the real prompt text Nemotron Super
would see, AND that it lands in the certificate's structured attempt record — not just
one of those three; `test_tavily_not_configured_still_completes_the_repair_loop` proves
the should-have degrades gracefully; `test_tavily_search_failure_does_not_crash_the_pipeline`
proves a Tavily outage never blocks a repair attempt.

**Result:** `pytest tests/test_tavily.py tests/test_orchestrator.py -v` —
9 + 14 = 23/23 passed. Full backend suite: **203 passed, 4 skipped**. This is the sixth
real wiring-gap bug this session's self-audits have caught, and the first tied directly
to a hackathon prize track rather than internal engineering discipline.

---

## 2026-09-19 — Bug found and fixed: the "daily" cost ceiling reset to full on every request

**User checkpoint:** after six consecutive wiring-gap fixes, asked the user directly
whether to keep self-auditing, move to a specific feature, or stop — chose to keep
self-auditing, since the pattern had a 6-for-6 hit rate on real bugs.

**Bug:** Re-reading `routers/runs.py::execute_run()` line by line (rather than grepping
for a missing call site this time — the call sites for `check_daily_budget`/
`record_spend` were now correctly present after the earlier fix) found: `cost_guard =
CostGuard(daily_cost_ceiling_usd=..., max_attempts_per_run=...)` was constructed **fresh,
inline, on every single call to `execute_run`**. Since `CostGuard._spent_today_usd`
starts at `0.0` for a new instance, this means the "daily" ceiling silently reset to
full on every HTTP request — a user (or judge) triggering 50 executions in one day would
each get a fresh, full budget, while the code believed it was enforcing a single shared
$25/day cap. The daily-ceiling arithmetic itself was correct and already proven correct
by both `test_cost_guard.py` and the orchestrator-level tests added in the prior two
entries — none of those tests could ever have caught this, because they all construct
one `CostGuard` and exercise it directly; the defect was entirely in application-level
lifecycle (who owns the instance, for how long), a layer none of the existing tests
touched. `cost_guard.py`'s own module docstring had said all along that "the orchestrator
is responsible for persisting/loading the day's running total... this module only owns
the arithmetic" — the docstring correctly anticipated the requirement; nothing had
actually honored it.

**Fixed:** added `cost_guard.get_shared_cost_guard()`, an `@lru_cache`d process-wide
singleton — the same pattern `app.config.get_settings()` already uses for exactly this
reason. `execute_run()` now calls it instead of constructing a `CostGuard` inline. This
is deliberately scoped to what the directive's actual deployment model needs (§4.1:
single-tenant SQLite, zero ops) — a real multi-process/multi-worker deployment would
need the running total persisted somewhere shared (the SQLite store itself, most
naturally), which is flagged in the new function's docstring as separate, real future
work, not something this one-line-feeling fix silently also solved.

**Test-isolation consequence, handled explicitly:** an `lru_cache`d singleton shared
across the whole test process would otherwise leak spend from one test into every test
that runs after it — added an autouse `conftest.py` fixture that clears the cache before
and after every test. This is exactly the kind of collateral concern a
process-singleton fix has to account for, not an afterthought.

**Test that actually proves the fix, not just exercises the code path:**
`test_daily_cost_ceiling_is_shared_across_separate_execute_requests` calls `POST
/runs/{id}/execute` twice, against two different runs, with a fake `run_pipeline` that
records $3 of real spend each time — then asserts the shared guard shows **$6** total
after both, not $3 twice. Before this fix, that assertion would have seen $0.0 (a fresh,
untouched guard, since the test reads `get_shared_cost_guard()` directly rather than
whatever `execute_run` happened to construct) — confirming this test would have caught
the original bug, not merely passed cosmetically alongside it.

**Result:** `pytest tests/test_runs_execute_router.py -v` — 6/6 passed. Full backend
suite: **204 passed, 4 skipped**. Seventh real wiring-gap bug this session's audits have
caught — again a component (the arithmetic) fully correct and tested, with the actual
defect in who owns and how long an instance lives, a dimension isolated unit tests
structurally cannot see.

---

## 2026-09-19 — Bug found and fixed: `.env` loading silently depended on invocation directory

**Bug:** `config.py` had `env_file="../.env"` — a bare relative string. Verified
empirically (not just reasoned about) with a real subprocess: this correctly loaded a
real repo-root `.env` when the process was launched from `backend/`, but **silently
found nothing and fell back to all-default values, with zero error**, when launched
from the repo root itself — because pydantic-settings resolves a relative `env_file`
against the process's actual current working directory at `Settings()` construction
time, and `../.env` from the repo root points one directory *above* the repo root,
where nothing exists. `config.py` had no test file at all before this entry — every
other settings-dependent test in the suite either monkeypatches `get_settings` directly
or never exercises real `.env` loading, so nothing had ever caught this.

**Why this one is a lower-severity but still real bug, not a false alarm:** Docker
deployment was never actually broken by it — `docker-compose.yml`'s `env_file:`
directive injects variables straight into the container process's real environment,
and pydantic-settings' `BaseSettings` always reads `os.environ` regardless of whether
its own file-based `env_file` loading found anything. The actual harm is local,
non-Docker development: a developer following this project's own README (`cp
.env.example .env` at the repo root) and then running the app or `pytest` from a
different working directory would silently get all-default settings — features quietly
reporting as unconfigured — with no error message pointing at why, which is exactly the
"reproducibility tool with an irreproducible setup" failure mode §4.1 explicitly warns
against, just at the config-loading layer rather than the dependency-install layer this
session's earlier `requires-python` fix addressed.

**Fixed:** resolved the `.env` path from `config.py`'s own file location
(`Path(__file__).resolve().parent.parent.parent / ".env"`) instead of a bare relative
string, so it is correct regardless of the process's cwd at construction time.

**Verified for real, twice:** first by hand — writing a real temporary `.env` at the
repo root and running a one-line script from both `backend/` and the repo root, before
and after the fix, confirming the exact failure and the fix — then by a proper test file
(`test_config.py`, which had never existed for this module before): two tests spawn
real subprocesses from each directory with a real temporary `.env` and assert the
loaded value, plus a structural check that the resolved path's parent really is the
repo root where `.env.example` actually lives.

**Result:** `pytest tests/test_config.py -v` — 3/3 passed. Full backend suite:
**207 passed, 4 skipped**. Eighth real wiring/configuration-gap bug this session's
audits have caught.

---

## 2026-09-19 — Bug found and fixed: `NEBIUS_SANDBOX_IMAGE` was declared but never read

**Audit method this time:** rather than tracing one specific requirement end-to-end (the
approach that found the prior eight), swept every field in `config.py` with `grep -rn
"settings\.<field>"` across the whole app to find which settings are declared,
documented in `.env.example`, and yet never actually referenced anywhere outside
`config.py` itself. Two came back with zero hits: `nebius_sandbox_image` and
`nebius_project_id`.

**`nebius_sandbox_image` — a real bug, fixed.** `planner.py`'s `_base_image_for()` had
`"python:3.11-slim"` hardcoded as its fallback default, completely bypassing the
configurable setting a user could set in `.env` and see zero effect from, with no error.
Fixed by threading a `default_image` parameter from `config.py` through
`PipelineDeps.default_sandbox_image` (analogous to how `tavily_client` and `cost_guard`
are already injected) into `planner.build_plan()`, replacing the hardcoded literal.
4 new tests prove it: two directly on `build_plan()` (the no-hint case and the
range-specifier-fallback case both now respect a custom `default_image`, not just the
one hardcoded string that happened to match the test's expectations before), and one
orchestrator-level integration test confirming the configured image reaches both the
certificate's `build_plan` and the actual sandbox call.

**`nebius_project_id` — audited, not a bug, left alone.** This setting is intended for
Nebius Serverless Jobs (`metadata.parentId` in `batch/runner.py`'s REST payload — see
the earlier `runner.py` entry), a feature that is real, tested in isolation, but not yet
wired into any router endpoint at all. An unread setting for a feature that
legitimately doesn't have a caller yet is a documented gap, not a silent wiring defect
like the other nine — wiring it in now, with nothing to consume it, would just be
speculative code. Recorded here so it isn't mistaken for an oversight later: when
`batch/runner.py` gets an actual router/CLI entrypoint, `NebiusJobsClient` construction
should read `settings.nebius_project_id`, not a hardcoded or missing value.

**Result:** `pytest tests/test_planner.py tests/test_orchestrator.py -v` — 29/29
passed. Full backend suite: **210 passed, 4 skipped**. Ninth real bug this session's
self-audits have caught — this time found by a systematic settings sweep rather than
tracing one directive requirement at a time, which suggests the sweep method itself is
worth repeating on any future settings additions.

---

## 2026-09-19 — Bug found and fixed: the persisted DB volume mounted the wrong path

**Audit method:** cross-checked `docker-compose.yml`'s declared persistence
(`backend-data:/app/data`) against where the app would actually write, rather than
trusting that a volume declaration existing means it's doing anything.

**Bug:** `DATABASE_URL` defaulted to `sqlite:///./rerun.db` — a relative path resolving,
inside the container, to `/app/rerun.db` (the container's cwd is always `/app`, fixed by
`Dockerfile`'s `WORKDIR`). The `backend-data` volume is mounted at `/app/data` — a
**different directory that nothing ever wrote to at all**. The volume declaration looked
complete and correct in the compose file; in reality every run, certificate, and repair
attempt would have lived in the container's ephemeral writable layer and been **silently
discarded** the instant the container was recreated (`docker compose down && up`, or any
redeploy) — exactly the kind of infrastructure claim ("this is persisted") that looks
right at a glance and is wrong in a way no application-level test could ever catch,
since the mismatch lives entirely in the relationship between two separate files
(`config.py` and `docker-compose.yml`) that no single test exercises together.

**Fixed:** changed the default to `sqlite:///./data/rerun.db` (in both `config.py` and
`.env.example`, kept explicitly in sync via a comment in each), which resolves to
`/app/data/rerun.db` inside the container — landing exactly inside the already-declared
volume mount. Also fixed the other half of the same problem: SQLite itself never creates
a missing parent directory, so a fresh volume (or fresh local checkout, `data/` doesn't
exist yet) would fail outright on first write. Added `db.py::_ensure_sqlite_dir_exists`
(using `sqlalchemy.engine.make_url()` to correctly parse the database path out of the
URL — rather than hand-rolling `urlparse` logic and getting sqlite's eccentric
3-slash-relative-vs-4-slash-absolute slash conventions subtly wrong, verified directly
against the installed SQLAlchemy source per §2.4) that creates the parent directory
before the engine is constructed.

**Result:** `pytest tests/test_db.py -v` — 4/4 passed, including a real connection test
(`test_make_engine_creates_missing_parent_directory`: creates a table, inserts a row,
reads it back) proving the auto-created directory actually produces a usable database,
not just that `mkdir` didn't raise. Full backend suite: **214 passed, 4 skipped**.
Tenth real bug this session's audits have caught.

---

## 2026-09-19 — Bug found and fixed: `git` was never installed in the backend Docker image

**How this was found:** while live-verifying the DB-volume fix above (rebuild, `docker
compose up`, create a real run against the running container), `POST /runs` returned a
raw 500. This was not found by inspection or by a unit test — every existing test
either runs on the host machine (where `git` is genuinely installed) or monkeypatches
around the credential boundary; nothing in the suite ever exercised `intake.py`'s real
`subprocess.run(["git", ...])` calls *from inside the actual container image*.

**Bug:** `backend/Dockerfile` is `FROM python:3.11-slim` and never installs `git`.
`intake.py` shells out to the real `git` binary for every clone/`ls-remote`/`rev-parse`
call — the very first step of the entire pipeline. The container log showed the exact
failure: `FileNotFoundError: [Errno 2] No such file or directory: 'git'` from
`intake.validate_repo_accessible`. This means the deployed Docker image, as it existed
before this fix, could not complete **S1 intake at all** — not a downstream feature, the
literal first thing a user does. `docker compose build` and `docker compose up` had both
already succeeded earlier this session (§"docker-compose reproducibility gaps" entry)
precisely because neither of those steps ever exercises the code path that needs `git`
at runtime — a clean build and a healthy `/healthz` say nothing about whether the app's
actual core feature works.

**Fixed:** added `apt-get install -y --no-install-recommends git` (with the standard
`apt-get update`/`rm -rf /var/lib/apt/lists/*` pairing to avoid leaving a stale package
index bloating the image) to `backend/Dockerfile`, before the Python dependency install
step.

**Verified live, fully, after a transient first-attempt network blip:** the first
rebuild failed with `Unable to connect to deb.debian.org`; a direct `docker run
python:3.11-slim apt-get update` immediately afterward succeeded, showing it was a
momentary DNS/network hiccup rather than a persistent restriction, and the rebuild
succeeded on retry. Then, against the real rebuilt container:

1. `POST /runs` with the exact same repo that previously 500'd
   (`octocat/Hello-World`) now correctly clones and returns the honest
   `"no Python code found in repo"` rejection (that repo genuinely isn't Python — the
   *bug* was the 500 before ever reaching that check, not this rejection itself).
2. `POST /runs` against a real Python repo (`pypa/sampleproject`) succeeds fully,
   returning a real commit SHA.
3. `docker compose exec backend ls -la /app/data/` shows `rerun.db` actually living
   inside the mounted volume path — confirming the companion DB-path fix above lands
   correctly together with this one.
4. `docker compose up -d --force-recreate backend` (simulating a redeploy) followed by
   re-fetching the same run by id returns the identical record — proving the data
   survived container recreation, the exact failure mode the DB-path bug would have
   caused silently.

Torn down afterward (`docker compose down -v`) — no containers or volumes left running.

---

## 2026-09-19 — Bug found and fixed: docker-compose.yml referenced Dockerfiles that didn't exist

**Bug:** `docker-compose.yml` was written early (Phase 0 scaffolding, before either
service had real code) with `build: context: ./backend` / `./frontend`, but no
`Dockerfile` was ever added to either directory — `docker compose build` would have
failed immediately for anyone actually trying to run the "reproducible setup" §4.1
explicitly calls for ("a reproducibility tool with an irreproducible README is an own
goal"). Caught by actually trying to build it, not by re-reading the compose file.

**Fixed:** added `backend/Dockerfile` (plain `python:3.11-slim`, `pip install .`,
`uvicorn`) and `frontend/Dockerfile` (multi-stage: `node:20-alpine` builds the real
production Vite bundle, then `nginx:1.27-alpine` serves it). Also fixed a second latent
bug this surfaced: the frontend's `/api` calls only work through Vite's *dev-server*
proxy (`vite.config.ts`'s `server.proxy`) — a production static build served by nginx
has no such proxy, so every API call would have 404'd in the exact deployment path §12
requires ("Working demo URL"). Added `frontend/nginx.conf` with a `location /api/ {
proxy_pass http://backend:8000/; }` block that mirrors the dev-server proxy's behavior,
so `src/api.ts`'s hardcoded `/api` base path is correct in both dev and
docker-compose/production without needing environment-specific base URLs.

Also removed the backend's `./backend:/app` bind mount (it would have shadowed the
image's installed package with the host source tree for no benefit, since the compose
setup targets "run this the way a judge would," not live-reload development) and made
`.env` optional in `env_file` (`required: false`) so `docker compose build`/`up` works
out of the box before a real `.env` exists, matching the README's copy-`.env.example`-first
instructions rather than requiring it just to validate the compose file.

**Verified for real, not just written:** Docker Desktop was not running in this
environment; started it, waited for the daemon, then ran a real `docker compose build`
— both images built successfully (`rerun_nvidia-backend`, `rerun_nvidia-frontend`).
Then ran `docker compose up -d` and confirmed with real `curl` calls: the backend
answers `/healthz` directly on :8000, **and** the nginx-served frontend on :5173
correctly proxies `/api/healthz` through to the backend container — proving the
`nginx.conf` reverse-proxy fix actually works end-to-end, not just parses. Torn down
with `docker compose down` afterward, no containers left running.

---

## 2026-09-19 — Bug found and fixed: the README's own setup command failed on this machine

**Bug:** While verifying §13 definition-of-done item 2 ("a fresh git clone on a clean
machine, following only the README, produces a running local instance") by literally
doing it — a real `git clone` into a scratch directory, then following the README's
`python -m venv .venv` / `pip install -e ".[dev]"` steps verbatim — the install failed
immediately: `ERROR: Package 'rerun-backend' requires a different Python: 3.14.4 not in
'<3.13,>=3.11'`. This machine only has Python 3.14 installed. The bug had been latent
all session because this session's own working `.venv` was never actually set up via
the documented `pip install -e ".[dev]"` command — every dependency was installed
individually and ad hoc (`pip install pytest`, `pip install fastapi uvicorn ...`, etc.),
which never triggers setuptools' `requires-python` enforcement the way installing the
project itself does. In other words: the tests were real and green all session, but the
literal onboarding path a judge would actually follow was never itself exercised until
now — exactly the gap §13's "following only the README" phrasing exists to catch.

**Fixed:** relaxed `backend/pyproject.toml`'s `requires-python` from `>=3.11,<3.13` to
`>=3.11` (no upper bound). Nothing in the codebase uses syntax exclusive to 3.11/3.12 —
it has been running correctly on 3.14 all session — so the upper bound was serving no
real purpose beyond blocking exactly the kind of machine this one is. 3.11 remains the
floor and the pinned Docker image version (`backend/Dockerfile` -> `python:3.11-slim`),
matching §4.1's stated target for where the app is actually deployed; the relaxed
ceiling only affects local developer machines with a newer interpreter already
installed.

**Re-verified after the fix, from a genuinely fresh clone + fresh venv (not the
session's pre-existing one):** `git clone` into a new scratch directory, real
`python -m venv .venv`, real `pip install -e ".[dev]"`, real `pytest -q` ->
**172 passed, 4 skipped** — the exact command a judge running only the README would
type. This is the strongest form of verification this session performed for §13 item 2,
short of an actual second machine.

---
