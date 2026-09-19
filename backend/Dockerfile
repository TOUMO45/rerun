FROM python:3.11-slim

# intake.py shells out to the real `git` binary (clone, ls-remote,
# rev-parse) — python:3.11-slim does not include it. Found by actually
# running `POST /runs` against a live container, not by inspecting the
# Dockerfile: it built and started cleanly with no error until the first
# real request hit this exact code path.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
