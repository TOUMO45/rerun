"""The DEV rounds of the v1.5 dev/test protocol (rounds 1-5, harness-v1.5.0 .. harness-v1.7.1), as tagged numbers with a pointer to their records.

    python -m phase_d.dev_rounds            # writes reports/phase-d/dev_rounds.json
    python -m phase_d.dev_rounds --check    # fails if the committed file is not what the records give

Same rules as the REPLAY (phase_d/replay.py): every value is read from a committed record blob (`git cat-file blob HEAD:<path>`, never the worktree copy,
which `core.autocrlf` rewrites), carries a tag (API-REPORTED | ESTIMATED | DERIVED) and a pointer (`ref` to one record, `sum_of` / `count_of` a list of
record ids). DEV entries are tuned on: these are development signals, not results; the protocol's primary metric is the TEST phase (METHODOLOGY,
"harness-v1.5 dev/test protocol"). A verdict is shown with its label (harness-v1.7: dependency change, RESOURCE-ADAPTED, memory hook, semantic change).
The DEV total is cross-checked against the ledger reader the round runner itself uses (reports/corpus-v2.1/v1.5/devtest/budget.read_spend)."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "phase-d" / "dev_rounds.json"  # not under replay/: build_replay owns that folder
ROUNDS = (("harness-v1.5.0", 1), ("harness-v1.5.1", 2), ("harness-v1.5.2", 3), ("harness-v1.6.0", 4), ("harness-v1.7.1", 5))
EXTRAS = "reports/corpus-v2.1/v1.5/ledger_extras.json"
RUNS = ("RUNS_CLEAN", "RUNS_AFTER_REPAIR")


class DevRoundsError(RuntimeError):
    pass


def _git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True).stdout


def _blob(rel: str) -> bytes:
    return _git("cat-file", "blob", f"HEAD:{rel}")


def _committed(prefix: str) -> list[str]:
    return sorted(p for p in _git("ls-files", "--", prefix).decode().splitlines() if p)


def _tagged(value, tag: str, **pointer) -> dict:
    if isinstance(value, float):
        value = round(value, 6)
    return {"value": value, "tag": tag, **pointer}


def _passing_origin(result: dict) -> str | None:
    """The origin of the attempt whose run passed (time_machine | model), or None for a run that did not pass or passed as published."""
    if result.get("verdict") not in RUNS:
        return None
    for attempt in reversed(result.get("attempts") or []):
        if attempt.get("exit_code") == 0 or (attempt.get("execution") or {}).get("outcome") in ("completed", "alive_at_limit"):
            return attempt.get("origin")
    return None


def build() -> dict:
    sys.path.insert(0, str(ROOT / "backend"))
    from app.services import outcome_levels  # the labels the certificate prints

    rounds, all_ids = [], []
    for tag, number in ROUNDS:
        summary_rel = f"runs/corpus_v2_batch/{tag}/dev/round_summary.json"
        summary = json.loads(_blob(summary_rel))
        if summary.get("round") != number or summary.get("tag") != tag or summary.get("complete") is not True:
            raise DevRoundsError(f"{summary_rel}: not the complete round {number} at {tag}")
        ladder_ids = {"first_error_cleared": [], "env_resolved": [], "entrypoint_runs": []}
        entries, ids, run_ids, api_ids, est_ids, smoke_ids = [], [], [], [], [], []
        api_sum = est_sum = smoke_sum = 0.0
        for rel in _committed(f"runs/corpus_v2_batch/{tag}/dev/"):
            name = rel.rsplit("/", 1)[1]
            if name.startswith("upload_smoke_") and name.endswith(".json"):  # the pre-batch upload smoke test (budget.read_spend counts it)
                smoke = json.loads(_blob(rel))
                if smoke.get("kind") == "pre-batch upload smoke test":
                    smoke_sum += sum(float(r.get("cost_usd") or 0.0) for r in smoke.get("runs") or [])
                    smoke_ids.append(f"{rel}@{hashlib.sha256(_blob(rel)).hexdigest()}")
                continue
            if not re.match(r"^\d{2}_.+\.json$", name):
                continue
            raw = _blob(rel)
            record_id = f"{tag}/dev/{name[:2]}@{hashlib.sha256(raw).hexdigest()}"
            doc = json.loads(raw)
            result, guard = doc["result"], doc.get("cost_guard") or {}
            spent, estimated = float(guard.get("spent_usd") or 0.0), float(guard.get("estimated_sandbox_spent_usd") or 0.0)
            api_sum += spent - estimated
            est_sum += estimated
            ids.append(record_id)
            (est_ids if estimated else api_ids).append(record_id)
            if result["verdict"] in RUNS:
                run_ids.append(record_id)
            levels = result.get("outcome_levels") or outcome_levels.compute(result)  # stored on harness-v1.6 records; computed from stored fields before
            for rung in ladder_ids:
                if levels.get(rung):
                    ladder_ids[rung].append(record_id)
            entries.append({"entry": int(name[:2]), "name": name[3:-5], "record": record_id,
                            "verdict": result["verdict"], "code": result.get("taxonomy_code") or None,
                            "label": outcome_levels.verdict_label(result),
                            "passing_attempt_origin": _passing_origin(result),
                            "spent_usd": _tagged(spent - estimated, "API-REPORTED", ref=record_id),
                            "estimated_usd": _tagged(estimated, "ESTIMATED", ref=record_id)})
        by_entry = {e["entry"]: e for e in summary["entries"]}
        for e in entries:  # the round summary the runner wrote must agree with the records
            s = by_entry.get(e["entry"])
            if s is None or s["verdict"] != e["verdict"]:
                raise DevRoundsError(f"{summary_rel}: entry {e['entry']} disagrees with its record")
        if len(entries) != 8:
            raise DevRoundsError(f"{tag}: {len(entries)} DEV records, expected 8")
        if abs(api_sum + est_sum - float(summary["round_spent_usd"])) > 1e-4:
            raise DevRoundsError(f"{tag}: the records sum to {api_sum + est_sum:.6f}, the round summary says {summary['round_spent_usd']}")
        all_ids += ids
        rounds.append({"round": number, "harness_tag": tag, "summary": summary_rel,
                       "entry_cap_usd": _tagged(float(summary["entry_cap_usd"]), "DERIVED", ref=summary_rel),
                       "entries_total": _tagged(len(entries), "DERIVED", count_of=ids),
                       "runs_count": _tagged(len(run_ids), "DERIVED", count_of=run_ids),
                       "ladder": {rung: _tagged(len(found), "DERIVED", count_of=found) for rung, found in ladder_ids.items()},
                       "spent_api_reported_usd": _tagged(api_sum, "API-REPORTED", sum_of=ids),
                       "spent_estimated_usd": _tagged(est_sum, "ESTIMATED", sum_of=est_ids),
                       "upload_smoke_usd": _tagged(smoke_sum, "API-REPORTED", sum_of=smoke_ids),
                       "entries": sorted(entries, key=lambda e: e["entry"])})
    extras = json.loads(_blob(EXTRAS))["items"]
    extras_api = sum(float(r["usd"]) for r in extras if not r.get("estimated"))
    extras_est = sum(float(r["usd"]) for r in extras if r.get("estimated"))
    rounds_total = sum(r["spent_api_reported_usd"]["value"] + r["spent_estimated_usd"]["value"] + r["upload_smoke_usd"]["value"] for r in rounds)
    dev_total = rounds_total + extras_api + extras_est
    sys.path.insert(0, str(ROOT / "reports" / "corpus-v2.1" / "v1.5" / "devtest"))
    import budget  # the round runner's own ledger reader

    ledger_dev = budget.read_spend(ROOT).total_usd
    if abs(ledger_dev - dev_total) > 1e-4:
        raise DevRoundsError(f"DEV total {dev_total:.6f} from the records disagrees with the round runner's ledger reader {ledger_dev:.6f}")
    best_before = max(r["runs_count"]["value"] for r in rounds[:-1])
    test = _test_phase()
    return {"kind": "DEV rounds of the harness-v1.5 dev/test protocol: tuned-on entries, smoke level (60 s); a development signal, not a result",
            "primary_metric": "the TEST phase (8 entries never tuned on, confirmed by a 600 s sustained check or completion): see `test`",
            "rounds": rounds,
            "test": test,
            "ledger_with_test_usd": _tagged(float(budget.LEDGER_BASE_USD) + dev_total + test["total_usd"]["value"], "DERIVED",
                                            ref="ledger_usd + test.total_usd"),
            "last_round_adds_nothing": _tagged(rounds[-1]["runs_count"]["value"] <= best_before, "DERIVED", ref="METHODOLOGY.md D4"),
            "extras_api_reported_usd": _tagged(extras_api, "API-REPORTED", ref=EXTRAS),
            "extras_estimated_usd": _tagged(extras_est, "ESTIMATED", ref=EXTRAS),
            "dev_total_usd": _tagged(dev_total, "DERIVED", sum_of=[*all_ids, EXTRAS]),
            "ledger_base_usd": _tagged(float(budget.LEDGER_BASE_USD), "DERIVED", ref="reports/corpus-v2.1/v1.5/devtest/budget.py LEDGER_BASE_USD"),
            "ledger_usd": _tagged(float(budget.LEDGER_BASE_USD) + dev_total, "DERIVED", ref="reports/corpus-v2.1/v1.5/devtest/budget.py read_spend")}


TEST_TAG = "harness-v1.5-final"
# The D-46 audit (reports/dev/TEST_RESULT.md; reports/corpus-v2.1/candidate_v1.3.3_defects.md), decided before the TEST result was read: an entry confirmed
# under rule (i) whose run did nothing. #18: the stored stderr SHA-256 equals that of the 154-byte `ModuleNotFoundError: No module named 'decorator'`
# traceback, and `| bash` exited 0. The pre-registered count is not changed; this is reported beside it.
D46_STDERR_SHA256 = {18: "5c4c19a43604794b1bb52f532b020f44f6a05982f8c0c45865800ffa8ecc1164"}


def _test_phase() -> dict:
    base = f"runs/corpus_v2_batch/{TEST_TAG}/test/"
    result_rel = base + "test_result.json"
    result = json.loads(_blob(result_rel))
    ids, confirmed_ids, runs_ids, api_ids, est_ids, smoke_ids, sustained_ids = {}, [], [], [], [], [], []
    api_sum = est_sum = smoke_sum = sustained_api = sustained_est = 0.0
    for rel in _committed(base):
        name = rel.rsplit("/", 1)[1]
        raw = _blob(rel)
        if re.match(r"^\d{2}_.+\.json$", name):
            doc = json.loads(raw)
            rid = f"{TEST_TAG}/test/{name[:2]}@{hashlib.sha256(raw).hexdigest()}"
            ids[int(name[:2])] = (rid, doc)
            guard = doc.get("cost_guard") or {}
            spent, est = float(guard.get("spent_usd") or 0.0), float(guard.get("estimated_sandbox_spent_usd") or 0.0)
            api_sum += spent - est
            est_sum += est
            (est_ids if est else api_ids).append(rid)
        elif name.startswith("sustained_"):
            doc = json.loads(raw)
            sustained_api += float(doc.get("cost_usd") or 0.0)
            sustained_est += float(doc.get("cost_estimated_usd") or 0.0)
            sustained_ids.append(f"{rel}@{hashlib.sha256(raw).hexdigest()}")
        elif name.startswith("upload_smoke_"):
            doc = json.loads(raw)
            smoke_sum += sum(float(r.get("cost_usd") or 0.0) for r in doc.get("runs") or [])
            smoke_ids.append(f"{rel}@{hashlib.sha256(raw).hexdigest()}")
    if len(ids) != result["ran"] or len(ids) != 8:
        raise DevRoundsError(f"{base}: {len(ids)} TEST records, the result says {result['ran']}")
    for row in result["rows"]:
        rid, doc = ids[row["entry"]]
        if doc["result"]["verdict"] != row["verdict"]:
            raise DevRoundsError(f"TEST entry {row['entry']}: the result disagrees with its record")
        if row["verdict"] in RUNS:
            runs_ids.append(rid)
        if row["confirmed"]:
            confirmed_ids.append(rid)
    if len(confirmed_ids) != result["confirmed_count"]:
        raise DevRoundsError("the confirmed count disagrees with the rows")
    false_positive = []
    for entry, sha in D46_STDERR_SHA256.items():
        rid, doc = ids[entry]
        stored = (doc["operations"][0].get("streams") or {}).get("stderr", {}).get("sha256")
        if stored != sha:
            raise DevRoundsError(f"TEST #{entry}: the stored stderr hash is not the audited one")
        false_positive.append(rid)
    ran_ids = [r for r in confirmed_ids if r not in false_positive]
    total = api_sum + est_sum + smoke_sum + sustained_api + sustained_est
    return {"harness_tag": TEST_TAG, "result": result_rel,
            "entries_total": _tagged(len(ids), "DERIVED", count_of=[ids[k][0] for k in sorted(ids)]),
            "runs_count": _tagged(len(runs_ids), "DERIVED", count_of=runs_ids),
            "confirmed_count": _tagged(len(confirmed_ids), "DERIVED", count_of=confirmed_ids),
            "target": _tagged(int(result["target"]), "DERIVED", ref=result_rel),
            "confirmed_false_positive_d46": _tagged(len(false_positive), "DERIVED", count_of=false_positive),
            "confirmed_that_ran": _tagged(len(ran_ids), "DERIVED", count_of=ran_ids),
            "entries_api_reported_usd": _tagged(api_sum, "API-REPORTED", sum_of=api_ids),
            "entries_estimated_usd": _tagged(est_sum, "ESTIMATED", sum_of=est_ids),
            "sustained_api_reported_usd": _tagged(sustained_api, "API-REPORTED", sum_of=sustained_ids),
            "sustained_estimated_usd": _tagged(sustained_est, "ESTIMATED", sum_of=sustained_ids),
            "upload_smoke_usd": _tagged(smoke_sum, "API-REPORTED", sum_of=smoke_ids),
            "total_usd": _tagged(total, "DERIVED", sum_of=[*api_ids, *est_ids, *sustained_ids, *smoke_ids])}


def render(doc: dict) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    text = render(build())
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
        if current.replace("\r\n", "\n") != text:
            print(f"{OUT.relative_to(ROOT)} is not what the records give: rebuild it", file=sys.stderr)
            return 1
        print(f"{OUT.relative_to(ROOT)}: matches the records")
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
