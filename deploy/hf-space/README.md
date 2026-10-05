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

# RERUN on a Hugging Face Space (demo mode)

> **Note (2026-10-05):** creating a Docker Space required a paid plan on the owner's account (seen on the Space creation page), so this path is kept but not used. The free hosted demo is on Render: `deploy/render/README.md`. The image here was built and run locally and works.

This Space replays the committed audit records of [RERUN](https://github.com/TOUMO45/rerun). There is no API key and nothing is spent: live execution is refused (HTTP 409). Every certificate shows the verdict with its label, the outcome ladder and the blocker, and the downloaded certificate verifies offline with `python scripts/verify_passport.py <file>` from the repository.

What the image does (see `Dockerfile`): it clones the public repository at `REF`, builds the frontend, installs the backend, and runs both behind nginx on port 7860, as an unprivileged user, with `DEMO_MODE=1` and a fresh SQLite database in `/tmp`. The app code is the repository's own; nothing in this folder changes it.

## Steps (the owner, once)

These steps need your Hugging Face account. RERUN never needs or asks for a token.

1. On huggingface.co: **New Space**, SDK **Docker**, template **Blank**, hardware **CPU basic (free)**, visibility of your choice. Note the Space's name, e.g. `<you>/rerun-demo`.
2. Clone the empty Space and copy this folder's five files into it (`Dockerfile`, `nginx.conf`, `start.sh`, `README.md`, `.gitattributes`):

   ```bash
   git clone https://huggingface.co/spaces/<you>/rerun-demo
   ```
   ```bash
   cp deploy/hf-space/Dockerfile deploy/hf-space/nginx.conf deploy/hf-space/start.sh deploy/hf-space/README.md deploy/hf-space/.gitattributes rerun-demo/
   ```

3. Optional but recommended: pin the build to a commit, so the Space shows exactly what you reviewed. In the Space's copy of `Dockerfile`, change `ARG REF=main` to `ARG REF=<commit sha>` (for example the commit you submit to Devpost).
4. Commit and push; Hugging Face asks for your credentials in its own prompt:

   ```bash
   cd rerun-demo && git add -A && git commit -m "RERUN demo" && git push
   ```

5. The Space builds (about 5 to 10 minutes: the frontend build and the backend install). When it shows **Running**, open it: the Gallery lists the recorded audits; open a certificate and press **Download certificate JSON**. The container log's first line names the deployed commit.

## What to check after it is up

- `/gallery` lists the recorded audits (the latest round of each entry) and no live rows.
- A certificate page shows the verdict label (for example `BLOCKED (dependency change: torchvision 0.5.0->0.4.0, Pillow 9.0.0->6.2.2)` on DEV entry 05 at harness-v1.7.1).
- The home page accepts a repository URL; intake runs, and **Start execution run** is disabled with the demo-mode explanation.

## Limits

- A free Space sleeps when idle and takes a moment to wake.
- The database is in `/tmp`: it is rebuilt from the records at every start, so nothing a visitor does persists.
- Demo mode only. A live run needs `NEBIUS_API_KEY` and `TAVILY_API_KEY` and spends money; do not add them to a public Space.
