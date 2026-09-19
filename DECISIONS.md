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
