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
from app.services.cost_guard import get_shared_cost_guard


@pytest.fixture(autouse=True)
def _reset_shared_cost_guard():
    """`get_shared_cost_guard()` is an `lru_cache`d process-wide singleton
    by design (see cost_guard.py) — without this, one test's recorded
    spend/attempts would leak into every test that runs after it in the
    same pytest process."""
    get_shared_cost_guard.cache_clear()
    yield
    get_shared_cost_guard.cache_clear()


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
    # GitHub allows fetching a specific commit SHA directly for public
    # repos (what intake.clone_repo_at_commit relies on); a plain local
    # git repo does NOT allow this by default (`Server does not allow
    # request for unadvertised object`). Enabling it here makes this
    # fixture actually mirror GitHub's real behavior for tests that need
    # fetch-by-commit, rather than everyone needing to remember to set it.
    _git("config", "uploadpack.allowReachableSHA1InWant", "true", cwd=src)

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
def client(monkeypatch):
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
    # GET /runs/{id}/stream's background worker thread creates its own
    # session by calling `SessionLocal()` directly (a background thread
    # can't use a request-scoped `Depends(get_db)` — FastAPI's dependency
    # override mechanism only applies to request-time DI, not code that
    # imports and calls a session factory itself). Without also
    # redirecting that direct import, the worker thread would silently
    # talk to the real default `rerun.db` engine — uninitialized in tests
    # — instead of this fixture's isolated in-memory one. Found by
    # actually running the stream test, not by inspection.
    monkeypatch.setattr("app.routers.runs.SessionLocal", TestingSessionLocal)
    # Deliberately not using `with TestClient(...)`: that would trigger the
    # app's startup event, which calls init_db() against the REAL default
    # engine (rerun.db), not this test's in-memory one. Tests only need the
    # routes, not the startup lifecycle.
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _no_real_http_in_dependency_resolver(monkeypatch):
    """dep_resolver's default GitHub/PyPI GET must never hit the network in
    the unit suite; tests that exercise it inject their own `http_get`."""
    from app.services import dep_resolver

    def _blocked(url):
        raise RuntimeError(f"real HTTP disabled in tests: {url}")

    monkeypatch.setattr(dep_resolver, "_default_http_get", _blocked)


@pytest.fixture(autouse=True)
def _no_real_uv_in_time_machine(monkeypatch):
    """The unit suite never shells out to uv (network + minutes); tests that
    exercise the time machine inject `lock_compiler` or a runner."""
    from app.services import time_machine

    def _blocked(argv, stdin_text):
        raise RuntimeError("real uv disabled in tests")

    monkeypatch.setattr(time_machine, "_default_runner", _blocked)
