# Hackathon submission checklist (§12)

Tracks `RERUN_BUILD_DIRECTIVE.md` §12 with evidence per item (§13 item 7). **Rewritten from the actual state on 2026-10-11** (the first version, `f5b2d6e`, was
written before the repository was public and before any live run, and had not been updated since).

Legend: ✅ done, with evidence · ⏳ ready, waiting on one named step · 👤 the owner's action on an external platform, not verifiable from the repository ·
❌ not done.

## §12 items

- [x] ✅ **Runs on Nebius Token Factory (Sandboxes + inference).** Every live record stores `config.sandbox_backend = token_factory`, its sandbox operations
      (`operations[]`) and its model calls with token usage (`model_calls`, `cost_guard.model_usage`); README "Where Token Factory is used". The sealed harness
      `harness-v1.10.0` was sealed live on a GitHub Actions runner (`seal_verification.json`, run 37958950100).
- [x] ✅ **Uses NVIDIA open models: Nemotron 3 Nano, Super and Ultra.** README "Where Nemotron is used" lists the model names as stored in the records
      (`config.models`): Nano for recon, Super for planner and repairer, Ultra for adjudicator.
- [ ] 👤 **Category: Coding and Agentic Engineering.** A form field (the README's "Track" line says the same).
- [x] ✅ **Project description.** `docs/submission/description.md` and `docs/submission/devpost_answers.md`, generated from `reports/v1.9/figures.json` by
      `reports/texts/render.py` (the word limit and every number's tag are guarded by tests). ⏳ They are regenerated after the live run below.
- [ ] ⏳ **Working demo URL (hosted app).** Both images are ready and proven by the keyless workflow `.github/workflows/demo-check.yml` (no secret; it builds each
      image at the pushed commit, checks that it holds no `.env` or key, that it refuses to start with a key without printing the value, and probes the running app):
      `deploy/hf-space/` (job `space-image`) and `deploy/render/` (job `render-image`, brought to the Space's standard on 2026-10-11). The Render URL
      <https://rerun-demo.onrender.com> answers, keyless, but serves the commit of 2026-10-06. **Owner:** choose A (create the Space, `deploy/hf-space/README.md`)
      or B (redeploy Render, `deploy/render/README.md`), then put the URL in the README and the form.
- [ ] 👤 **Demo video: public YouTube, at most three minutes, audio covers Token Factory and NVIDIA models.** Not recorded. The shot list
      `docs/submission/video_shot_list.md` names Nebius Token Factory in the sandbox shot and the Nemotron models in the repair shot; it uses `python demo.py`.
- [x] ✅ **Public repository, Apache-2.0.** <https://github.com/TOUMO45/rerun>: GitHub's API reports it public with license `Apache-2.0` detected from the
      root `LICENSE` (2026-10-11), which is what the repository page shows; README "License".
- [x] ✅ **README with setup instructions and run guidance.** README "Run it in one command" (`python demo.py`, keyless) is run from a fresh clone on Linux and on
      Windows by the keyless workflow at every push to `main`; README "Run it live" for a live run. The Docker Compose demo was removed on 2026-10-11 because no
      workflow ever tested it.
- [x] ✅ **README highlights NVIDIA model usage and the Nebius services used.** README "Where Nemotron is used", "Where Token Factory is used" (Sandboxes, the model
      endpoints, the price list, the seal). Serverless Jobs and Serverless Endpoints are **not used**, and the README does not claim them; the hosted demo runs on a
      Hugging Face Space or Render.
- [ ] 👤 **Feedback submitted on Token Factory / AI Cloud / NVIDIA tools.** On the hackathon platform.
- [x] ✅ **Not built from pre-existing code.** `DECISIONS.md`'s first entry ("Repo bootstrap") and the git history from an empty repository.
- [ ] 👤 **Builders & Brews city, if attended.** Fill in or mark not applicable.
- [x] ✅ **Tavily called at runtime and cited in the certificate.** Called before every repair attempt; the references offered (`consulted`) and the sources the model
      cited (`cited`) are stored on the attempt and in the certificate; README "Where Tavily is used" gives the counts per gate and the limit (whether a citation shaped a
      decision is not measured, D-21 open). ⏳ The flag mode's only live run so far had no Tavily context (its search failed on a malformed secret); the pending live
      run below is pre-registered with Tavily on.
- [ ] 👤 **Submitted before Oct 30, 2026, 10:00am PDT** (internal target Oct 28).

## The project's own gate (state on 2026-10-11)

- [ ] ⏳ **The one pre-registered live run** (`reports/v1.10/review_live/PLAN.md`, Amendment 1 committed before the run in `6fba7f5`): M-FAC at `harness-v1.10.0`,
      flag mode, Tavily on, cap $10.00 API-reported, one run. Preconditions hold (`launch.py --check`, 2026-10-11). **Waiting on the owner's go.** Afterwards: the
      record, the ledger, `figures.json`, the regenerated texts, and the two "what weakens a claim" items rewritten to what the run showed.
- [x] ✅ **Harness frozen.** Tag `harness-v1.10.0`; the harness paths on `main` equal the tag (the launcher refuses otherwise). No harness change after the tag.
- [x] ✅ **Keys.** The leaked keys were rotated and their branches and artifacts deleted; the full-reference secret scan finds neither value
      (`reports/scan_history_for_secrets.py`, `backend/tests/test_no_secrets.py`). The new keys are only in this machine's `.env`, never in the repository or a
      hosted image.
- [x] ✅ **Backend test suite** (2026-10-11, `cd backend && pytest`): 2583 passed, 23 skipped.
- [x] ✅ **Frontend** (2026-10-11): `tsc --noEmit` clean; `vitest run` 43 tests in 5 files pass.
- [ ] ❌ **ESLint: not done.** `npm run lint` runs `eslint .`, but `frontend/` has no ESLint configuration and `package.json` declares no `eslint` package, so the
      script does not lint anything.
      Left as is by the owner's decision (2026-10-11); recorded here, not hidden.
- [x] ✅ **Generated texts match their sources** (2026-10-11): `reports/v1.9/figures.py --write` rebuilds `figures.json` byte-identical from the records, and
      `reports/texts/render.py --check` reports the three generated texts match it.
- [x] ✅ **Certificates verify offline.** `python scripts/verify_passport.py <file>`.
- [ ] Note on §13 item 3 (a live run from the public URL): superseded by the owner's decision of 2026-10-10. The hosted demo is keyless, because an HTTP client's
      error text can carry a request header into a run's outputs inside the sealed harness (`METHODOLOGY.md`, "harness-v1.10.0 frozen").

## What is left, in order

1. The owner's go for the live run, then its after-reading (BILLED). The reading before it: $41.97 (the owner's screenshot, 2026-10-11).
2. The hosted demo: A or B above, then the URL in the README and the form.
3. The video, from the shot list.
4. The form: category, description and answers (regenerated after step 1), feedback, Builders & Brews, submit by Oct 28.
