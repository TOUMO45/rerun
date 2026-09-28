"""Import name -> PyPI distribution name (harness-v1.1, fix b).

One lookup for every place RERUN turns an import into something pip or uv
can install. Backed by backend/app/data/import_names/import_to_dist.json,
built by scripts/build_import_map.py from three cited sources (pipreqs's
curated mapping, pigar's PyPI-derived provider table, PyPI download
rankings) — no hand-added entries. A name that isn't in the table is
returned unchanged, as before. Hardware/CUDA-variant distributions are
excluded from auto-mapping when the table is built (see the build script).

Found by corpus-v1 entry #1 on harness-v1: the time machine asked the
resolver for `absl` (the import) instead of `absl-py`, and the era lock failed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

TABLE_PATH = Path(__file__).resolve().parents[1] / "data" / "import_names" / "import_to_dist.json"


@dataclass(frozen=True)
class ImportMapping:
    module: str
    distribution: str
    source: str  # "pipreqs" | "pigar+rank"
    confidence: str  # "normal" | "low"

    def as_dict(self) -> dict:
        return {"import": self.module, "distribution": self.distribution, "source": self.source, "confidence": self.confidence}


@lru_cache(maxsize=1)
def _rows() -> dict[str, list[str]]:
    return json.loads(TABLE_PATH.read_text(encoding="utf-8"))["rows"]


def mapping_for(module: str) -> ImportMapping | None:
    """The table's mapping for top-level `module` (dotted names use their
    first component), or None when the name is used unchanged."""
    top = module.split(".")[0]
    row = _rows().get(top)
    if not row:
        return None
    return ImportMapping(top, row[0], row[1], row[2] if len(row) > 2 else "normal")


def dist_for_import(module: str) -> str:
    found = mapping_for(module)
    return found.distribution if found else module.split(".")[0]
