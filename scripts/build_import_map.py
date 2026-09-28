"""Build RERUN's import-name -> PyPI-distribution table (harness-v1.1, fix b).

No hand-added entries. Three cited sources, each verified against a pinned
sha256 before use:

  1. pipreqs 0.5.0 `pipreqs/mapping` — hand-curated import:distribution table
     (Apache-2.0). Vendored with its license: backend/app/data/import_names/.
  2. pigar 2.2.0 `pigar/.db.sqlite3` — PyPI-derived table of which
     distributions provide which top-level modules (BSD-3-Clause). Used at
     build time only (39.8 MB wheel, not vendored).
  3. hugovk/top-pypi-packages (top-pypi-packages.min.json, the 15,000
     most-downloaded PyPI projects). No license is declared, so the file is
     NOT redistributed; it is used at build time only and cited by URL,
     date and sha256.

Rule, for an import name M (hardware/CUDA-variant distributions — see
HARDWARE_VARIANT_RE — are never candidates, from any source):
  a. pipreqs has M              -> its distribution;
  b. else the most-downloaded project among {M itself} + pigar's providers
     of M, restricted to the top-downloads list (never an unranked
     candidate — pigar's lists include squatters: absl -> 'mis-modulos');
  c. else M is left unchanged (not in the table).
Only rows where the chosen distribution differs from M (PEP 503) are written,
as [distribution, source, confidence]. confidence = "low" for a pigar+rank row
when a project named M itself provides M but is not ranked (we chose a
differently named, more-downloaded project over a same-named one — e.g.
clip -> openai-clip); "normal" otherwise.

Usage (repo root):
  backend/.venv/Scripts/python.exe scripts/build_import_map.py \
      --pipreqs-wheel <pipreqs-0.5.0-py3-none-any.whl> \
      --pigar-wheel <pigar-2.2.0-py3-none-any.whl> \
      --top <top-pypi-packages.min.json>
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sqlite3
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "backend" / "app" / "data" / "import_names"

SOURCES = {
    "pipreqs": {
        "file": "pipreqs-0.5.0-py3-none-any.whl",
        "url": "https://files.pythonhosted.org/packages/36/38/cc1343c3a63655e18328e51e00c6e6851be648f1b8babffc5131f1b9f226/pipreqs-0.5.0-py3-none-any.whl",
        "sha256": "0809f6217028e35785f80e90217e18043e58c99ba28175e28320f9074dd03874",
        "member": "pipreqs/mapping",
        "license": "Apache-2.0",
        "project": "https://github.com/bndr/pipreqs",
    },
    "pigar": {
        "file": "pigar-2.2.0-py3-none-any.whl",
        "url": "https://files.pythonhosted.org/packages/e0/3c/7c804834720b807f3ed0654636d923da19c520a4eebe6c50d70cefc2cb66/pigar-2.2.0-py3-none-any.whl",
        "sha256": "73ba65974dc63e7bb68f81f753642b61d93cbd1aafc2a902aaaaa834a85d07d5",
        "member": "pigar/.db.sqlite3",
        "license": "BSD-3-Clause",
        "project": "https://github.com/damnever/pigar",
    },
    "top_pypi_packages": {
        "file": "top-pypi-packages.min.json",
        "url": "https://hugovk.dev/top-pypi-packages/top-pypi-packages.min.json",
        "sha256": "9f7d002b3d0972f798e66d0de29921d6fafa1c67368b0a7e3ac34449de2e0a6c",
        "license": "none declared — used at build time only, not redistributed",
        "project": "https://github.com/hugovk/top-pypi-packages",
    },
}


# Hardware/accelerator-specific builds are never chosen automatically: the
# sandbox is CPU-only and the choice of build is the repository's, not ours.
HARDWARE_VARIANT_RE = re.compile(
    r"(^|-)(cuda\d*[a-z0-9]*|cu\d{2,3}|gpu|cpu|rocm\d*|tpu|xpu|metal|directml|mkl|aarch64|arm64|armv7l?|jetson)(-|$)"
    r"|^cupy(-|$)|^nvidia-|^jax-cuda|^jaxlib-"
)


def is_hardware_variant(dist: str) -> bool:
    return bool(HARDWARE_VARIANT_RE.search(norm(dist)))


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _verified(path: Path, key: str) -> bytes:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SOURCES[key]["sha256"]:
        raise SystemExit(f"{key}: sha256 {digest} != pinned {SOURCES[key]['sha256']} — refusing to build")
    return data


def build(pipreqs_wheel: Path, pigar_wheel: Path, top_json: Path) -> dict:
    with zipfile.ZipFile(pipreqs_wheel) as z:
        _verified(pipreqs_wheel, "pipreqs")
        mapping_text = z.read(SOURCES["pipreqs"]["member"]).decode("utf-8")
        license_text = z.read("pipreqs-0.5.0.dist-info/LICENSE").decode("utf-8")
    curated: dict[str, str] = {}
    for line in mapping_text.splitlines():
        if ":" in line.strip():
            module, dist = line.strip().split(":", 1)
            curated.setdefault(module, dist)

    _verified(pigar_wheel, "pigar")
    providers: dict[str, set[str]] = collections.defaultdict(set)
    with zipfile.ZipFile(pigar_wheel) as z, tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "pigar.sqlite3"
        db.write_bytes(z.read(SOURCES["pigar"]["member"]))
        con = sqlite3.connect(db)
        for module, dist in con.execute(
            "SELECT t.name, d.name FROM top_level_module_names t JOIN distributions d ON d.id = t.distribution_id"
        ):
            providers[module].add(norm(dist))
        con.close()

    top_data = json.loads(_verified(top_json, "top_pypi_packages"))
    downloads = {norm(r["project"]): int(r["download_count"]) for r in top_data["rows"]}

    rows: dict[str, list[str]] = {}
    excluded_hardware = 0
    for module in sorted(set(providers) | set(curated)):
        confidence = "normal"
        if module in curated and not is_hardware_variant(curated[module]):
            dist, source = norm(curated[module]), "pipreqs"
        else:
            candidates = providers.get(module, set()) | {norm(module)}
            pool = {c for c in candidates if c in downloads and not is_hardware_variant(c)}
            excluded_hardware += any(c in downloads and is_hardware_variant(c) for c in candidates)
            if not pool:
                continue
            dist, source = max(pool, key=lambda c: (downloads[c], c)), "pigar+rank"
            if dist != norm(module) and norm(module) in providers.get(module, set()) and norm(module) not in downloads:
                confidence = "low"
        if dist != norm(module):
            rows[module] = [dist, source, confidence]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "pipreqs_mapping").write_text(mapping_text, encoding="utf-8", newline="\n")
    (OUT_DIR / "pipreqs_LICENSE").write_text(license_text, encoding="utf-8", newline="\n")
    table = {
        "description": "Import name -> PyPI distribution (only where they differ). Built by scripts/build_import_map.py; "
        "do not edit by hand.",
        "rule": [
            "pipreqs curated entry, if any",
            "hardware/CUDA-variant distributions (hardware_variant_rule) are never candidates",
            "else the most-downloaded of {the import name itself} + pigar's providers, restricted to top-pypi-packages",
            "confidence 'low': a same-named project provides the import but is unranked, and a differently named one was chosen",
            "else not in the table (callers keep the import name unchanged)",
        ],
        "sources": {k: {kk: vv for kk, vv in v.items() if kk != "member"} for k, v in SOURCES.items()},
        "top_pypi_packages_last_update": top_data.get("last_update"),
        "counts": dict(collections.Counter(src for _, src, _ in rows.values())),
        "low_confidence": sum(1 for *_, conf in rows.values() if conf == "low"),
        "hardware_variant_rule": HARDWARE_VARIANT_RE.pattern,
        "names_with_a_hardware_variant_candidate_excluded": excluded_hardware,
        "rows": rows,
    }
    (OUT_DIR / "import_to_dist.json").write_text(
        json.dumps(table, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    return table


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pipreqs-wheel", type=Path, required=True)
    parser.add_argument("--pigar-wheel", type=Path, required=True)
    parser.add_argument("--top", type=Path, required=True)
    args = parser.parse_args()
    table = build(args.pipreqs_wheel, args.pigar_wheel, args.top)
    print(f"wrote {len(table['rows'])} rows {table['counts']}, {table['low_confidence']} low-confidence, to {OUT_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
