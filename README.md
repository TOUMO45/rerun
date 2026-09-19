# RERUN

RERUN takes a published paper's code repository, rebuilds its environment from scratch
inside an isolated **Nebius Token Factory Sandbox**, actually runs it, issues an
evidence-backed reproducibility verdict, and — when it can — proposes a minimal patch
that is verified by a deterministic **tamper gate** before it is ever accepted. The
tamper gate exists so that a reported "fix" can never be the model quietly making the
code do less (deleting the eval call, stubbing a model call, shrinking the dataset,
swallowing the error) to force a pass.

**Scope, stated honestly:** RERUN verifies that the artifact **executes** (`SMOKE`
level: exit code 0 + non-trivial output). It does **not** verify that the paper's
numerical results are reproduced.

Full specification: [RERUN_BUILD_DIRECTIVE.md](RERUN_BUILD_DIRECTIVE.md). Build decisions
and their rationale: [DECISIONS.md](DECISIONS.md). Batch Lab corpus selection and
limitations: [METHODOLOGY.md](METHODOLOGY.md).

## Status

This project is being built in phases (see the directive, §11). Current state:

- ✅ Phase 1 core — `classifier.py`: pure, deterministic failure-taxonomy classifier
  (§5.2). 26/26 tests green, every taxonomy code has a positive + negative-control test.
- ✅ Phase 2 core — `tamper_gate.py`: the differentiator (§5.3). 22/22 tests green,
  every rejection rule has a negative control, including the required hand-crafted
  "delete the eval call" rejection test.
- ✅ `passport.py` + `scripts/verify_passport.py` (§6.3), `cost_guard.py` (§9),
  `intake.py` (repo clone + dependency/entrypoint parsing) — all green, no credentials
  required.
- 🚧 `sandbox.py` is implemented against the real, source-verified Nebius Token Factory
  Sandboxes SDK (`contree-sdk`), but its live gate — `pytest tests/test_sandbox_smoke.py`,
  3 real sandboxes created and destroyed — is honestly **skipped**, not faked, until
  `NEBIUS_API_KEY` is supplied. This is the single remaining blocker on Phase 0.
- ✅ FastAPI orchestrator skeleton: `POST /runs` performs real S1 intake (clone +
  parse + Python-code detection) against any real git repo today; `GET /batch/results`
  fails loudly (502) instead of rendering a fake zero when `batch_results.json` is
  missing; `GET /healthz` reports real Nebius/Tavily configuration state.
- ✅ `model_client.py` (shared, testable Nebius/Nemotron chat-completion wrapper),
  `recon.py` (§6.1 calibrated abstention — a hallucinated or low-confidence entrypoint
  is rejected into `INDETERMINATE`, enforced in code, not just prompted for),
  `planner.py` (mostly-deterministic build-plan construction, model used only to
  enrich apt-package inference). All tested against fake injected model clients — no
  live Nemotron call has been made yet (needs `NEBIUS_API_KEY`).
- ✅ `repairer.py`: proposes a minimal diff via Nemotron Super but never decides
  whether it's acceptable — proven end-to-end by a test that feeds a proposal
  violating the tamper gate's rules straight through the real `check_patch()` and
  confirms it's rejected, not just described in a prompt.
- ✅ `adjudicator.py`: Nemotron Ultra writes certificate prose but is structurally
  barred from ever upgrading a verdict ("may only downgrade") — a fake client that
  dishonestly tries to turn a `BLOCKED` run into `RUNS_CLEAN` is proven to be clamped
  back. Falls back to honest templated prose whenever no model client is available.
  This completes real, tested integration code for all three Nemotron-routed roles
  (Nano/recon, Super/planning+repair, Ultra/adjudication) required by §12 — none has
  hit the live API yet, but all are ready the moment `NEBIUS_API_KEY` exists.
- ✅ `orchestrator.py`: the full pipeline (recon → §6.1 abstention → planner → sandbox
  → classifier → bounded repair loop against the real tamper gate → adjudicator →
  passport) wired together and proven end-to-end with injected fakes for the model/
  sandbox layer, while `classifier.py` and `tamper_gate.py` run for real, unmocked.
  Directly proves §14's red-team question: a scripted "delete the eval call" repair
  proposal is rejected by the real gate, a legitimate follow-up passes, and the file on
  disk is checked to confirm the bad patch was genuinely never applied.
- ✅ `POST /runs/{id}/execute` + `GET /runs/{id}/certificate`: calls the real
  orchestrator with real credentials from settings and persists the result
  (`Run`/`RepairAttempt`/`Certificate` rows, including the real passport hash). Returns
  a clear 503 — never a crash or a fake result — when `NEBIUS_API_KEY` is absent.
- ✅ Frontend (React + Vite + Tailwind): all 4 screens (S1 Intake, S2 Run Timeline, S3
  Certificate, S4 Batch Lab) built and wired to the real API — verified live in a
  browser against a running backend, not just code review. The tamper-gate REJECT card
  is the one deliberately loud, animated visual moment, per §8 S2. Run it with
  `cd frontend && npm install && npm run dev` (proxies `/api` to `localhost:8000`).
- ✅ Batch Lab corpus ([corpus.yaml](backend/app/batch/corpus.yaml), 20 repos): every
  entry verified live (`git ls-remote` + a GitHub API file listing) at assembly time —
  see [METHODOLOGY.md](METHODOLOGY.md) for selection criteria and known limitations.
  The corpus has not been *executed* yet (needs `NEBIUS_API_KEY` + Nebius Serverless
  Jobs) — `batch/runner.py` is the one piece of §7 not yet built.
- ✅ `docker-compose.yml` + real `Dockerfile`s for both services, actually built and
  run: `docker compose build` succeeds, and `docker compose up` proves the nginx-served
  frontend correctly proxies `/api/*` to the backend container (verified with `curl`
  against a real running stack, then torn down).
- ✅ Fresh-clone verified: a real `git clone` into a scratch directory, followed by the
  README's exact setup steps, produces a passing test suite. This caught and fixed a
  real bug (`requires-python` blocked this exact machine's Python 3.14) that had been
  latent all session because the working dev environment was never itself built via the
  documented command.
- ✅ `batch/run_single_repo.py`: the actual job-container entrypoint (clone at a pinned
  commit via the new `intake.clone_repo_at_commit`, run the pipeline, print a JSON
  verdict) — real and tested, closing the gap `runner.py`'s docstring had explicitly
  flagged as not built. Building this surfaced and fixed an unbounded disk-space leak:
  `routers/runs.py` created a temp git clone on *every* `POST /runs` and every
  `POST /runs/{id}/execute` and never once deleted it — confirmed with 317 leaked
  directories found in this session's own system temp folder from testing alone.
- 🟡 `batch/runner.py`: the Nebius Serverless Jobs REST client and the pure
  `batch_results.json` aggregation logic are real and tested, but — unlike everything
  else — this is **not** verified against an installed SDK or a live account (no ready
  Python bindings exist for this API yet); the full submit-and-poll loop tying it to
  `run_single_repo.py` is not yet built. See `DECISIONS.md` for exactly what's solid vs.
  still speculative here. Once it does produce a real `batch_results.json`, it's picked
  up correctly: `docker-compose.yml` bind-mounts the repo root's `batch_results.json`
  into the backend container (verified live — see the bug below), a gap that would
  otherwise have made S4 unreachable in production regardless of how solid the runner
  itself is. One more real limitation, found and documented rather than fixed: §9's
  daily cost ceiling is a process-wide singleton, correct for the web app but each batch
  corpus repo runs in its own separate Nebius Job container — there's no coordination
  across them, so a full batch run isn't actually capped in aggregate the way a single
  web request is. See `DECISIONS.md` for why this needs shared infrastructure to fix
  properly rather than a code change.
- **S4's "click a row → the frozen S3 certificate" (§8) isn't built**, found by
  re-reading the S4 spec line by line. `RepoTable`'s row click only expands an inline
  `repo_url`/`duration` detail today. Traced why this isn't a simple frontend add:
  `run_single_repo.py`'s own job output only carries summary fields (verdict, taxonomy
  code, attempts, duration) — no build plan, diffs, full log, or passport hash — so
  there's nothing for a "frozen certificate" view to render yet even if built. This is
  three layers deep (the batch job's output schema, `aggregate_batch_results()` passing
  it through, and a new frontend rendering path) and entangled with `batch/runner.py`'s
  already-documented incomplete state above; building the frontend piece alone, ahead of
  deciding the real output schema, risks locking in a shape that has to change again
  once the batch runner is finished. Scoped and ready to pick up — see `DECISIONS.md`.
- **Two real npm CVEs, found while re-verifying the README's fresh-clone setup**:
  `esbuild` (dev-server-only — doesn't affect the deployed production build) and
  `react-router` (a real runtime dependency; an open-redirect and an SSR-hydration CVE).
  Checked exploitability for this specific app rather than assuming the worst: RERUN has
  no SSR at all, and every navigation target is a hardcoded route or a backend-issued
  UUID, never user-controlled input — so neither CVE has real attack surface here. Not
  fixed: confirmed via `npm view` that no non-breaking patch exists (the latest 6.x is
  still vulnerable); only a major-version jump to `react-router-dom@7` fixes it, and a
  core-routing-library major upgrade this late, without dedicated regression testing
  across all four screens, is judged a worse trade than the negligible actual risk.
- Two more gaps in the same cost guard, found the same way (adversarial testing, not
  code reading) and documented rather than fixed: (1) a genuine TOCTOU race — reproduced
  live with two real threads — where two *different* runs executing concurrently can
  each pass the daily-ceiling check before either records its spend, together exceeding
  the ceiling; closing it properly would need a pre-flight cost quote the sandbox API
  doesn't provide, or a lock that would serialize all concurrent sandbox execution
  process-wide. (2) the daily USD ceiling **never actually covered model/inference
  spend** — only sandbox cost is ever recorded against it; every Nemotron call is bounded
  by a per-call token-count ceiling, never converted to USD or accumulated toward the
  daily total, because no verified per-token pricing exists anywhere in this codebase to
  do that conversion honestly. `cost_guard.py`'s own module docstring previously claimed
  otherwise — corrected.
- 🚧 **`DEMO_MODE`'s recorded fixtures (§9) were never actually built**, found by
  re-reading the directive fresh rather than by testing existing code. `demo_mode` is a
  real config flag (default `False`, surfaced in `/healthz`), but nothing anywhere reads
  it to change behavior — no fixture file, no fixture directory, no conditional branch.
  The flag's existence could look like this requirement is satisfied; it isn't. Not
  built now rather than faked: a real implementation needs actual recorded output from a
  genuine clean run and a genuine repair-then-pass run, which needs live Nebius
  credentials this session doesn't have — fabricating placeholder fixture content to
  stand in for "the guaranteed demo fallback" would risk exactly the "never fake a
  result" violation §0 forbids. See `DECISIONS.md`.
- ✅ `GET /runs/{id}/stream`: true SSE live-streaming for S2, per §4's named endpoint,
  and the frontend actually consumes it. Runs the real pipeline in a background thread
  and streams each log line the instant `orchestrator.run_pipeline` produces it via an
  `on_event` callback threaded through the whole pipeline; replays the persisted log
  instead of re-executing if the run already finished. S2 (`RunTimeline.tsx`) opens this
  stream with the native `EventSource` API on "Start reproduction run" and renders each
  line live in a scrollable panel, closing the connection itself on both completion and
  error rather than trusting `EventSource`'s default auto-reconnect — which, for this
  particular endpoint, would otherwise silently re-execute the whole pipeline on every
  dropped connection. The previous single blocking `/execute` call still exists and
  still works (used by the batch runner, curl, and tests). Nebius Serverless Endpoints
  hosting is not yet built.
- ✅ S2's "Live sandbox badge (id, elapsed time, wall-clock remaining)" (§8) — found
  missing by re-reading the UI spec line by line, then built rather than just
  documented, since the underlying data (the real `contree_sdk` image's `.uuid`, and the
  configured wall-clock ceiling) is real and needed no fabrication. Wall-clock remaining
  is fully live, computed client-side from the existing elapsed ticker; the sandbox id
  appears honestly once a real step has actually logged it, not a placeholder pretending
  to be live from second one — that would need a larger redesign (a progress callback
  threaded through the currently-blocking `sandbox.py` call) judged out of scope for
  what this gap needed. Verified live against a real browser with realistic delays, not
  just unit-tested.

Backend test suite: **244 passed, 4 skipped** (`cd backend && pytest -v`) — reconfirmed
from a genuinely fresh clone, not just the working session directory. 3 skips are the
real Nebius Sandboxes integration test, honestly gated on `NEBIUS_API_KEY`; 1 is a
network-dependent corpus-freshness check (`RERUN_VERIFY_CORPUS_NETWORK=1` to run it —
confirmed passing against all 20 real repos as of 2026-09-19).

Self-audit passes found and fixed **twenty-three** real bugs/gaps this session (full detail in
`DECISIONS.md`). Three are worth calling out specifically because unit tests
structurally could never have caught them — only running the real, deployed Docker image
did:

- **S4's data file could never reach the deployed container.** `batch_results.json` is
  meant to live at the repo root, but the backend's Docker build context is `./backend`
  only — no `COPY` in the Dockerfile could ever have reached it, and no volume mount
  existed either. Fixed with a bind mount in `docker-compose.yml`; verified live,
  including that a *missing* `batch_results.json` (true today — the batch corpus hasn't
  been run yet) still fails loudly with a 502 rather than crashing `docker compose up`
  or silently mounting something broken.
- **The persisted database volume mounted the wrong path.** `DATABASE_URL` defaulted to
  a location outside `docker-compose.yml`'s declared `backend-data` volume entirely —
  every run/certificate would have been silently discarded on every container
  recreation, despite the volume declaration looking complete and correct.
- **`git` was never installed in the backend Docker image.** `python:3.11-slim` doesn't
  ship it, and `intake.py` shells out to the real binary for every clone — meaning **S1
  intake, the literal first thing a user does, was completely broken** in the deployed
  container, despite a clean `docker compose build` and a healthy `/healthz`. Found only
  by creating a real run against the real running container and reading the traceback.

All three are now fixed and verified live: rebuilt the image, created a real run against
a real Python repo, confirmed the database file actually lives in the mounted volume,
and confirmed the run survives a full `--force-recreate` (simulated redeploy).

One more is worth calling out on its own: **a double-click, browser back-then-resubmit,
or a page reload mid-run could crash or silently corrupt a run's final state.**
`Certificate.run_id` is a one-to-one DB column; nothing stopped `POST /execute` (or a
second `GET /stream`) from being called a second time against the same run, and doing so
crashed with an unhandled `sqlite3.IntegrityError` — reproduced with no concurrency at
all, just two sequential calls. Fixed with an `EXECUTING` stage marker committed before
any real work starts, refusing a second execution with a clean `409` instead; the
frontend now shows "already in progress, checking back automatically" instead of
re-exposing the start button after a reload.

And one in the tamper gate itself (§5.3, the project's differentiator): **an unrelated,
completely benign patch could get falsely rejected as a tampering attempt.**
`_reachable_matching_calls`'s function-lookup table was a flat, name-keyed dict built
without regard for lexical scope — a never-called helper function that happened to
define a *locally-nested* function sharing a name with the real, actually-called
function corrupted resolution of the real call, making an entirely unrelated addition
look exactly like a deleted eval call. Found by stress-testing the gate with novel
adversarial inputs, not by re-running the existing suite. This one cuts the wrong way for
this project specifically: a false rejection burns a bounded repair attempt (§5.4) on a
patch that was actually fine, which can push a run to `BLOCKED` when it should have
recovered — directly against the Recovery Rate metric the pitch is built on. Fixed by
excluding locally-nested functions from the lookup table (module-level functions and
class methods are still resolved by name, unchanged); verified both that the fix closes
the false positive and that the actual attack this mechanism defends against (moving a
real eval call into a same-named function defined *after* the original, so the later
definition shadows it) is still correctly rejected. The same audit pass found the exact
same false-positive shape one rule over, in `STUBBED_MODEL_CALL`: it scanned the *whole*
patched file for any trivial stub matching a model-call name, so a file that already had
a `pass`-bodied abstract base-class placeholder (an entirely ordinary override pattern)
would fail *any* unrelated patch touching that file. Fixed the same way `DELETED_EVAL_CALL`
already works — comparing trivial-stub *counts* before and after, flagging only a genuine
increase — and verified a real attack (stubbing the actual implementation) is still
caught even when an untouched, already-trivial same-named stub exists elsewhere.

One more, in `sandbox.py`: **the configured wall-clock ceiling was per-step, not
per-attempt.** Every install command and the final execute command each got the full,
unchanged `wall_clock_seconds` as their own `timeout=`, so a configured 60s ceiling could
let a multi-step build consume 180+ seconds in aggregate — scaling with however many
install commands a given repo's build plan needs, contradicting §4's "hard limits (wall
clock...)" and undermining §9's cost predictability. Fixed by tracking one shared
deadline across all steps, verified with a clock-controlled fake proving the remaining
budget correctly shrinks as real time elapses and a step is refused outright once the
deadline is exhausted, rather than silently starting with a fresh budget it was never
entitled to.

One more worth calling out: **a gate-approved patch that turned out to be inapplicable
crashed the entire pipeline.** `tamper_gate.py`'s own diff reconstruction never
cross-checks a diff's claimed context lines against the real file — it just trusts the
diff's structure. A repair model proposing a diff against a slightly stale or
misremembered view of the file (an ordinary LLM failure mode, not a contrived one) could
therefore pass the gate cleanly, only for the real `git apply` step to correctly refuse
it — and that refusal was never caught anywhere, crashing the whole run with an unhandled
exception instead of the honest `BLOCKED` verdict §0 requires. Fixed by catching it at
the one call site and folding it into the bounded loop's existing "this attempt didn't
work, try again" path; verified live that the crash reproduces beforehand, disappears
after, the file on disk is confirmed untouched by the failed apply, and the run still
reaches `BLOCKED` with an honest per-attempt record of what happened.

Other fixes from this session's audits: both halves of §9's cost guard (daily USD
ceiling, per-attempt token ceiling) were implemented and unit-tested in isolation but
never called from the orchestrator; **Tavily was never called anywhere at all** despite
being a named prize track; the router built a **fresh `CostGuard` on every request**,
silently resetting the "daily" budget each time; `.env` loading **silently loaded
nothing** depending on launch directory; `NEBIUS_SANDBOX_IMAGE` was declared but never
read; a temp git clone was leaked on every `POST /runs` and `/execute` call with no
cleanup, confirmed with 317 leaked directories in this session's own temp folder; a
late-binding function-default bug made a test silently skip its monkeypatch and make a
real network call; and, most recently, the new SSE stream route's background worker
thread bypassed the test suite's DB-isolation fixture entirely by calling `SessionLocal`
directly instead of through FastAPI's request-scoped override. A reminder that isolated
unit tests don't catch defects in the wiring *between* components, in instance
lifecycle, or in what the actual deployed artifact does versus what its source code
claims — only running the real thing does.

## Repo layout

See §4.2 of the build directive. Backend is FastAPI + SQLite (Python 3.11), frontend is
React + Vite + Tailwind, tests are `pytest`.

## Running the backend tests

```bash
cd backend
python -m venv .venv
./.venv/Scripts/activate   # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -e ".[dev]"
pytest -v
```

## Running the full stack via Docker

```bash
cp .env.example .env   # fill in real credentials for a live run; works unfilled too
docker compose build
docker compose up
```

Backend on `http://localhost:8000`, frontend on `http://localhost:5173` (nginx,
proxying `/api/*` to the backend container). Both images are verified to build and run
— see `DECISIONS.md` for the exact `curl` checks performed.

Only `classifier.py` and `tamper_gate.py` (plus their tests) require no external
credentials — they are pure, network-free Python. Everything touching the Nebius Token
Factory (sandboxes, Nemotron inference) or Tavily needs `.env` populated from
`.env.example` first.

## NVIDIA / Nebius usage (hackathon requirement)

- **Nebius Token Factory** — inference for Nemotron 3 Nano (recon), Super (planning +
  repair), Ultra (adjudication); and **Sandboxes** for isolated, destroyed-after-use
  execution of target repos.
- **Nebius Serverless Jobs** — runs the 20-repo Batch Lab corpus in parallel.
- **Nebius Serverless Endpoints** — hosts the deployed app.
- **Tavily** — runtime-called for dependency/environment context injected into the
  repair prompt and cited in the certificate.

## Before submitting

See [`SUBMISSION_CHECKLIST.md`](SUBMISSION_CHECKLIST.md) — §12's full hackathon
compliance checklist with real, current evidence per item (what's done, what's
code-ready but needs live credentials, and what's a genuinely blocking human step like
deploying, recording the demo video, and pushing to a public repo).

## License

Apache-2.0 — see [LICENSE](LICENSE).
