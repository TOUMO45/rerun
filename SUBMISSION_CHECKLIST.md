# Hackathon submission checklist (§12)

Tracks `RERUN_BUILD_DIRECTIVE.md` §12's compliance checklist with evidence per item, per
§13 item 7 ("Every item in §12 is checked, with evidence... next to each line in the
submission notes"). Created because no such tracking file existed despite being an
explicit definition-of-done requirement — see `DECISIONS.md`.

Legend: ✅ done, verified · 🧩 code/content ready, blocked only on a human/process step ·
❌ not done, blocking submission · 👤 pure human/process action, not verifiable from code.

- [x] ✅ **Uses ≥1 NVIDIA open-source model — Nemotron 3 Nano + Super + Ultra.**
      `backend/app/config.py` routes all three by task (`nebius_model_recon`,
      `nebius_model_planner`/`nebius_model_repairer`, `nebius_model_adjudicator`);
      `model_client.py` is the shared, tested call path all four services use.
- [ ] 🧩 **Runs on Nebius Token Factory (Sandboxes + inference).** Code is built and
      source-verified against the real installed SDKs (`contree-sdk`, OpenAI-compatible
      client), but has never been exercised against the live API — no `NEBIUS_API_KEY`
      in this environment. See README's 🚧/🟡 markers for exactly what's source-verified
      vs. live-verified. **Needs:** a real key, then a real `POST /runs/{id}/execute`
      against a real repo before submission.
- [ ] 👤 **Category: Coding and Agentic Engineering.** A submission-form field, not code.
- [x] ✅ **Project description: what it is, why, how it works.** README's opening
      section already has this content, adapted from §1 of the directive — copy into
      the submission form as-is.
- [ ] ❌ **Working demo URL (hosted app).** Not deployed. Nebius Serverless Endpoints
      hosting is explicitly not yet built (README). **Needs:** live credentials +
      an actual deploy, which is a real infrastructure action outside what this
      session can do unilaterally.
- [ ] ❌ **Demo video: public YouTube, ≤3 min, audio covers Token Factory + NVIDIA.**
      `docs/demo_script.md` has the exact narration/timing and a pre-recording checklist
      (created this session — see `DECISIONS.md`), but the video itself hasn't been
      recorded. **Needs:** the working demo URL above, plus a human to actually record
      and upload it.
- [ ] ❌ **Public repo, Apache-2.0 license visible at the top of the repo page.**
      `LICENSE` (Apache-2.0) exists at repo root, but `git remote -v` shows this repo
      has never been pushed anywhere — it's local-only. **Needs:** a human decision to
      create/push to a public GitHub repo (not something this session does
      unilaterally — publishing a new public repo is exactly the kind of action that
      needs explicit go-ahead).
- [x] ✅ **README with setup instructions and clear run guidance.** `README.md`'s
      "Running the backend tests" / "Running the full stack via Docker" sections;
      re-verified working from a genuinely fresh clone this session (`DECISIONS.md`).
- [x] ✅ **README highlights NVIDIA model usage, Token Factory, and every other Nebius
      service (Sandboxes, Serverless Jobs, Serverless Endpoints).** README's dedicated
      "NVIDIA / Nebius usage (hackathon requirement)" section names all of them
      substantively, not as token mentions.
- [ ] 👤 **Feedback submitted on Token Factory / AI Cloud / NVIDIA tools.** Pure human
      action on an external platform — not verifiable or actionable from this repo.
- [x] ✅ **Not built from pre-existing code (or the required written explanation is
      included).** True: this project was built from an empty repository over the
      course of one autonomous agent session — see `DECISIONS.md`'s first entry
      ("Repo bootstrap") and the full git history for the complete build record. This
      note *is* the required written explanation.
- [ ] 👤 **Builders & Brews city selected if attended.** Pure human/attendance fact this
      session has no way to know — fill in if applicable, otherwise mark N/A.
- [x] ✅ **Tavily called at runtime, cited in the certificate — Best Use of Tavily
      eligibility.** `tavily.py`, wired into the real repair loop
      (`orchestrator.py`'s attempt loop calls `tavily.fetch_context` before every
      repair proposal); cited sources render in `RepairAttemptCard.tsx` and are part of
      the certificate's `diffs[].tavily_sources`.
- [ ] 👤 **Submitted before Oct 30, 2026, 10:00am PDT (internal target: Oct 28).**
      Deadline tracking — not a code item.

## What this means concretely, in priority order

1. Get a real `NEBIUS_API_KEY` (and `TAVILY_API_KEY`) and run one real end-to-end
   `S1 → S2 → S3` pass against a real repo, to move the first ❌/🧩 item to ✅.
2. Deploy to Nebius Serverless Endpoints (needs the key above) → working demo URL.
3. Record the demo video per `docs/demo_script.md`, using the real deployed URL.
4. Push this repo to a public GitHub repository with the `LICENSE` visible at the top.
5. Fill in the remaining 👤 items (category selection, feedback, Builders & Brews,
   actual submission) as part of the real submission flow on the hackathon platform.
