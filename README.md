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
- 🟡 `batch/runner.py`: the Nebius Serverless Jobs REST client and the pure
  `batch_results.json` aggregation logic are real and tested, but — unlike everything
  else — this is **not** verified against an installed SDK or a live account (no ready
  Python bindings exist for this API yet); the job container's actual entrypoint script
  and the full submit-and-poll loop are not yet built. See `DECISIONS.md` for exactly
  what's solid vs. still speculative here.
- 🚧 True SSE live-streaming for S2 (currently a single blocking `/execute` call, so S2
  shows a "Running…" state and then renders the timeline retrospectively once done —
  an honest simplification, not a fake stream) and hosting on Nebius Serverless
  Endpoints are not yet built.

Backend test suite: **182 passed, 4 skipped** (`cd backend && pytest -v`) — reconfirmed
from a genuinely fresh clone, not just the working session directory. 3 skips are the
real Nebius Sandboxes integration test, honestly gated on `NEBIUS_API_KEY`; 1 is a
network-dependent corpus-freshness check (`RERUN_VERIFY_CORPUS_NETWORK=1` to run it —
confirmed passing against all 20 real repos as of 2026-09-19).

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

## License

Apache-2.0 — see [LICENSE](LICENSE).
