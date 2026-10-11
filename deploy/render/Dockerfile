# RERUN demo on Render (Docker runtime, free instance): no API key, no spend.
# The image of deploy/hf-space/ (the same pins, the same keyless guard), with the port Render assigns: Render sets PORT (default 10000) and expects the
# service on 0.0.0.0:$PORT, so start.sh writes it into nginx's configuration at start. The backend runs in DEMO mode: it replays the committed audit
# records (DEV and gate entries; the TEST set stays behind the firewall) and refuses live execution with HTTP 409. The app code is the repository's own,
# cloned at REF; nothing here changes it. The keyless workflow (.github/workflows/demo-check.yml) builds this folder at every pushed commit and probes it.
#
# Build args:
#   REPO  the public repository to clone
#   REF   the commit to serve, a full SHA (a pinned commit also keeps Render's layer cache from serving an old clone of a branch);
#         change it to the commit you submit, push, then deploy (README.md)
ARG REPO=https://github.com/TOUMO45/rerun.git
ARG REF=6fba7f519306453eefd15514c2c4a98cfab993ca

# --- the frontend, built from the same checkout ---------------------------------------------------------------------------------------
FROM node:20.19.5-alpine AS web
ARG REPO
ARG REF
RUN apk add --no-cache git
RUN git clone --filter=blob:none "$REPO" /src && git -C /src checkout "$REF"
WORKDIR /src/frontend
RUN npm ci && npm run build

# --- the backend + nginx, one container on Render's $PORT -------------------------------------------------------------------------------
# Python 3.14: the pinned versions (.github/seal/constraints.txt) are the environment the harness was tested in, made on 3.14
FROM python:3.14-slim
ARG REPO
ARG REF
# git: intake.py shells out to it; nginx: serves the built frontend and proxies /api to the backend, as frontend/nginx.conf does in compose
RUN apt-get update && apt-get install -y --no-install-recommends git nginx && rm -rf /var/lib/apt/lists/*
RUN git clone --filter=blob:none "$REPO" /repo && git -C /repo checkout "$REF" && git -C /repo rev-parse HEAD > /repo/.deployed_commit
# pinned: every backend dependency at the version the harness was tested with (the seal workflow installs the same way)
RUN pip install --no-cache-dir -c /repo/.github/seal/constraints.txt /repo/backend
# keyless: a clone never holds a .env, and none may reach the image
RUN find /repo -name .env -type f -delete
COPY --from=web /src/frontend/dist /srv/web
COPY nginx.conf.template /etc/nginx/rerun.conf.template
COPY start.sh /start.sh
# a checkout on Windows may give start.sh CRLF line ends, which /bin/sh cannot run
RUN sed -i 's/\r$//' /start.sh

# an unprivileged user owns everything nginx and the backend write; the port Render assigns is above 1024
RUN useradd -m -u 1000 user && chmod +x /start.sh \
    && mkdir -p /tmp/nginx && chown -R user /tmp/nginx /srv/web /repo/backend /var/lib/nginx /var/log/nginx
USER user

# DEMO_MODE is set here and again in render.yaml; the key variables are set empty, and start.sh refuses to start if one is set
ENV DEMO_MODE=1 \
    DEMO_ROOT=/repo \
    NEBIUS_API_KEY= \
    TAVILY_API_KEY= \
    DATABASE_URL=sqlite:////tmp/rerun_demo.db \
    PYTHONUNBUFFERED=1 \
    PORT=10000
EXPOSE 10000
CMD ["/start.sh"]
