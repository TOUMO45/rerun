#!/bin/sh
# Starts the backend (demo mode, set in the Dockerfile's ENV) and nginx in front of it. If either exits, the container exits,
# so the Space shows the failure instead of serving a half-working page.
set -eu
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
