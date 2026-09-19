"""App configuration, loaded from environment / .env (see .env.example).

Every field here corresponds to a variable a human can find and change in
one place — no config value is ever hardcoded again elsewhere in the
codebase once it's listed here.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# The repo root's .env, resolved from this file's own location — NOT a
# bare relative string. A relative `env_file="../.env"` is resolved
# against the process's current working directory at Settings()
# construction time, which silently changes depending on whether the app
# is launched from the repo root, from backend/, or from inside a Docker
# container's WORKDIR — with no error if it resolves to nothing, just
# quietly-empty defaults. Verified empirically: `env_file="../.env"` did
# load a repo-root .env correctly when run from backend/, but silently
# found nothing (falling back to all-defaults) when run from the repo
# root itself. Docker deployment was never actually affected by this
# (docker-compose's `env_file:` injects vars straight into the process
# environment, which pydantic-settings also always reads), but local,
# non-Docker usage was fragile in exactly the way a "reproducibility
# tool with an irreproducible setup" (§4.1) must not be.
_REPO_ROOT_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_REPO_ROOT_ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    # Nebius Token Factory (inference)
    nebius_api_key: str = ""
    nebius_base_url: str = "https://api.tokenfactory.nebius.com/v1"
    nebius_model_recon: str = "nvidia/nemotron-3-nano"
    nebius_model_planner: str = "nvidia/nemotron-3-super"
    nebius_model_repairer: str = "nvidia/nemotron-3-super"
    nebius_model_adjudicator: str = "nvidia/nemotron-3-ultra"

    # Nebius Sandboxes / Serverless Jobs
    nebius_project_id: str = ""
    nebius_sandbox_image: str = "python:3.11-slim"
    nebius_sandbox_wall_clock_seconds: float = 600.0

    # Tavily
    tavily_api_key: str = ""

    # App
    # `./data/rerun.db` — kept in sync with docker-compose.yml's
    # `backend-data` volume, mounted at /app/data (the container's cwd is
    # always /app). See db.py's module docstring for why this matters.
    database_url: str = "sqlite:///./data/rerun.db"
    demo_mode: bool = False
    daily_cost_ceiling_usd: float = 25.0
    max_attempts_per_run: int = 3
    # §7: committed at repo root, precomputed by the offline batch runner.
    batch_results_path: str = "../batch_results.json"

    @property
    def nebius_configured(self) -> bool:
        return bool(self.nebius_api_key)

    @property
    def tavily_configured(self) -> bool:
        return bool(self.tavily_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
