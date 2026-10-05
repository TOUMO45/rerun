"""POST /runs passed the user's repo_url straight to `git ls-remote`: `--upload-pack=<cmd>` ran <cmd> on the backend host
(found 2026-10-05 in the UI check: the intake form's error showed git reading the value). Every test here wrote the marker
file, or answered 201 / "repo not found", on the code before the fix."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import get_settings
from app.services import intake
from app.services.intake import RepoUrlInvalidError, validate_repo_accessible, validate_repo_url


def _payload(marker: Path) -> str:
    return f"--upload-pack=sh -c 'echo INJECTED > \"{marker.as_posix()}\"'"


def test_validate_repo_accessible_never_runs_an_option_as_a_command(tmp_path):
    marker = tmp_path / "marker.txt"
    with pytest.raises(RepoUrlInvalidError):
        validate_repo_accessible(_payload(marker))
    assert not marker.exists()


def test_clone_repo_never_runs_an_option_as_a_command(tmp_path):
    marker = tmp_path / "marker.txt"
    with pytest.raises(RepoUrlInvalidError):
        intake.clone_repo(_payload(marker), tmp_path / "dest")
    with pytest.raises(RepoUrlInvalidError):
        intake.clone_repo_at_commit(_payload(marker), tmp_path / "dest2", "0" * 40)
    assert not marker.exists()


def test_post_runs_refuses_the_injection_with_a_clear_422(client, tmp_path):
    marker = tmp_path / "marker.txt"
    response = client.post("/runs", json={"repo_url": _payload(marker)})
    assert response.status_code == 422
    assert response.json()["detail"].startswith("invalid repo URL:")
    assert not marker.exists()


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc",
        "ext::sh -c id",
        "https://gitlab.com/owner/repo",
        "http://github.com/owner/repo",
        "https://github.com/owner",
        "https://github.com/-owner/repo",
        "https://github.com/owner/..",
        "https://github.com/owner/repo/tree/main",
        "https://github.com/owner/repo?x=1",
        "https://github.com.evil.example/owner/repo",
        "git@github.com:owner/repo.git",
        "not a url",
        "https://github.com/owner/repo\n",
        "//evil/share/repo",
    ],
)
def test_validate_repo_url_refuses_anything_but_github_https(url):
    with pytest.raises(RepoUrlInvalidError):
        validate_repo_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/YuliaRubanova/latent_ode",
        "https://github.com/Haichao-Zhang/FeatureScatter/",
        "https://github.com/autumn9999/vmtl.git",
        "https://github.com/IST-DASLab/M-FAC",
        "https://github.com/bckim92/sequential-knowledge-transformer",
        "https://GitHub.com/owner/repo",
        "https://www.github.com/owner/repo.git/",
    ],
)
def test_validate_repo_url_accepts_github_https(url):
    validate_repo_url(url)  # must not raise


def test_a_local_directory_is_admitted_only_when_the_setting_allows_it(tmp_path):
    with pytest.raises(RepoUrlInvalidError):
        validate_repo_url(str(tmp_path))
    validate_repo_url(str(tmp_path), allow_local=True)
    with pytest.raises(RepoUrlInvalidError):
        validate_repo_url("--upload-pack=x", allow_local=True)
    for unc in ("//evil/share/repo", r"\\evil\share\repo"):
        with pytest.raises(RepoUrlInvalidError):
            validate_repo_url(unc, allow_local=True)
    assert get_settings().allow_local_repo_paths is False  # the deployment default


def test_every_corpus_and_scan_url_on_disk_still_passes():
    """No recorded run is turned away by the new rule: every repo URL in the committed run records is a GitHub HTTPS URL."""
    import json

    root = Path(__file__).resolve().parents[2]
    urls: set[str] = set()
    paths = list((root / "runs" / "corpus_v2_batch").glob("harness-v*/**/*.json")) + list((root / "runs" / "live_scan").glob("**/*_certificate.json"))
    for path in paths:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if not isinstance(doc, dict):
            continue
        for part in (doc, doc.get("corpus_entry"), doc.get("certificate"), doc.get("intake")):
            if isinstance(part, dict) and isinstance(part.get("repo_url"), str):
                urls.add(part["repo_url"])
    for url in urls:
        validate_repo_url(url)
    assert len(urls) >= 20
