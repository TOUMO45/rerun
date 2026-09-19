"""Tests for POST/GET /runs (§4, §8 S1) against a real local git repo, real
clone, real dependency parsing — no mocking of intake.py."""

from __future__ import annotations


def test_create_run_against_real_local_repo(client, fake_paper_repo):
    response = client.post("/runs", json={"repo_url": str(fake_paper_repo)})
    assert response.status_code == 201
    body = response.json()
    assert len(body["commit_sha"]) == 40
    assert body["stage"] == "RECON_PENDING"
    assert body["repo_url"] == str(fake_paper_repo)


def test_get_run_after_create(client, fake_paper_repo):
    created = client.post("/runs", json={"repo_url": str(fake_paper_repo)}).json()
    response = client.get(f"/runs/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_get_run_negative_control_not_found(client):
    response = client.get("/runs/does-not-exist")
    assert response.status_code == 404


def test_create_run_rejects_empty_repo_url(client):
    response = client.post("/runs", json={"repo_url": "   "})
    assert response.status_code == 422


def test_create_run_rejects_nonexistent_repo(client, tmp_path):
    missing = tmp_path / "no_such_repo"
    response = client.post("/runs", json={"repo_url": str(missing)})
    assert response.status_code == 422
    assert "not found" in response.json()["detail"].lower()


def test_create_run_rejects_repo_with_no_python_code(client, tmp_path):
    import subprocess

    src = tmp_path / "non_python_repo"
    src.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=src, check=True, capture_output=True)
    (src / "README.md").write_text("just docs, no code\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=src, check=True, capture_output=True)

    response = client.post("/runs", json={"repo_url": str(src)})
    assert response.status_code == 422
    assert "no python" in response.json()["detail"].lower()
