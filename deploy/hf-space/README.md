---
title: RERUN demo
emoji: 🔁
colorFrom: gray
colorTo: green
sdk: docker
app_port: 7860
pinned: false
license: apache-2.0
short_description: Replays RERUN's recorded reproducibility audits; no key, no spend.
---

# RERUN on a Hugging Face Space (keyless demo)

This Space replays the committed audit records of [RERUN](https://github.com/TOUMO45/rerun). It holds **no API key and spends nothing**: the backend runs in demo mode and refuses live execution (HTTP 409). Every certificate shows the verdict with its label, the outcome ladder and the blocker, and a downloaded certificate verifies offline with `python scripts/verify_passport.py <file>` from the repository.

What the image does (`Dockerfile`): it clones the public repository at `REF`, builds the frontend (`npm ci`, locked versions), installs the backend with every dependency pinned to the version the harness was tested with (`.github/seal/constraints.txt`), and runs both behind nginx on port 7860 as an unprivileged user, with `DEMO_MODE=1` and a fresh SQLite database in `/tmp`. The app code is the repository's own; nothing in this folder changes it.

**Keyless by construction.** The image sets the three key variables empty and deletes any `.env`. `start.sh` refuses to start if `NEBIUS_API_KEY`, `NEBIUS_PROJECT_ID` or `TAVILY_API_KEY` is set (a Space secret added by mistake), if `DEMO_MODE` is not `1`, or if a `.env` exists; the message names the variable, never its value. Live mode in a hosted Space is out of scope: an HTTP client's error text can carry a request header into a run's log, record, API response and page, and that path is inside the sealed harness (`METHODOLOGY.md`, "harness-v1.10.0 frozen").

## Steps (the owner)

These steps need your Hugging Face account. RERUN never needs or asks for a token.

1. On huggingface.co: **New Space**, SDK **Docker**, template **Blank**, hardware **CPU basic**, visibility **Public**. Note the Space's name, for example `<you>/rerun-demo`. (On 2026-10-05 the creation page asked for a paid plan for a Docker Space on this account; check what it asks now.)
2. **Do not add any secret or variable** under the Space's Settings. If one of the three key names is set, the container refuses to start.
3. Clone the empty Space and copy this folder's five files into it:

   ```bash
   git clone https://huggingface.co/spaces/<you>/rerun-demo
   ```
   ```bash
   cp deploy/hf-space/Dockerfile deploy/hf-space/nginx.conf deploy/hf-space/start.sh deploy/hf-space/README.md deploy/hf-space/.gitattributes rerun-demo/
   ```

4. Pin the build to the commit you submit, so the Space shows exactly what you reviewed. In the Space's copy of `Dockerfile`, change `ARG REF=main` to `ARG REF=<commit sha>`.
5. Commit and push; Hugging Face asks for your credentials in its own prompt:

   ```bash
   cd rerun-demo && git add -A && git commit -m "RERUN demo" && git push
   ```

6. The Space builds (about 5 to 10 minutes). The container log's first line names the deployed commit; check that it is the one you pinned.

## What to check after it is up

- The Gallery lists the recorded audits and no live rows.
- A certificate page shows the verdict label, the outcome ladder and the blocker; **Download certificate JSON** works.
- The Batch Lab shows the result figures (they come from `reports/v1.9/figures.json` in the pinned commit).
- The home page accepts a repository URL; intake runs, and **Start execution run** is disabled with the demo-mode explanation.

## Limits

- A free Space sleeps when idle and takes a moment to wake.
- The database is in `/tmp`: it is rebuilt from the records at every start, so nothing a visitor does persists.
- The same app runs locally from a clone with one command and no Docker: `python demo.py` (see the repository's README).
