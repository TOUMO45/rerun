"""Retroactive audit of committed live-run records for the CRLF clone bug
(found 2026-09-24): until the fix, every run on this Windows host cloned
with the global `core.autocrlf=true`, so the sandbox received CRLF copies of
every text file in the repository.

A record is marked `invalidated_by: "crlf-clone-bug"` when its baseline or
final verdict may have depended on converted files:
  - the sandbox executed a shell script (or other non-Python script) from
    the repository (`bash x.sh`, `sh x.sh`, `./x`), or
  - the recorded output shows carriage-return artifacts.
Runs that executed only Python sources and pip requirement files are marked
not affected: CPython and pip both accept CRLF line endings, and the command
strings themselves are RERUN's, not repository files.

Records are annotated in place; nothing is deleted, and the embedded
certificates are untouched (their passport hashes still verify). Also tags
each record's `repair_mode` (deterministic | model_assisted).

Usage: python scripts/audit_crlf.py [runs/]
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path

FIX_NOTE = "clone fixed 2026-09-24 (core.autocrlf=false, core.eol=lf + tree integrity gate)"
# A bare "\r" is NOT evidence: progress bars (tqdm) redraw a line with a lone
# carriage return (found in the gpt-2 v4 record: 3 bare CRs from
# download_model.py, 0 CRLF pairs). Only CRLF pairs, an escaped "\r" printed
# inside an error message (e.g. "pipefail\r"), or known shell symptoms count.
CR_ARTIFACTS = re.compile(r"\r\n|\\r|invalid option name|bad interpreter", re.IGNORECASE)


def _commands(record: dict) -> list[str]:
    cert = record.get("certificate") or {}
    plan = cert.get("build_plan") or {}
    commands = [plan.get("execute_command") or "", *(plan.get("install_commands") or [])]
    baseline = cert.get("baseline") or {}
    commands += [baseline.get("execute_command") or "", *(baseline.get("install_commands") or [])]
    for line in (cert.get("full_log") or "").splitlines():
        if "build plan now:" in line or "[planner] build plan:" in line:
            commands.append(line)
    return [c for c in commands if c]


def _executed_scripts(commands: list[str]) -> list[str]:
    scripts = set()
    for command in commands:
        for match in re.finditer(r"(?:^|[\s'\"&;])(?:bash|sh)\s+([^\s'\"&;]+)", command):
            scripts.add(match.group(1))
        for match in re.finditer(r"(?:^|[\s'\"&;])(\./[^\s'\"&;]+)", command):
            scripts.add(match.group(1))
    return sorted(scripts)


def _outputs(record: dict) -> str:
    cert = record.get("certificate") or {}
    parts = [cert.get("full_log") or "", json.dumps(cert.get("baseline") or {})]
    for attempt in cert.get("diffs") or []:
        parts += [attempt.get("stdout_tail") or "", attempt.get("stderr_tail") or ""]
    return "\n".join(parts)


def repair_mode(record: dict) -> str:
    """model_assisted iff the repair model was consulted in any attempt;
    otherwise deterministic (no repair at all, or only RERUN's deterministic
    time machine). Records from before `origin` existed only had model attempts."""
    attempts = (record.get("certificate") or {}).get("diffs") or (record.get("result") or {}).get("attempts") or []
    return "model_assisted" if any(a.get("origin", "model") == "model" for a in attempts) else "deterministic"


def audit(record: dict) -> dict:
    cert = record.get("certificate") or {}
    if (cert.get("tree_integrity") or {}).get("status") == "verified":
        return {"crlf_audit": "not applicable: run after the fix, tree integrity verified"}
    if not cert or not (cert.get("build_plan") or {}).get("execute_command"):
        return {"crlf_audit": "not affected: nothing was executed in the sandbox"}
    scripts = _executed_scripts(_commands(record))
    artifacts = sorted({m.group(0) for m in CR_ARTIFACTS.finditer(_outputs(record))})
    if scripts or artifacts:
        reasons = []
        if scripts:
            reasons.append(f"executed repository script(s) {scripts} from a CRLF-converted clone")
        if artifacts:
            reasons.append(f"carriage-return artifacts in recorded output: {artifacts}")
        return {"invalidated_by": "crlf-clone-bug", "invalidation_reason": "; ".join(reasons), "crlf_audit_note": FIX_NOTE}
    return {
        "crlf_audit": (
            "not affected: only Python sources and pip requirement files were executed "
            "(CPython and pip accept CRLF); no carriage-return artifacts in the recorded output"
        )
    }


def main(argv: list[str] | None = None) -> int:
    runs_dir = Path((argv or sys.argv[1:] or ["runs"])[0])
    invalidated = []
    for path in sorted(runs_dir.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        for key in ("invalidated_by", "invalidation_reason", "crlf_audit", "crlf_audit_note"):
            record.pop(key, None)
        record.update(audit(record))
        record["repair_mode"] = repair_mode(record)
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        status = record.get("invalidated_by") or "ok"
        verdict = (record.get("result") or {}).get("verdict") or record.get("error", "")[:40]
        print(f"{path.name:32s} {verdict:20s} repair_mode={record['repair_mode']:15s} {status}"
              + (f"  <- {record['invalidation_reason']}" if record.get("invalidated_by") else ""))
        if record.get("invalidated_by"):
            invalidated.append(path.name)
    print(f"\nINVALIDATED: {len(invalidated)} {invalidated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
