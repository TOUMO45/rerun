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
    nebius_model_recon: str = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
    nebius_model_planner: str = "nvidia/nemotron-3-super-120b-a12b"
    nebius_model_repairer: str = "nvidia/nemotron-3-super-120b-a12b"
    nebius_model_adjudicator: str = "nvidia/Nemotron-3-Ultra-550b-a55b"

    # Per-token model prices, USD per 1M tokens as (input, output). Source:
    # Token Factory's own API, `GET {nebius_base_url}/models?verbose=true`,
    # field `pricing.prompt` / `pricing.completion` (USD per token, x1e6
    # here), retrieved 2026-09-24 with this project's key. The public
    # pricing page (https://tokenfactory.nebius.com/organization/prices) is
    # behind the console login, so it was not read directly. A model not in
    # this table is still called, but its spend is reported as UNPRICED
    # rather than guessed.
    model_prices_usd_per_1m: dict[str, tuple[float, float]] = {
        "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B": (0.06, 0.24),
        "nvidia/nemotron-3-super-120b-a12b": (0.30, 0.90),
        "nvidia/Nemotron-3-Ultra-550b-a55b": (1.00, 3.00),
    }
    model_prices_source: str = "https://api.tokenfactory.nebius.com/v1/models?verbose=true (pricing field)"
    model_prices_retrieved: str = "2026-09-24"

    # Nebius Sandboxes / Serverless Jobs
    nebius_project_id: str = ""
    nebius_sandbox_image: str = "python:3.11-slim"
    nebius_sandbox_wall_clock_seconds: float = 600.0

    # Which backend actually executes untrusted repo code (RERUN directive
    # §3 must-have #3). "token_factory" = contree_sdk against Nebius Token
    # Factory Sandboxes (sandbox.py) — the only backend live-verified so
    # far (see DECISIONS.md's 2026-09-19 entry). "compute" = provision a
    # real Nebius AI Cloud Compute VM per run (compute_sandbox.py) — a
    # SEPARATE Nebius product with a separate credential (see this
    # session's Nebius integration audit), scaffolded but NOT yet
    # exercised against a live account.
    nebius_sandbox_backend: str = "token_factory"

    # --- Nebius AI Cloud (Compute) ------------------------------------
    # Only read when nebius_sandbox_backend == "compute". Deliberately
    # separate from nebius_api_key/nebius_project_id above: Compute uses
    # Nebius's general Cloud IAM (a service-account JSON key downloaded
    # from the console), not Token Factory's bearer API key.
    nebius_compute_credentials_file: str = ""
    nebius_compute_project_id: str = ""
    nebius_compute_subnet_id: str = ""
    nebius_compute_platform: str = "cpu-e2"
    nebius_compute_preset: str = "4vcpu-16gb"
    nebius_compute_image_family: str = ""
    nebius_compute_ssh_username: str = "ubuntu"
    nebius_compute_boot_disk_gib: int = 20

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
    def nebius_compute_configured(self) -> bool:
        return bool(self.nebius_compute_credentials_file)

    @property
    def tavily_configured(self) -> bool:
        return bool(self.tavily_api_key)


class DuplicateEnvKeyError(ValueError):
    """Raised at startup when .env defines the same setting twice, differing
    only by case. Settings names are case-insensitive, so the LATER line
    silently wins — found live (2026-09-24): `Tavily_API_Key= tvly-…` on line
    4 was overridden by an empty `TAVILY_API_KEY=` on line 52, and RERUN ran
    with no Tavily key. The message names the key and line numbers, never the
    value."""


def check_env_file_duplicates(path: Path) -> None:
    if not path.is_file():
        return
    seen: dict[str, tuple[str, int]] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name = line.split("=", 1)[0].strip()
        if name.lower().startswith("export "):
            name = name[7:].strip()
        key = name.lower()
        if key in seen:
            first_name, first_line = seen[key]
            raise DuplicateEnvKeyError(
                f"{path.name} sets {name!r} on line {number} and {first_name!r} on line {first_line}. "
                "Setting names are case-insensitive, so the later line silently overrides the earlier one. "
                "Keep exactly one line for this setting and restart."
            )
        seen[key] = (name, number)


@lru_cache
def _checked_env_file() -> bool:
    check_env_file_duplicates(_REPO_ROOT_ENV_FILE)
    return True


@lru_cache
def get_settings() -> Settings:
    # Refuse to start on an ambiguous .env rather than silently using the
    # wrong value (see DuplicateEnvKeyError).
    _checked_env_file()
    return Settings()
