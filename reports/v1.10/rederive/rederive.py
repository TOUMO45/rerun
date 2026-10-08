"""harness-v1.10 pass, task 4 (offline): re-derive every committed RAN record under the v1.10 STATIC checks and list any certified run the checks would now refuse. POST-HOC; zero spend.

    backend/.venv/Scripts/python.exe reports/v1.10/rederive/rederive.py [--write]

RAN = a record whose verdict is RUNS_* in reports/v1.9/counterfactual/facts.json (83 entry-runs: 20 of them RUNS_*). For each: the model patches the loop ADOPTED (`chosen`, or a single-candidate round's model
attempt) are applied in order to the repository at the record's commit (the object store of .cache/planted_repos when the repository is one of the seven; otherwise the record is listed as "not
re-derived: repository not cached") and judged by behaviour.candidate_findings exactly as `_behaviour_static` does (the file before the patch, the file after, the command before and after the environment change).
What this cannot do, said once: the trace half (failure site reached, exit origin) needs a run; nothing in an old record can answer it, so no old run is re-judged by it. A record whose success came from the
deterministic rules alone (no adopted model patch, no adopted environment change) is unaffected by construction and is listed as such.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
from app.services import behaviour, tamper_gate  # noqa: E402

CHECKOUTS = ROOT / ".cache" / "planted_repos"


def git_show(repo: Path, sha: str, rel: str) -> str | None:
    done = subprocess.run(["git", "-C", str(repo), "show", f"{sha}:{rel}"], capture_output=True)
    return done.stdout.decode("utf-8", "replace").replace("\r\n", "\n") if done.returncode == 0 else None


def adopted_attempts(result: dict) -> list[dict]:
    out = []
    for a in result.get("attempts", []):
        if a.get("origin") != "model" or a.get("gate_decision") != "PASS":
            continue
        if a.get("chosen") is True or (a.get("candidate") is None and a.get("exit_code") is not None):
            out.append(a)
    return out


def rederive(entry: dict) -> dict:
    record = json.loads((ROOT / entry["record"]).read_text(encoding="utf-8"))
    ce, res = record["corpus_entry"], record["result"]
    out = {"set": entry["set"], "entry": entry["entry"], "name": entry["name"], "verdict": entry["verdict"], "certified": bool(entry.get("certified")),
           "published_audit": entry.get("published_audit"), "record": entry["record"]}
    attempts = adopted_attempts(res)
    out["adopted_model_attempts"] = [{"attempt": a["attempt_number"], "candidate": a.get("candidate"), "diff_chars": len(a.get("diff_text") or ""),
                                      "env_delta": [d.get("op") for d in (a.get("env_delta") or [])]} for a in attempts]
    if not attempts:
        out["status"] = "unaffected: the success came from the deterministic rules alone (no adopted model patch, no adopted environment change)"
        out["findings"] = []
        return out
    repo = CHECKOUTS / ce["repo_url"].rsplit("github.com/", 1)[-1].replace("/", "_")
    if not repo.is_dir():
        out["status"] = "not re-derived: repository not cached"
        out["findings"] = None
        return out
    sha = ce["commit_sha"]
    found: list[dict] = []
    state: dict[str, str] = {}  # the files as the loop had them when the next adopted patch came: earlier adopted patches applied
    for a in attempts:
        diff = a.get("diff_text") or ""
        command = res.get("build_plan", {}).get("execute_command") if isinstance(res.get("build_plan"), dict) else ce.get("command")
        env_changes = [d for d in (a.get("env_delta") or []) if d.get("op") == "command"]
        cmd_after = env_changes[-1].get("command") if env_changes else command
        if diff:
            prepared = tamper_gate.prepare_patch(diff)
            originals = {p: state.get(p, git_show(repo, sha, p)) for p in prepared.paths}
            originals = {p: t for p, t in originals.items() if t is not None}
            news = tamper_gate.patched_sources(diff, originals)
            findings = behaviour.candidate_findings(originals, news, command_before=command, command_after=cmd_after)
            state.update(news)
        else:
            findings = behaviour.candidate_findings({}, {}, command_before=command, command_after=cmd_after)
        found += [{"attempt": a["attempt_number"], **f.as_dict()} for f in findings]
    out["status"] = "would be refused by the static checks" if found else "not refused by the static checks"
    out["findings"] = found
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    facts = json.loads((ROOT / "reports/v1.9/counterfactual/facts.json").read_text(encoding="utf-8"))
    rows = [rederive(e) for e in facts["entry_runs"] if str(e["verdict"]).startswith("RUNS_")]
    for r in rows:
        print(f"{r['set']:16} {r['entry']:>3} {r['name'][:34]:34} {r['verdict']:18} {'certified' if r['certified'] else 'struck/uncertified':18} {r['status']}")
        for f in (r["findings"] or [])[:4]:
            print(f"        {f['reason']}: {f['detail'][:130]}")
    summary = {"records": len(rows), "certified": sum(1 for r in rows if r["certified"]),
               "unaffected_by_construction": sum(1 for r in rows if r["status"].startswith("unaffected")),
               "would_be_refused": [f"{r['set']} {r['entry']} {r['name']}" for r in rows if r["status"].startswith("would be refused")],
               "certified_that_would_be_refused": [f"{r['set']} {r['entry']} {r['name']}" for r in rows if r["status"].startswith("would be refused") and r["certified"]],
               "not_re_derived": [f"{r['set']} {r['entry']} {r['name']}" for r in rows if r["status"].startswith("not re-derived")]}
    print(json.dumps(summary, indent=1))
    if args.write:
        out = Path(__file__).resolve().parent / "rederive.json"
        out.write_text(json.dumps({"label": "post-hoc, offline, zero spend; static half only", "summary": summary, "rows": rows}, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
