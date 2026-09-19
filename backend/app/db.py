"""SQLAlchemy engine/session setup. SQLite, single tenant (§4.1).

`DATABASE_URL`'s default (`sqlite:///./data/rerun.db`) is a relative path
deliberately kept in sync with `docker-compose.yml`'s `backend-data`
volume, which mounts at `/app/data` — the container's cwd is always
`/app` (fixed by `Dockerfile`'s `WORKDIR`), so `./data/rerun.db` resolves
to exactly the mounted, persisted path. An earlier version of this
default (`sqlite:///./rerun.db`, no `data/` subdirectory) resolved to
`/app/rerun.db` instead — a path the volume never covered at all, so the
whole database would have been silently discarded on every container
recreation despite the volume declaration looking correct. See
DECISIONS.md. `_ensure_sqlite_dir_exists` covers the other half: SQLite
itself won't create a missing parent directory, which matters for local
(non-Docker) development where nothing else creates `./data/` for you.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import Base


def _ensure_sqlite_dir_exists(url: str) -> None:
    parsed = make_url(url)
    if parsed.drivername != "sqlite" or not parsed.database or parsed.database == ":memory:":
        return
    Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)


def make_engine(database_url: str | None = None):
    url = database_url or get_settings().database_url
    _ensure_sqlite_dir_exists(url)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db(bind_engine=None) -> None:
    Base.metadata.create_all(bind=bind_engine or engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
