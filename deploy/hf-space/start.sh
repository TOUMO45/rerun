#!/bin/sh
# Starts the backend (demo mode, set in the Dockerfile's ENV) and nginx in front of it. If either exits, the container exits,
# so the Space shows the failure instead of serving a half-working page.
set -eu
# keyless demo only (owner, 2026-10-10): refuse to start if a key reaches the container (a Space secret set by mistake) or demo mode is off.
# The message names the variable, never its value.
for name in NEBIUS_API_KEY NEBIUS_PROJECT_ID TAVILY_API_KEY; do
  eval "value=\${$name:-}"
  if [ -n "$value" ]; then echo "refusing to start: $name is set; this image runs the keyless demo only (remove the Space secret)" >&2; exit 1; fi
done
if [ "${DEMO_MODE:-}" != "1" ]; then echo "refusing to start: DEMO_MODE must be 1" >&2; exit 1; fi
if [ -e /repo/.env ]; then echo "refusing to start: /repo/.env exists" >&2; exit 1; fi
# a platform may mount an empty /tmp at run time (Render does): create nginx's directory here
mkdir -p /tmp/nginx
echo "RERUN demo: commit $(cat /repo/.deployed_commit), DEMO_MODE=${DEMO_MODE}"
cd /repo/backend
uvicorn app.main:app --host 127.0.0.1 --port 8000 &
backend=$!
# wait until the backend answers (it seeds the committed records on startup)
i=0
until python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)" 2>/dev/null; do
  i=$((i + 1))
  if [ "$i" -gt 60 ] || ! kill -0 "$backend" 2>/dev/null; then echo "backend did not start" >&2; exit 1; fi
  sleep 1
done
nginx -g 'daemon off;' &
web=$!
# exit as soon as either process exits
while kill -0 "$backend" 2>/dev/null && kill -0 "$web" 2>/dev/null; do sleep 5; done
echo "a process exited; stopping" >&2
exit 1
