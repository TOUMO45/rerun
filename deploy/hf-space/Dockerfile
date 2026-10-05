# RERUN demo on a Hugging Face Space (Docker SDK, CPU, free tier): no API key, no spend.
# The backend runs in DEMO mode: it replays the committed audit records (DEV and gate entries; the TEST set stays behind the firewall)
# and refuses live execution with HTTP 409. The app code is the repository's own, cloned at REF; nothing here changes it.
#
# Build args:
#   REPO  the public repository to clone
#   REF   a commit, tag or branch; pin a commit for a reproducible Space (see README.md)
ARG REPO=https://github.com/TOUMO45/rerun.git
ARG REF=main

# --- the frontend, built from the same checkout ---------------------------------------------------------------------------------------
FROM node:20-alpine AS web
ARG REPO
ARG REF
RUN apk add --no-cache git
RUN git clone --filter=blob:none "$REPO" /src && git -C /src checkout "$REF"
WORKDIR /src/frontend
RUN npm ci && npm run build

# --- the backend + nginx, one container on the Space's port 7860 ---------------------------------------------------------------------------
FROM python:3.11-slim
ARG REPO
ARG REF
# git: intake.py shells out to it; nginx: serves the built frontend and proxies /api to the backend, as frontend/nginx.conf does in compose
RUN apt-get update && apt-get install -y --no-install-recommends git nginx && rm -rf /var/lib/apt/lists/*
RUN git clone --filter=blob:none "$REPO" /repo && git -C /repo checkout "$REF" && git -C /repo rev-parse HEAD > /repo/.deployed_commit
RUN pip install --no-cache-dir /repo/backend
COPY --from=web /src/frontend/dist /srv/web
COPY nginx.conf /etc/nginx/nginx.conf
COPY start.sh /start.sh

# Spaces run the container as uid 1000: everything nginx and the backend write goes to paths that user owns
RUN useradd -m -u 1000 user && chmod +x /start.sh \
    && mkdir -p /tmp/nginx && chown -R user /tmp/nginx /srv/web /repo/backend /var/lib/nginx /var/log/nginx
USER user

ENV DEMO_MODE=1 \
    DEMO_ROOT=/repo \
    NEBIUS_API_KEY= \
    TAVILY_API_KEY= \
    DATABASE_URL=sqlite:////tmp/rerun_demo.db \
    PYTHONUNBUFFERED=1
EXPOSE 7860
CMD ["/start.sh"]
