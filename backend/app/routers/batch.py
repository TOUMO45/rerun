"""§7 / §8 S4: the Batch Lab. Loads the precomputed, committed
`batch_results.json`. §7 is explicit: "Never render a zero or a placeholder
if batch_results.json is missing — fail loudly in the UI instead." This
router enforces that at the API boundary — a missing or malformed file is a
502, never a quietly-empty 200.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.config import get_settings

router = APIRouter()


class BatchResultsUnavailable(RuntimeError):
    pass


def load_batch_results(path: str | Path | None = None) -> dict:
    settings = get_settings()
    resolved = Path(path if path is not None else settings.batch_results_path)
    if not resolved.is_file():
        raise BatchResultsUnavailable(f"batch_results.json not found at '{resolved}' — Batch Lab has not been run yet")
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BatchResultsUnavailable(f"batch_results.json at '{resolved}' is not valid JSON: {exc}") from exc

    required = {"repos", "recovery_rate", "n"}
    missing = required - data.keys()
    if missing:
        raise BatchResultsUnavailable(f"batch_results.json is missing required field(s): {sorted(missing)}")
    if data["n"] != len(data["repos"]):
        raise BatchResultsUnavailable(
            f"batch_results.json is internally inconsistent: n={data['n']} but "
            f"{len(data['repos'])} repo entries are present"
        )
    return data


@router.get("/batch/results")
def get_batch_results() -> dict:
    try:
        return load_batch_results()
    except BatchResultsUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
