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
and their rationale: [DECISIONS.md](DECISIONS.md).

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
- 🚧 True SSE live-streaming for S2 (currently a single blocking `/execute` call, so S2
  shows a "Running…" state and then renders the timeline retrospectively once done —
  an honest simplification, not a fake stream), the batch lab corpus, and hosting on
  Nebius Serverless Endpoints are not yet built — see `DECISIONS.md` for the full trail.

Backend test suite: **164 passed, 3 skipped** (`cd backend && pytest -v`). The 3 skips
are the real Nebius Sandboxes integration test, honestly gated on `NEBIUS_API_KEY`.
Every piece of the §4 architecture diagram now has real, tested code reachable from an
actual HTTP endpoint — the only remaining gap before a live end-to-end run is a real
Nebius API key.

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
