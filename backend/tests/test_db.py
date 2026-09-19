"""Tests for db.py's SQLite path handling.

Covers the bug where DATABASE_URL's default (`sqlite:///./rerun.db`)
didn't match docker-compose.yml's volume mount (`/app/data`) — the
database would have lived outside the persisted volume entirely, so it
was silently discarded on every container recreation. Also covers that
SQLite itself never creates a missing parent directory, which matters for
local (non-Docker) development where nothing else creates `./data/`.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from app.config import Settings
from app.db import _ensure_sqlite_dir_exists, make_engine


def test_default_database_url_lives_under_the_docker_volume_mount():
    # §4.1 + docker-compose.yml: the persisted volume mounts at /app/data,
    # and the container's cwd is always /app — a relative sqlite path must
    # resolve under a "data/" subdirectory to actually land inside it.
    from sqlalchemy.engine import make_url

    default_url = Settings.model_fields["database_url"].default
    database_path = make_url(default_url).database
    assert database_path is not None
    assert Path(database_path).parent.name == "data"


def test_make_engine_creates_missing_parent_directory(tmp_path):
    db_path = tmp_path / "nested" / "dirs" / "test.db"
    assert not db_path.parent.exists()

    engine = make_engine(f"sqlite:///{db_path}")
    # A real connection, not just "the call didn't raise" — proves the
    # directory creation actually made the file usable.
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE t (x INTEGER)"))
        conn.execute(text("INSERT INTO t VALUES (1)"))
        conn.commit()
        result = conn.execute(text("SELECT x FROM t")).scalar()
    assert result == 1
    assert db_path.is_file()


def test_ensure_sqlite_dir_exists_negative_control_in_memory_db_is_a_noop(tmp_path, monkeypatch):
    # Must not try to create a directory literally named ":memory:".
    monkeypatch.chdir(tmp_path)
    _ensure_sqlite_dir_exists("sqlite:///:memory:")
    assert list(tmp_path.iterdir()) == []


def test_ensure_sqlite_dir_exists_negative_control_non_sqlite_url_is_a_noop(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _ensure_sqlite_dir_exists("postgresql://user:pass@localhost/db")
    assert list(tmp_path.iterdir()) == []
