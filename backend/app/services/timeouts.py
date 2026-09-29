"""Every network and subprocess timeout the harness uses, in one place
(harness-v1.2). None may rely on a silent client/SDK default: corpus-v1 on
harness-v1.1 lost SearchFair (30.6 MB archive) and ExpressGNN (125.6 MB) to
contree_sdk's default `transport_timeout` of 10 s, which no code here set.

These are constants in sealed harness code, not `.env` settings, so a machine's
environment cannot silently change them after the harness tag.

Audit (value before harness-v1.2 -> now):

| Client / call                              | before                          | now                                  |
|--------------------------------------------|---------------------------------|--------------------------------------|
| Nebius sandbox HTTP (upload, exec, output) | 10 s (SDK default, silent)      | sandbox_transport_timeout(archive)   |
| Nebius sandbox operations (import, run)    | 1000 s (SDK default, silent)    | SANDBOX_OPERATION_S = 1000 s         |
| Nebius per-step run                        | remaining wall clock (explicit) | unchanged (settings wall clock)      |
| Nebius cleanup run                         | 30 s (explicit)                 | SANDBOX_CLEANUP_S = 30 s             |
| Model API (OpenAI client)                  | connect 5 / read, write, pool 600 s (SDK default, silent) | MODEL_* below |
| GitHub + PyPI JSON API                     | 15 s (explicit)                 | HTTP_API_S = 15 s                    |
| Tavily search                              | 60 s (library default, silent)  | TAVILY_S = 60 s                      |
| git fetch (clone of the pinned commit)     | 300 s (explicit)                | GIT_FETCH_S = 300 s                  |
| git local commands (init/config/checkout/rev-parse/log/apply) | 15-30 s (explicit) | GIT_LOCAL_S = 30 s          |
| git ls-tree                                | 60 s (explicit)                 | GIT_LS_TREE_S = 60 s                 |
| uv pip compile                             | 300 s (explicit)                | UV_COMPILE_S = 300 s                 |
| uv python dir                              | 30 s (explicit)                 | UV_QUERY_S = 30 s                    |
"""

from __future__ import annotations

# --- Nebius sandbox ------------------------------------------------------------
# HTTP timeout for every request the contree_sdk client makes, scaled to the
# size of the one upload archive (harness-v1.1 sends the repository as a
# single tar): max(FLOOR, size_MB / MIN_THROUGHPUT + MARGIN).
SANDBOX_TRANSPORT_FLOOR_S = 60.0
# Assumed worst-case upstream throughput to the Nebius API, set by the
# pre-registered probe (runs/upload_probe/probe_2026-09-29_amendment1.json):
# 0.5 x the slowest measured upload rate among passing steps (1.973 MB/s at 75 MB).
UPLOAD_MIN_THROUGHPUT_MBPS = 0.987
# Server-side time after the body is sent (hashing/storing) plus slack.
UPLOAD_MARGIN_S = 30.0
SANDBOX_OPERATION_S = 1000.0
SANDBOX_CLEANUP_S = 30.0

# --- Model API (Token Factory, OpenAI-compatible) -------------------------------
MODEL_CONNECT_S = 10.0
MODEL_READ_S = 600.0  # reasoning models: minutes per reply were observed live
MODEL_WRITE_S = 60.0
MODEL_POOL_S = 60.0

# --- Other external services -----------------------------------------------------
HTTP_API_S = 15.0  # GitHub REST + PyPI JSON
TAVILY_S = 60.0

# --- Subprocesses ------------------------------------------------------------------
GIT_FETCH_S = 300
GIT_LOCAL_S = 30
GIT_LS_TREE_S = 60
UV_COMPILE_S = 300
UV_QUERY_S = 30


def sandbox_transport_timeout(archive_bytes: int) -> float:
    """HTTP timeout (s) for a sandbox client that will upload `archive_bytes`."""
    size_mb = max(0, archive_bytes) / 1_000_000
    return max(SANDBOX_TRANSPORT_FLOOR_S, size_mb / UPLOAD_MIN_THROUGHPUT_MBPS + UPLOAD_MARGIN_S)
