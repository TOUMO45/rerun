"""App configuration, loaded from environment / .env (see .env.example).

Every field here corresponds to a variable a human can find and change in
one place — no config value is ever hardcoded again elsewhere in the
codebase once it's listed here.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", env_file_encoding="utf-8", extra="ignore")

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
    database_url: str = "sqlite:///./rerun.db"
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
