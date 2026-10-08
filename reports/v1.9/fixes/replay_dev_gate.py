"""harness-v1.9, task 3: replay every recorded DEV model patch through the harness-v1.9 gate (offline, zero spend), to see whether the new rule
(SKIPPED_MISSING_INPUT) or the D-55 exemption changes a decision on a real patch.

    backend/.venv/Scripts/python.exe reports/v1.9/fixes/replay_dev_gate.py [--write]

DEV only (the five DEV rounds, runs/corpus_v2_batch/harness-v1.5.0 ... v1.7.1/dev): the fixes may be developed on DEV and on the planted corpus's dev half,
never on a held-out record. Each patch is checked against the repository at its recorded commit (.cache/dev_repos); a later-round patch was written against a
checkout that may already carry an adopted earlier patch, so its reconstruction can differ from what the run saw: the script reports, per patch, the recorded
decision, the harness-v1.9 decision and the rules, and lists every patch whose decision changes, with its diff, so each change can be read.
"""
from __future__ import annotations

import argparse
import ast
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import tamper_gate  # noqa: E402

REPOS = ROOT / ".cache" / "dev_repos"
DEV = [f"runs/corpus_v2_batch/{t}/dev" for t in ("harness-v1.5.0", "harness-v1.5.1", "harness-v1.5.2", "harness-v1.6.0", "harness-v1.7.1")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    rows, changed = [], []
    for d in DEV:
        for f in sorted(glob.glob(str(ROOT / d / "*.json"))):
            doc = json.loads(Path(f).read_text(encoding="utf-8"))
            res = doc.get("result") if isinstance(doc, dict) else None
            if not isinstance(res, dict) or not res.get("attempts"):
                continue
            cert = doc.get("certificate") or {}
            repo = REPOS / cert["repo_url"].rstrip("/").split("github.com/")[1].replace("/", "_")
            command = (cert.get("baseline") or {}).get("execute_command") or (cert.get("build_plan") or {}).get("execute_command")
            for a in res["attempts"]:
                diff = a.get("diff_text") or ""
                if not diff.strip() or (a.get("attempt_number") or 0) < 1:
                    continue
                prepared = tamper_gate.prepare_patch(diff)
                originals = {p: (repo / p).read_text(encoding="utf-8", errors="replace") for p in prepared.paths if (repo / p).is_file()}
                touched = "\n".join(originals.values())
                result = tamper_gate.check_patch(diff, originals, eval_call_names=tamper_gate.heuristic_eval_call_names(touched),
                                                 model_call_names=tamper_gate.heuristic_model_call_names(touched), repo_root=repo,
                                                 documented_files=tamper_gate.documented_scripts(command))
                v = list(result.violations) or list(tamper_gate.py_compile_violations(result.canonical_diff or diff, originals))
                recorded = a.get("gate_decision")
                raw = a.get("gate_violations")
                if isinstance(raw, str):
                    try:
                        raw = ast.literal_eval(raw)
                    except (ValueError, SyntaxError):
                        raw = []
                row = {"record": Path(f).relative_to(ROOT).as_posix(), "attempt": a.get("attempt_number"), "candidate": a.get("candidate"),
                       "recorded": recorded, "recorded_rules": sorted({x.get("rule") for x in (raw or []) if isinstance(x, dict)}),
                       "v19": "REJECT" if v else "PASS", "v19_rules": sorted({x.rule for x in v}),
                       "new_rule_fired": any(x.rule == tamper_gate.GateRule.SKIPPED_MISSING_INPUT for x in v),
                       "exit_code": a.get("exit_code")}
                rows.append(row)
                if row["new_rule_fired"] or (recorded in ("PASS", "REJECT") and row["v19"] != recorded):
                    changed.append({**row, "diff": diff[:1500]})
    print(f"model patches replayed: {len(rows)}; new rule fired on {sum(r['new_rule_fired'] for r in rows)}; decisions that differ from the record: "
          f"{sum(1 for r in rows if r['recorded'] in ('PASS', 'REJECT') and r['v19'] != r['recorded'])}")
    for c in changed:
        print(f"--- {c['record']} attempt {c['attempt']} cand {c['candidate']}: recorded {c['recorded']} {c['recorded_rules']} -> v1.9 {c['v19']} {c['v19_rules']} "
              f"(exit {c['exit_code']})")
        print(c["diff"][:700])
    if args.write:
        (Path(__file__).parent / "replay_dev_gate.json").write_text(json.dumps({"rows": rows, "changed": changed}, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
