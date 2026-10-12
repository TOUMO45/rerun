# Hackathon submission checklist (§12)

Tracks `RERUN_BUILD_DIRECTIVE.md` §12 with evidence per item (§13 item 7). **Rewritten from the actual state on 2026-10-11 and brought up to date on 2026-10-12**
(the first version, `f5b2d6e`, was written before the repository was public and before any live run). **The paid-run window for this submission is closed (owner,
2026-10-12): no further paid run of any kind.**

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
      `reports/texts/render.py` (the word limit and every number's tag are guarded by tests), regenerated after the two live runs of 2026-10-11/12.
- [ ] ⏳ **Working demo URL (hosted app): Render (the owner's choice B, 2026-10-12).** `deploy/render/Dockerfile` pins `ARG REF` to the submitted commit; the keyless
      workflow `.github/workflows/demo-check.yml` (no secret) builds the image, checks that it holds no `.env` or key and refuses to start with one without printing the
      value, runs it as Render does (`PORT=10000`, an empty `/tmp`, 512 MB) and probes it, beside the Space image and the fresh-clone runs of `python demo.py --check`
      on Linux and Windows. **Owner:** Manual Deploy on Render (`deploy/render/README.md`) and check that the log's first runtime line names the pinned SHA. The service
      is on Render's free plan, which sleeps when idle (measured 2026-10-11: 51.7 s cold, 0.87 s warm); the README says the first load can take about a minute.
- [ ] 👤 **Demo video: public YouTube, at most three minutes, audio covers Token Factory and NVIDIA models.** Not recorded. The shot list
      `docs/submission/video_shot_list.md` names Nebius Token Factory in the sandbox shot and the Nemotron models in the repair shot; it uses `python demo.py`.
- [x] ✅ **Public repository, Apache-2.0.** <https://github.com/TOUMO45/rerun>: GitHub's API reports it public with license `Apache-2.0` detected from the
      root `LICENSE` (2026-10-11), which is what the repository page shows; README "License".
- [x] ✅ **README with setup instructions and run guidance.** README "Run it in one command" (`python demo.py`, keyless) is run from a fresh clone on Linux and on
      Windows by the keyless workflow at every push to `main`; README "Run it live" for a live run. The Docker Compose demo was removed on 2026-10-11 because no
      workflow ever tested it (the owner accepted the deletion).
- [x] ✅ **README highlights NVIDIA model usage and the Nebius services used.** README "Where Nemotron is used", "Where Token Factory is used" (Sandboxes, the model
      endpoints, the price list, the seal). Serverless Jobs and Serverless Endpoints are **not used**, and the README does not claim them; the hosted demo runs on Render.
- [ ] 👤 **Feedback submitted on Token Factory / AI Cloud / NVIDIA tools.** On the hackathon platform.
- [x] ✅ **Not built from pre-existing code.** `DECISIONS.md`'s first entry ("Repo bootstrap") and the git history from an empty repository.
- [ ] 👤 **Builders & Brews city, if attended.** Fill in or mark not applicable.
- [x] ✅ **Tavily called at runtime and cited in the certificate**, with what the records do not show. Called before every repair attempt; the references offered
      (`consulted`) and the sources cited (`tavily_sources[].cited_via`) are stored on the attempt and in the certificate. Counted by run over every committed live
      record (`figures.json`, `tavily_by_harness`): 24 of the 88 live runs that were offered references cite one, 24 of all 203 live runs. The run of 2026-10-11/12
      (`reports/v1.10/tavily_live/`) closed the flag mode's Tavily gap: 3 references offered to each of 3 candidates, one candidate cited a source, the adopted patch did
      not. Whether a citation shapes a decision is not measured (D-21, open); nothing shows that Tavily improved a repair.
- [ ] 👤 **Submitted before Oct 30, 2026, 10:00am PDT** (internal target Oct 28).

## The project's own gate

- [x] ✅ **The pre-registered live run for the flag's positive path** (`reports/v1.10/review_live/PLAN.md`, Amendment 1 committed before the run): M-FAC, TIMEOUT in
      the baseline, no repair attempt, so nothing about the flag; $0.2130 API-reported; BILLED $41.97 before, $41.96 after; not run again. Recorded, with the texts'
      "what weakens these claims" items rewritten to it.
- [x] ✅ **The live run for the Tavily gap** (`reports/v1.10/tavily_live/PLAN.md`, committed before the run): minmaxot, RUNS_AFTER_REPAIR (the wiring check's verdict),
      no attempt flagged, no REVIEW_REQUIRED; $3.9763 API-reported; BILLED $41.96 before and after.
- [x] ✅ **Harness frozen.** Tag `harness-v1.10.0`; the harness paths on `main` equal the tag. No harness change after the tag.
- [x] ✅ **Keys.** The leaked keys were rotated and their branches and artifacts deleted; the full-history secret scan finds neither value
      (`reports/scan_history_for_secrets.py`, `backend/tests/test_no_secrets.py`). The new keys are only in this machine's `.env`, never in the repository or a
      hosted image.
- [ ] ❌ **ESLint: not done.** `npm run lint` runs `eslint .`, but `frontend/` has no ESLint configuration and `package.json` declares no `eslint` package, so the
      script does not lint anything. Left as is by the owner's decision (2026-10-11); recorded here, not hidden.
- [x] ✅ **Certificates verify offline.** `python scripts/verify_passport.py <file>` (both certificates of 2026-10-11/12 verified).
- [ ] Note on §13 item 3 (a live run from the public URL): superseded by the owner's decision of 2026-10-10. The hosted demo is keyless, because an HTTP client's
      error text can carry a request header into a run's outputs inside the sealed harness (`METHODOLOGY.md`, "harness-v1.10.0 frozen").

## What is left, in order

1. Render: Manual Deploy, then check the commit in the log's first runtime line and open the Gallery once (the free plan sleeps when idle).
2. The video, from the shot list.
3. The form: category, the description and answers in `docs/submission/`, feedback, Builders & Brews; submit by Oct 28.
