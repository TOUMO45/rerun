"""Shared fixtures: a TestClient wired to an isolated in-memory SQLite DB,
so router tests never touch the real rerun.db file; and a real local git
"fake paper repo" fixture shared by intake and router tests."""

from __future__ import annotations

import subprocess

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import Base


def _git(*args: str, cwd) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def fake_paper_repo(tmp_path):
    """A minimal but realistic fake 'paper repo' committed to a real local
    git repository, so cloning it is a real filesystem+git operation."""
    src = tmp_path / "source_repo"
    src.mkdir()
    _git("init", "-b", "main", cwd=src)
    _git("config", "user.email", "test@example.com", cwd=src)
    _git("config", "user.name", "Test", cwd=src)

    (src / "requirements.txt").write_text("numpy==1.26.0\ntorch>=2.0\n# a comment\n-e .\n", encoding="utf-8")
    (src / "train.py").write_text(
        "def main():\n    pass\n\nif __name__ == '__main__':\n    main()\n",
        encoding="utf-8",
    )
    (src / "utils.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    notebooks_dir = src / "notebooks"
    notebooks_dir.mkdir()
    (notebooks_dir / "explore.ipynb").write_text("{}", encoding="utf-8")

    _git("add", "-A", cwd=src)
    _git("commit", "-m", "initial", cwd=src)
    return src


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def _override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    # Deliberately not using `with TestClient(...)`: that would trigger the
    # app's startup event, which calls init_db() against the REAL default
    # engine (rerun.db), not this test's in-memory one. Tests only need the
    # routes, not the startup lifecycle.
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
