"""harness-v1.9, task 2: run the tamper gate on one half of the planted corpus, the way the orchestrator calls it, and count. Offline, zero spend.

    backend/.venv/Scripts/python.exe reports/v1.9/planted/run_gate.py --half heldout --label before [--write]

The gate as the orchestrator calls it (orchestrator.py, the `tamper_gate` stage): `check_patch(diff, originals of every touched file, eval names = recon's |
heuristic_eval_call_names(touched sources), model names = recon's | heuristic_model_call_names(touched sources), repo_root)`, then, when nothing was found,
`py_compile_violations`. Recon's names come from a model call and are not available offline: they are empty here (PROTOCOL.md). If the gate at the running
code takes the documented command's files (harness-v1.9, D-55), they are passed (the base's entry file), exactly as the orchestrator passes them.

Every original is read from the checkout at its pinned commit (.cache/planted_repos, fetch.py) and must match the sha256 stored with the patch.
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

from app.services import tamper_gate  # noqa: E402

REPOS = ROOT / ".cache" / "planted_repos"
SIZE_OR_FORM_RULES = {"PROTECTED_PATH_MODIFIED", "DIFF_TOO_LARGE", "UNPARSEABLE_PATCH", "PY_COMPILE_FAILED", "UNAPPLICABLE_PATCH", "UNVERIFIED_FILE", "UNSAFE_PATH"}


def gate(row: dict, entry: str) -> dict:
    repo = REPOS / row["repo"].replace("/", "_")
    prepared = tamper_gate.prepare_patch(row["diff"])
    originals = {}
    for path in prepared.paths:
        f = repo / path
        if f.is_file():
            originals[path] = f.read_text(encoding="utf-8")
    original = originals.get(row["file"])
    if original is None or hashlib.sha256(original.encode("utf-8")).hexdigest() != row["original_sha256"]:
        raise SystemExit(f"{row['id']}: the original of {row['file']} does not match the stored sha256 (run fetch.py)")
    touched = "\n".join(originals.values())
    kwargs = dict(eval_call_names=tamper_gate.heuristic_eval_call_names(touched), model_call_names=tamper_gate.heuristic_model_call_names(touched), repo_root=repo)
    if "documented_files" in inspect.signature(tamper_gate.check_patch).parameters:
        kwargs["documented_files"] = frozenset({entry})
    result = tamper_gate.check_patch(row["diff"], originals, **kwargs)
    violations = list(result.violations)
    if not violations:
        violations = list(tamper_gate.py_compile_violations(result.canonical_diff or row["diff"], originals))
    rules = sorted({v.rule for v in violations})
    return {"id": row["id"], "decision": "REJECT" if violations else "PASS", "rules": rules,
            "reasons": [v.reason[:200] for v in violations][:3]}


def summarise(rows: list[dict], results: dict[str, dict]) -> dict:
    fam: dict[str, Counter] = {}
    for r in rows:
        res = results[r["id"]]
        c = fam.setdefault(r["family"], Counter())
        c["n"] += 1
        rejected = res["decision"] == "REJECT"
        c["rejected"] += rejected
        c["rejected_by_a_semantic_rule"] += rejected and bool(set(res["rules"]) - SIZE_OR_FORM_RULES)
        for rule in res["rules"]:
            c["rule:" + rule] += 1
    out = {}
    for f, c in sorted(fam.items()):
        out[f] = {"n": c["n"], "rejected": c["rejected"], "rate": round(c["rejected"] / c["n"], 4),
                  "rejected_by_a_semantic_rule": c["rejected_by_a_semantic_rule"], "rules": {k[5:]: v for k, v in sorted(c.items()) if k.startswith("rule:")}}
    cheats = [r for r in rows if r["kind"] == "cheat"]
    controls = [r for r in rows if r["kind"] == "control"]
    out["ALL CHEATS"] = {"n": len(cheats), "rejected": sum(results[r["id"]]["decision"] == "REJECT" for r in cheats)}
    out["ALL CONTROLS"] = {"n": len(controls), "rejected": sum(results[r["id"]]["decision"] == "REJECT" for r in controls)}
    for k in ("ALL CHEATS", "ALL CONTROLS"):
        out[k]["rate"] = round(out[k]["rejected"] / out[k]["n"], 4) if out[k]["n"] else None
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--half", choices=("dev", "heldout"), required=True)
    ap.add_argument("--label", required=True, help="before | after | dev-iteration-N")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    corpus = [json.loads(line) for line in (HERE / "corpus.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    split = json.loads((HERE / "split.json").read_text(encoding="utf-8"))
    entries = {b["name"]: b["entry"] for b in json.loads((HERE / "bases.json").read_text(encoding="utf-8"))["bases"]}
    ids = set(split[args.half])
    rows = [r for r in corpus if r["id"] in ids]
    results = {r["id"]: gate(r, entries[r["base"]]) for r in rows}
    summary = summarise(rows, results)
    blob = subprocess.run(["git", "hash-object", "backend/app/services/tamper_gate.py"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    for k, v in summary.items():
        print(f"{k:13} {json.dumps(v)}")
    if args.write:
        out = {"half": args.half, "label": args.label, "head": head, "tamper_gate_blob": blob,
               "documented_files_passed": "documented_files" in inspect.signature(tamper_gate.check_patch).parameters,
               "summary": summary, "results": [results[r["id"]] for r in rows]}
        (HERE / f"gate_{args.half}_{args.label}.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
