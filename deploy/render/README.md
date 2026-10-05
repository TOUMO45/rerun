# RERUN demo on Render (free instance)

A public, no-key demo of RERUN: the backend in demo mode replays the committed audit records (the DEV and gate entries) and refuses live execution with HTTP 409, so the service can never spend. The frontend and backend are the repository's own code, cloned at a pinned commit; this folder only packages them behind nginx on the port Render assigns.

Tested locally as Render runs it (2026-10-05): `docker build` of this folder, then `docker run -e PORT=10000 --tmpfs /tmp --memory=512m --cpus=0.1` (an empty `/tmp`, the free instance's 512 MB and 0.1 CPU). Healthy after 39 s; page and API answered; demo mode on, no key configured; the Gallery listed 12 recorded audits; a certificate page showed its label; the certificate downloaded through the page verified with `scripts/verify_passport.py`. Memory in use: about 122 MiB.

**Found on the first real deploy (fixed):** Render mounts an empty `/tmp` at run time, so the directory the image created there at build time was missing and `start.sh` exited (`cannot create /tmp/nginx/nginx.conf: Directory nonexistent`). `start.sh` now creates it; the local test above uses an empty `/tmp` for that reason.

## What the service is

| Setting | Value |
|---|---|
| Runtime | Docker |
| Root directory | `deploy/render` |
| Dockerfile path | `./Dockerfile` (relative to the root directory) |
| Instance type | **Free** ($0/month) |
| Health check path | `/api/healthz` |
| Environment variables | `DEMO_MODE` = `1` (also set in the image). **No API key: do not add `NEBIUS_API_KEY` or `TAVILY_API_KEY`.** |
| Port | Render sets `PORT` (default 10000); `start.sh` writes it into nginx's configuration |
| Commit served | `ARG REF` in `Dockerfile`, pinned to the submission commit; to serve another commit, change that line and push |

## Steps (the owner, once, in the Render dashboard)

You are already signed in with GitHub and the `rerun` repository is connected.

1. **New** > **Web Service**, choose the `TOUMO45/rerun` repository.
2. **Name**: `rerun` (or any name; it becomes `https://<name>.onrender.com`).
3. **Language**: `Docker`. **Branch**: `main`. **Region**: any.
4. **Root Directory**: `deploy/render`. **Dockerfile Path**: `./Dockerfile` (leave the default if Render shows `./Dockerfile` relative to the root directory).
5. **Instance Type**: select **Free** ($0 / month, 0.1 CPU, 512 MB). Do not keep a paid plan that may be preselected.
6. **Environment Variables**: add `DEMO_MODE` = `1`. Nothing else.
7. **Advanced** > **Health Check Path**: `/api/healthz`. Turn **Auto-Deploy** off if you want the service to stay on the pinned commit until you choose to redeploy.
8. **Deploy Web Service**. The first build takes about 5 to 10 minutes (the frontend build and the backend install). The log's first runtime line names the commit served: `RERUN demo: commit <sha>, DEMO_MODE=1, port 10000`.

Alternatively, **New** > **Blueprint** and point it at `deploy/render/render.yaml` (same values, free plan).

## What to expect

- **Cold start.** A free service spins down when idle; Render's own notice on the service page says this "can delay requests by 50 seconds or more". Open it once before a judge does.
- **Nothing persists.** The database is in `/tmp` and is rebuilt from the committed records at every start.
- **What to check once it is up:** `https://<name>.onrender.com/gallery` lists the recorded audits with no live rows; a certificate page (for example DEV entry 05 at harness-v1.7.1) shows `BLOCKED (DEPENDENCY CHANGE)`; **Download certificate JSON** gives a file that `python scripts/verify_passport.py <file>` verifies; on the home page a repository URL goes through intake and **Start execution run** is disabled with the demo-mode explanation.
- **Not in the hosted demo:** the TEST-phase records (the demo seeder's firewall leaves them out; they are in `runs/corpus_v2_batch/harness-v1.5-final/test/` and `reports/dev/TEST_RESULT.md`), and live runs.
