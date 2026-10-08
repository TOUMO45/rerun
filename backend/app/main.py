"""FastAPI orchestrator entrypoint (§4)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.routers import batch, health, runs

log = logging.getLogger(__name__)


def seed_demo_records() -> int:
    """DEMO mode: replay the committed run records into the DB (services/demo_seed.py). The root is `settings.demo_root` or the
    checkout three levels above the `app` package; without a `runs/` directory there, the seeder logs and skips."""
    from app.services import demo_seed

    settings = get_settings()
    root = Path(settings.demo_root) if settings.demo_root else demo_seed.PACKAGE_REPO_ROOT
    db = SessionLocal()
    try:
        added = demo_seed.seed(db, root)
        return added + demo_seed.seed_scenes(db, root)  # harness-v1.9: the scenes' records (task 5)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if get_settings().demo_mode:
        try:
            seed_demo_records()
        except Exception:  # the demo must still serve whatever was seeded before; a seeding bug is logged, never fatal
            log.exception("demo seed failed")
    yield


app = FastAPI(title="RERUN", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(runs.router)
app.include_router(batch.router)
