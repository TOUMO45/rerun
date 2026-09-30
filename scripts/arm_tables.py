"""Read-only per-entry tables for CONTROL and TREATMENT (corpus-v2.1). Modifies nothing under runs/.

    python scripts/arm_tables.py --root runs/corpus_v2_batch/harness-v1.3.2 --out reports/corpus-v2.1/arm_tables

Columns per entry: python_version_used (+ how it was chosen), verdict, attribution, cost, and one row per repair with
its tag. Tag definitions (fixed here, applied mechanically to the stored delta):

  env_only               only a package/apt environment delta (env_delta ops add/pin/remove/apt with no shell command)
  source_patch           a non-empty unified diff in `diff_text` (applied or not; `applied` says which)
  python_version_change  the interpreter image differs from the policy choice (time-machine era lock -> python:X-slim)
  build_step             an env_delta carrying a shell `command`

Python version used = the last interpreter image the sandbox ran: the policy choice (`[python]` event), replaced by the
time-machine's era python only when its lock succeeded (`[time-machine] era ... -> python X` event).

Stop-condition checks (used by the watcher): REGRESSION on entry 18; a repair with Tavily sources whose diff touches a
tamper-gate protected path or is REJECTed by the gate; spend against the $25 cap.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PASS = ("RUNS_CLEAN", "RUNS_AFTER_REPAIR")
CAP = 25.0
CONTROL_SPENT_FOR_CAP = 4.08


def load(arm_dir: Path) -> list[dict]:
    out = []
    for f in sorted(arm_dir.glob("[0-9][0-9]_*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        d["_file"] = f.as_posix()
        d["_sha256"] = hashlib.sha256(f.read_bytes()).hexdigest()
        out.append(d)
    return out


def python_used(rec: dict) -> tuple[str, str]:
    version, how = None, ""
    for e in rec.get("events", []):
        line = e["line"]
        m = re.match(r"\[python\] python:(\d+\.\d+)-slim \((.*?)\)", line)
        if m:
            version, how = m.group(1), f"policy:{m.group(2)}"
        m = re.match(r"\[time-machine\] era \S+ \((\S+)\) -> python (\d+\.\d+)", line)
        if m:
            version, how = m.group(2), f"time-machine era lock ({m.group(1)})"
    tm = [a for a in rec["result"]["attempts"] if a.get("origin") == "time_machine"]
    if tm and not tm[0]["time_machine"]["lock"]["ok"]:
        chosen = tm[0]["time_machine"]["python"]["version"]
        how += f"; era lock FAILED (era python {chosen} computed but not used)"
    return version or "?", how or "n/a"


def tag_attempt(a: dict, default_py: str) -> tuple[list[str], bool]:
    tags: list[str] = []
    applied = a["exit_code"] is not None
    if a.get("origin") == "time_machine":
        tm = a["time_machine"]
        if tm["lock"]["ok"]:
            tags.append("env_only")
            if tm["python"]["version"] != default_py:
                tags.append("python_version_change")
        return tags, tm["lock"]["ok"]
    if a.get("diff_text"):
        tags.append("source_patch")
    deltas = a.get("env_delta") or []
    if any(d.get("command") for d in deltas):
        tags.append("build_step")
    if any(not d.get("command") for d in deltas):
        tags.append("env_only")
    return tags, applied


def delta_summary(a: dict) -> str:
    parts = []
    for d in a.get("env_delta") or []:
        parts.append(f"{d['op']} {d.get('package') or d.get('command')}{'==' + d['version'] if d.get('version') else ''}")
    if a.get("diff_text"):
        hunks = a["diff_text"].count("\n@@")
        parts.append(f"diff({hunks} hunk(s), {len(a['diff_text'])} chars)")
    if a.get("origin") == "time_machine":
        tm = a["time_machine"]
        parts.append(f"era-lock {tm['era']['date']} py{tm['python']['version']} ok={tm['lock']['ok']}")
    return "; ".join(parts) or "(nothing stored)"


def entry_row(rec: dict) -> dict:
    res, cg = rec["result"], rec.get("cost_guard") or {}
    py, how = python_used(rec)
    default_py = "3.10"
    repairs = []
    for a in res["attempts"]:
        tags, applied = tag_attempt(a, default_py)
        repairs.append({
            "attempt": a["attempt_number"], "origin": a["origin"], "tags": tags, "applied": applied,
            "gate": a["gate_decision"], "gate_violations": a["gate_violations"], "exit_code": a["exit_code"],
            "delta": delta_summary(a), "delta_stored": bool(a.get("diff_text") or a.get("env_delta") or a["origin"] == "time_machine"),
            "tavily_sources": [s if isinstance(s, str) else s.get("url", s) for s in a.get("tavily_sources") or []],
            "resolved_sources": [s.get("url") for s in a.get("resolved_sources") or []],
        })
    chain = res.get("error_chain") or []
    return {
        "id": rec["batch"]["entry_id"], "name": rec["corpus_entry"]["name"], "arm": rec["batch"]["arm"],
        "verdict": res["verdict"], "class": res.get("taxonomy_code") or res.get("reason_code") or "",
        "attributions": sorted({c["attribution"] for c in chain}), "python_version_used": py, "python_choice": how,
        "spent_usd": round(float(cg.get("spent_usd") or 0), 4), "repairs": repairs,
        "record": rec["_file"], "record_sha256": rec["_sha256"],
    }


def protected_hit(rec: dict) -> list[str]:
    sys.path.insert(0, str(ROOT / "backend"))
    from app.services.tamper_gate import DEFAULT_PROTECTED_PATTERNS, _is_protected_path  # noqa: WPS433
    hits = []
    for a in rec["result"]["attempts"]:
        paths = re.findall(r"^\+\+\+ b/(\S+)", a.get("diff_text") or "", flags=re.M)
        prot = [p for p in paths if _is_protected_path(p, DEFAULT_PROTECTED_PATTERNS)]
        rejected = a["gate_decision"] == "REJECT"
        if a.get("tavily_sources") and (prot or rejected):
            hits.append(f"entry {rec['batch']['entry_id']} attempt {a['attempt_number']}: gate={a['gate_decision']} paths={paths}")
    return hits


def stop_conditions(control: list[dict], treatment: list[dict]) -> list[str]:
    flags = []
    c18 = {r["batch"]["entry_id"]: r["result"]["verdict"] for r in control}.get(18)
    for r in treatment:
        if r["batch"]["entry_id"] == 18 and c18 in PASS and r["result"]["verdict"] not in PASS:
            flags.append(f"REGRESSION: entry 18 CONTROL {c18} -> TREATMENT {r['result']['verdict']}")
        flags += [f"TAVILY_GATE: {h}" for h in protected_hit(r)]
    spent = CONTROL_SPENT_FOR_CAP + sum(float((r.get("cost_guard") or {}).get("spent_usd") or 0) for r in treatment)
    if spent >= CAP:
        flags.append(f"CAP: total spend ${spent:.2f} >= ${CAP}")
    return flags


def render(rows: dict[str, list[dict]]) -> str:
    out = ["# corpus-v2.1 per-entry tables (generated by scripts/arm_tables.py; read-only over runs/)", ""]
    for arm, rs in rows.items():
        out += [f"## {arm.upper()} ({len(rs)}/20 records)", "",
                "| # | entry | verdict | class | attribution | python_version_used | how chosen | repairs (tag) | cost USD |",
                "|--:|---|---|---|---|--:|---|---|--:|"]
        for r in rs:
            rep = "; ".join(f"{x['attempt']}:{'+'.join(x['tags']) or 'none'}{'' if x['applied'] else '(not applied)'}"
                            for x in r["repairs"]) or "—"
            out.append(f"| {r['id']} | {r['name']} | {r['verdict']} | {r['class']} | {'/'.join(r['attributions']) or '—'} | "
                       f"{r['python_version_used']} | {r['python_choice'][:70]} | {rep} | {r['spent_usd']:.2f} |")
        out += ["", f"{arm} spend: ${sum(r['spent_usd'] for r in rs):.2f}", ""]
    out += ["## Repair deltas (TREATMENT; the stored delta is in the record named in the JSON)", "",
            "| # | attempt | origin | tags | applied | gate | delta | Tavily sources | stored |", "|--:|--:|---|---|:-:|---|---|--:|:-:|"]
    for r in rows.get("treatment", []):
        for x in r["repairs"]:
            out.append(f"| {r['id']} | {x['attempt']} | {x['origin']} | {'+'.join(x['tags']) or 'none'} | "
                       f"{'Y' if x['applied'] else 'N'} | {x['gate']} | {x['delta'][:80]} | {len(x['tavily_sources'])} | "
                       f"{'Y' if x['delta_stored'] else 'N'} |")
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--check", action="store_true", help="print stop-condition flags and treatment progress only")
    a = ap.parse_args()
    control, treatment = load(a.root / "control"), load(a.root / "treatment")
    flags = stop_conditions(control, treatment)
    if a.check:
        spent = sum(float((r.get("cost_guard") or {}).get("spent_usd") or 0) for r in treatment)
        print(f"treatment {len(treatment)}/20 spend ${spent:.2f} (+${CONTROL_SPENT_FOR_CAP} control) flags={flags or 'none'}")
        return 2 if flags else 0
    rows = {"control": [entry_row(r) for r in control], "treatment": [entry_row(r) for r in treatment]}
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.with_suffix(".md").write_text(render(rows), encoding="utf-8", newline="\n")
        a.out.with_suffix(".json").write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(render(rows))
    print("stop-condition flags:", flags or "none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
