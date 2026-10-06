# RERUN demo on Render (Docker runtime, free instance): no API key, no spend.
# Same image as deploy/hf-space/, with the port Render assigns: Render sets PORT (default 10000) and expects the service on 0.0.0.0:$PORT,
# so start.sh writes it into the nginx configuration at start. The backend runs in DEMO mode: it replays the committed audit records
# (the DEV and gate entries; the demo seeder's firewall still leaves the TEST records out) and refuses live execution with HTTP 409.
# The app code is the repository's own, cloned at REF; nothing here changes it.
#
# Build args:
#   REPO  the public repository to clone
#   REF   the commit to serve; pinned to the submission commit (change it here to serve another one)
ARG REPO=https://github.com/TOUMO45/rerun.git
ARG REF=a7f5c4cab2d27874da6bce78187aae66160ddd85

# --- the frontend, built from the same checkout ---------------------------------------------------------------------------------------
FROM node:20-alpine AS web
ARG REPO
ARG REF
RUN apk add --no-cache git
RUN git clone --filter=blob:none "$REPO" /src && git -C /src checkout "$REF"
WORKDIR /src/frontend
RUN npm ci && npm run build

# --- the backend + nginx, one container on Render's $PORT -------------------------------------------------------------------------------
FROM python:3.11-slim
ARG REPO
ARG REF
# git: intake.py shells out to it; nginx: serves the built frontend and proxies /api to the backend (as frontend/nginx.conf does in compose)
RUN apt-get update && apt-get install -y --no-install-recommends git nginx && rm -rf /var/lib/apt/lists/*
RUN git clone --filter=blob:none "$REPO" /repo && git -C /repo checkout "$REF" && git -C /repo rev-parse HEAD > /repo/.deployed_commit
RUN pip install --no-cache-dir /repo/backend
COPY --from=web /src/frontend/dist /srv/web
COPY nginx.conf.template /etc/nginx/rerun.conf.template
COPY start.sh /start.sh

# an unprivileged user owns everything nginx and the backend write; the port Render assigns is above 1024
RUN useradd -m -u 1000 user && chmod +x /start.sh \
    && mkdir -p /tmp/nginx && chown -R user /tmp/nginx /srv/web /repo/backend /var/lib/nginx /var/log/nginx
USER user

# DEMO_MODE is set here and again in render.yaml; no key is set anywhere (the backend reads none in demo mode)
ENV DEMO_MODE=1 \
    DEMO_ROOT=/repo \
    DATABASE_URL=sqlite:////tmp/rerun_demo.db \
    PYTHONUNBUFFERED=1 \
    PORT=10000
EXPOSE 10000
CMD ["/start.sh"]
