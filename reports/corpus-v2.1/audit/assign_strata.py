"""Assign each corpus-v2 entry to a pre-registered fix-difficulty stratum, from CONTROL and the attribution audit ONLY
(nothing from TREATMENT exists yet). Deterministic; the output's sha256 is written into METHODOLOGY before TREATMENT runs.

  D1  name-only        the missing module is a PyPI distribution the repo never declares, with no version stated anywhere
                       (audit REPO_UNDECLARED, not an internal module, no README version for it, not a torch-binary-coupled package)
  D2  version / API    the fix needs a version or Python choice, or a binary-compatible build: audit ENV_ROT, or REPO_UNDECLARED with a
                       version stated in the README prose for that module, or a torch-coupled binary package (torch-sparse/scatter/...)
  D3  platform         needs a GPU / Docker / hardware the sandbox does not have (audit PLATFORM_REQUIRED): not expected to be fixable
  D4  build / code     the repo's own module or a documented build step is missing (audit internal_module), or the record needs a manual read
  --  not stratified   PASS (nothing to fix) and INFRA (NOT_MEASURED)

  backend/.venv/Scripts/python.exe reports/corpus-v2.1/audit/assign_strata.py
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "strata.json"
TORCH_BINARY = {"torch_sparse", "torch_scatter", "torch_cluster", "torch_spline_conv", "torch_geometric", "apex", "mmcv"}


def states_version(text: str, module: str) -> bool:
    """A version is stated FOR the module: `version 1.1.0`, `v1.2`, `==1.0`, `>=1.0`, or the module name followed by a number."""
    name = re.escape(module.lower().replace("_", "[-_ ]?"))
    return bool(re.search(r"(version|\bv)\s*\d+(\.\d+)+|[=<>~]=?\s*\d+(\.\d+)+|" + name + r"\W{0,12}\d+(\.\d+)+", text, re.I))


def stratum(row: dict) -> tuple[str, str]:
    label = row["label"]
    if label in ("PASS", "INFRA"):
        return "-", "not stratified"
    if label == "PLATFORM_REQUIRED":
        return "D3", "needs a GPU / Docker the sandbox does not provide"
    if label == "ENV_ROT":
        return "D2", "historical pins / removed API: a version or Python choice is needed"
    if label == "REPO_UNDECLARED":
        module = (row.get("module") or "").split(".")[0]
        if row.get("internal_module"):
            return "D4", "the repo's own module / a documented build step"
        if module in TORCH_BINARY:
            return "D2", "a torch-coupled binary package: the build must match the torch in use"
        if any(states_version(m["text"], module) for m in row.get("readme_mentions", [])):
            return "D2", "the README states a version for it"
        return "D1", "a missing package with no version stated anywhere: add it by name"
    return "D4", f"label {label}: manual read"


def main() -> int:
    audit = json.loads((HERE / "audit_attribution.json").read_text(encoding="utf-8"))
    rows = []
    for r in audit["rows"]:
        s, why = stratum(r)
        rows.append({"id": r["id"], "name": r["name"], "stratum": s, "audit_label": r["label"], "why": why})
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["stratum"]] = counts.get(r["stratum"], 0) + 1
    doc = {"rule": __doc__.split("\n\n")[1] if "\n\n" in __doc__ else "", "source": "CONTROL harness-v1.3.2 + audit_attribution.json; no TREATMENT data",
           "counts": dict(sorted(counts.items())), "entries": rows}
    text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"strata.json sha256 {hashlib.sha256(text.encode('utf-8')).hexdigest()}  counts {doc['counts']}")
    for r in rows:
        print(r["id"], r["name"][:34].ljust(34), r["stratum"], r["audit_label"], "|", r["why"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
