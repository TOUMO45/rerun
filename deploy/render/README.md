# RERUN demo on Render (free instance, keyless)

A public, no-key demo of RERUN: the backend in demo mode replays the committed audit records (the DEV and gate entries) and refuses live execution with HTTP 409, so the service can never spend. The frontend and backend are the repository's own code, cloned at the commit `ARG REF` pins; this folder only packages them behind nginx on the port Render assigns.

**State on 2026-10-12.** <https://rerun-demo.onrender.com> answers (probed: demo mode, no key configured), but it still serves the commit deployed on 2026-10-06 (harness-v1.7.2's records, built from the old, unpinned image of this folder): its Batch Lab predates the harness-v1.9 and v1.10 results the repository's README reports. For the submission, `ARG REF` already pins the submitted commit (steps 1 and 2 below are done); what remains is steps 3 to 6 in the dashboard. The service is on the free plan, which sleeps when idle: on 2026-10-11 a cold load took 51.7 s and the next one 0.87 s.

## What the image does (the same standard as `deploy/hf-space/`)

- **Pinned.** `node:20.19.5-alpine` builds the frontend from its lock file (`npm ci`); `python:3.14-slim` installs the backend with every dependency at the version the harness was tested with (`pip install -c .github/seal/constraints.txt`); `ARG REF` is a full commit SHA, so the service serves exactly that commit.
- **Keyless by construction.** The image sets `NEBIUS_API_KEY` and `TAVILY_API_KEY` empty and deletes any `.env`. `start.sh` refuses to start if `NEBIUS_API_KEY`, `NEBIUS_PROJECT_ID` or `TAVILY_API_KEY` is set (an environment variable added to the service by mistake), if `DEMO_MODE` is not `1`, or if a `.env` exists; the message names the variable, never its value. Live mode in a hosted service is out of scope: an HTTP client's error text can carry a request header into a run's log, record, API response and page, and that path is inside the sealed harness (`METHODOLOGY.md`, "harness-v1.10.0 frozen").
- **Proven by the keyless workflow.** `.github/workflows/demo-check.yml` (no secret, read-only) builds this folder at every pushed commit with `REF` set to that commit, checks that the image holds no `.env`, no key value and no secret-shaped string, that it refuses to start with a key set without printing the value, and then runs it as Render does (`PORT=10000`, an empty `/tmp`, 512 MB) and probes it with the same checks as `python demo.py --check`.

## Steps (the owner, in the Render dashboard)

The service `rerun-demo` exists and is connected to `TOUMO45/rerun`. To serve the commit you submit:

1. In this repository, set `ARG REF=` in `deploy/render/Dockerfile` to the full SHA of the commit you submit (`git rev-parse HEAD` before this edit), commit and push. That one-line commit sits on top of the submitted one and changes nothing the service serves.
2. Wait until the push's run of **demo check (keyless, no spend)** is green on GitHub (its `render-image` job built and probed exactly this folder).
3. In Render: the `rerun-demo` service > **Settings**. Check: **Root Directory** `deploy/render`, **Dockerfile Path** `./Dockerfile`, **Instance Type** Free, **Health Check Path** `/api/healthz`, **Auto-Deploy** off.
4. **Environment**: exactly one variable, `DEMO_MODE` = `1`. Delete any other. If a key variable is present, the new container refuses to start.
5. **Manual Deploy** > **Deploy latest commit**. The build takes about 5 to 10 minutes. The log's first runtime line names the commit served: `RERUN demo: commit <sha>, DEMO_MODE=1, port 10000`. Check that it is the SHA of step 1.
6. Open `https://rerun-demo.onrender.com/api/healthz` (expect `"demo_mode":true`, both `configured` fields false), then the checks below.

A new service instead: **New** > **Web Service** with the same values (Language Docker, Branch `main`, Root Directory `deploy/render`, Instance Type Free, `DEMO_MODE` = `1`, nothing else), or **New** > **Blueprint** pointed at `deploy/render/render.yaml`.

## What to check once it is up

- The Gallery lists the recorded audits with no live rows; a certificate page shows its verdict label, the outcome ladder and the blocker; **Download certificate JSON** gives a file that `python scripts/verify_passport.py <file>` verifies.
- The Batch Lab shows the figures of `reports/v1.9/figures.json` at the pinned commit.
- On the home page a repository URL goes through intake and **Start execution run** is disabled with the demo-mode explanation.

## Limits

- **Cold start.** A free service spins down when idle; Render's own notice says this "can delay requests by 50 seconds or more" (on 2026-10-11 the first page load took about 42 s). Open it once before a judge does.
- **Nothing persists.** The database is in `/tmp` and is rebuilt from the committed records at every start.
- **Not in the hosted demo:** the TEST-phase records (the demo seeder's firewall leaves them out) and live runs.
