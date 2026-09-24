"""Loader/validator for the Batch Lab corpus (§7).

PURE — reads and validates `corpus.yaml`'s structure. Does not touch the
network; `runner.py` is responsible for actually cloning/executing each
entry via Nebius Serverless Jobs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

CORPUS_PATH = Path(__file__).parent / "corpus.yaml"

_REQUIRED_FIELDS = ("name", "repo_url", "commit_sha", "entrypoint_hint", "selection_note")


class CorpusError(ValueError):
    pass


@dataclass(frozen=True)
class CorpusEntry:
    name: str
    repo_url: str
    commit_sha: str
    entrypoint_hint: str
    selection_note: str
    stars_observed: int | None = None
    dependency_files_observed: tuple[str, ...] = ()
    # The repository's own documented command (args allowed) — ground truth
    # for what "runs" means. `command_source` says where it was documented.
    command: str | None = None
    command_source: str = ""


def load_corpus(path: Path | None = None) -> tuple[CorpusEntry, ...]:
    resolved = path or CORPUS_PATH
    if not resolved.is_file():
        raise CorpusError(f"corpus file not found at '{resolved}'")

    data = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "repos" not in data:
        raise CorpusError("corpus.yaml must be a mapping with a top-level 'repos' list")

    repos = data["repos"]
    if not isinstance(repos, list) or not repos:
        raise CorpusError("corpus.yaml's 'repos' must be a non-empty list")

    entries = []
    seen_names: set[str] = set()
    seen_urls: set[str] = set()
    for i, raw in enumerate(repos):
        missing = [f for f in _REQUIRED_FIELDS if f not in raw or not raw[f]]
        if missing:
            raise CorpusError(f"corpus entry #{i} is missing required field(s): {missing}")
        if raw["name"] in seen_names:
            raise CorpusError(f"duplicate corpus entry name: '{raw['name']}'")
        if raw["repo_url"] in seen_urls:
            raise CorpusError(f"duplicate corpus entry repo_url: '{raw['repo_url']}'")
        seen_names.add(raw["name"])
        seen_urls.add(raw["repo_url"])

        if len(raw["commit_sha"]) != 40:
            raise CorpusError(f"corpus entry '{raw['name']}' has a commit_sha that isn't a full 40-char SHA")
        command = raw.get("command")
        if command is not None and (not isinstance(command, str) or not command.strip()):
            raise CorpusError(f"corpus entry '{raw['name']}' has an empty or non-string command")
        if command is not None and not str(raw.get("command_source") or "").strip():
            raise CorpusError(f"corpus entry '{raw['name']}' has a command but no command_source saying where it is documented")

        entries.append(
            CorpusEntry(
                name=raw["name"],
                repo_url=raw["repo_url"],
                commit_sha=raw["commit_sha"],
                entrypoint_hint=raw["entrypoint_hint"],
                selection_note=raw["selection_note"].strip(),
                stars_observed=raw.get("stars_observed"),
                dependency_files_observed=tuple(raw.get("dependency_files_observed") or ()),
                command=command.strip() if command else None,
                command_source=str(raw.get("command_source") or "").strip(),
            )
        )

    return tuple(entries)
