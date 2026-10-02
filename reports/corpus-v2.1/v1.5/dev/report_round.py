"""Write reports/dev/ROUND_N.md for one DEV round of the v1.5 dev/test protocol (METHODOLOGY D6).

    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.5/dev/report_round.py --round N [--out reports/dev/ROUND_N.md]

Reads only the DEV round records written by run_dev_round.py (runs/corpus_v2_batch/harness-v1.5.*/dev/NN_name.json) and, for the historical histogram, the records of DEV and
gate entries of every earlier version (devtest/firewall.py refuses a TEST record before it is opened). Every figure is read from a record; nothing is estimated here except what
is labelled ESTIMATED (a killed step's cost, from the record's own estimate). The BILLED line stays AWAITED until the owner gives a balance reading.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "devtest"))

import budget  # noqa: E402
import firewall  # noqa: E402
import split  # noqa: E402

RUNS_VERDICTS = ("RUNS_CLEAN", "RUNS_AFTER_REPAIR")
_CLASSIFIER = re.compile(r"^\[classifier\]\s+([A-Z_]+):")
_DETERMINISTIC = re.compile(r"^\[time-machine\](?: repair \d+ candidate \d+:)?(?: repair \d+:)? ?deterministic step:? ([A-Za-z_ \-]+?) \(matched")
_TORCH = re.compile(r"^\[runner\] torch: ")


def dev_records(runs_root: Path, round_no: int | None = None) -> dict[int, list[dict]]:
    """{round: [records]} for every DEV round on disk (the entry records, not the infra_retries); `round_no` keeps one round."""
    out: dict[int, list[dict]] = {}
    for tagdir in sorted((runs_root / "corpus_v2_batch").glob("harness-v1.5*")):
        dev = tagdir / "dev"
        files = sorted(p for p in dev.glob("[0-9][0-9]_*.json") if firewall.may_read_record(p) and firewall.entry_id_of(p) in firewall.DEV_ENTRIES)
        if not files:
            continue
        records = [json.loads(firewall.read_record_text(p)) for p in files]
        rnd = (records[0].get("batch") or {}).get("dev_round")
        if rnd is None or (round_no is not None and rnd != round_no):
            continue
        out[int(rnd)] = records
    return out


def classifier_codes(record: dict) -> list[str]:
    return [m.group(1) for e in record.get("events") or [] if (m := _CLASSIFIER.match(e.get("line") or ""))]


def final_kind(record: dict) -> str | None:
    from app.services import sustained_run

    final = sustained_run.final_run_of(record)
    return final["kind"] if final else None


def verdict_code(record: dict) -> str:
    result = record.get("result") or {}
    return result.get("taxonomy_code") or result.get("reason_code") or ""


def rules_fired(record: dict) -> list[str]:
    out = []
    for e in record.get("events") or []:
        line = e.get("line") or ""
        if (m := _DETERMINISTIC.match(line)):
            out.append(m.group(1).strip())
        elif _TORCH.match(line):
            out.append("runner torch policy")
    for a in (record.get("result") or {}).get("attempts") or []:
        if a.get("origin") == "time_machine":
            tm = a.get("time_machine") or {}
            out.append(f"time machine (era {((tm.get('era') or {}).get('date'))}, python {((tm.get('python') or {}).get('version'))}, apt {tm.get('apt_added') or []})")
    return out


def model_contribution(record: dict) -> dict:
    attempts = [a for a in (record.get("result") or {}).get("attempts") or [] if a.get("origin") == "model"]
    calls = collections.Counter((c.get("model") or "?") for c in record.get("model_calls") or [])
    final = (record.get("result") or {}).get("verdict") in RUNS_VERDICTS
    last_exec = next((a for a in reversed((record.get("result") or {}).get("attempts") or []) if a.get("exit_code") == 0), None)
    return {
        "model_calls": dict(calls),
        "attempts": len(attempts),
        "env_delta_ops": sum(len(a.get("env_delta") or []) for a in attempts),
        "patches_proposed": sum(1 for a in attempts if (a.get("diff_text") or "").strip()),
        "declined": sum(1 for a in attempts if a.get("gate_decision") == "DECLINED"),
        "rejected": sum(1 for a in attempts if a.get("gate_decision") == "REJECT"),
        "citations": sum(len(a.get("tavily_sources") or []) for a in attempts),
        "final_attempt_origin": (last_exec or {}).get("origin") if final else None,
    }


def stream_flags(record: dict) -> dict:
    ops = record.get("operations") or []
    cut = [o.get("n") for o in ops if any(((o.get("streams") or {}).get(s) or {}).get("truncated") for s in ("stdout", "stderr"))]
    biggest = max((((o.get("streams") or {}).get(s) or {}).get("bytes") or 0 for o in ops for s in ("stdout", "stderr")), default=0)
    return {"operations": len(ops), "truncated_operations": cut, "largest_stream_bytes": biggest,
            "output_truncated_verdict": "OUTPUT_TRUNCATED" in json.dumps((record.get("result") or {}).get("indeterminate_reason") or "") or verdict_code(record) == "OUTPUT_TRUNCATED"}


def cost_of(record: dict) -> dict:
    cg = record.get("cost_guard") or {}
    est = float(cg.get("estimated_sandbox_spent_usd") or 0.0)
    return {"total": float(cg.get("spent_usd") or 0.0), "estimated": est, "api_reported": float(cg.get("spent_usd") or 0.0) - est,
            "sandbox": float(cg.get("sandbox_spent_usd") or 0.0), "model": float(cg.get("model_spent_usd") or 0.0)}


def historical_histogram() -> collections.Counter:
    """Verdict codes of the historical records of DEV and gate entries, every version (TEST records are never opened)."""
    counts: collections.Counter = collections.Counter()
    for p in firewall.analysis_records(ROOT / "runs" / "corpus_v2_batch"):
        if "infra_retries" in p.parts or "harness-v1.5" in p.as_posix():
            continue
        rec = json.loads(firewall.read_record_text(p))
        verdict = (rec.get("result") or {}).get("verdict")
        if verdict:
            counts[f"{verdict} {verdict_code(rec)}".strip()] += 1
    return counts


def adds_something(rounds: dict[int, list[dict]], n: int) -> tuple[bool, str]:
    def runs(rs):
        return {(r.get("batch") or {}).get("entry_id") for r in rs if (r.get("result") or {}).get("verdict") in RUNS_VERDICTS}

    mine = runs(rounds[n])
    earlier = [runs(rs) for k, rs in sorted(rounds.items()) if k < n]
    best = max((len(s) for s in earlier), default=0)
    seen = set().union(*earlier) if earlier else set()
    new = mine - seen
    if len(mine) > best:
        return True, f"count {len(mine)} exceeds the best earlier count {best}"
    if new:
        return True, f"entries {sorted(new)} reach RUNS_* for the first time"
    return False, f"count {len(mine)} does not exceed the best earlier count {best} and no entry reaches RUNS_* for the first time"


def build_report(round_no: int, rounds: dict[int, list[dict]], *, billed: str = "AWAITED (the owner reads the account balance and reports it in chat)",
                 spend: budget.Spend | None = None, history: collections.Counter | None = None) -> str:
    records = rounds[round_no]
    tag = (records[0].get("batch") or {}).get("harness_tag")
    commit = (records[0].get("batch") or {}).get("harness_commit")
    total = sum(cost_of(r)["total"] for r in records)
    est = sum(cost_of(r)["estimated"] for r in records)
    runs = [r for r in records if (r.get("result") or {}).get("verdict") in RUNS_VERDICTS]
    kinds = collections.Counter(final_kind(r) for r in runs)
    adds, why = adds_something(rounds, round_no)
    spend = spend if spend is not None else budget.read_spend(ROOT)
    guard = budget.round_guard(spend)
    out = [f"# DEV round {round_no} — {tag}", "",
           f"Protocol: METHODOLOGY.md \"harness-v1.5 dev/test protocol\". Tag `{tag}` (commit `{commit[:12]}`), TREATMENT, the {len(split.DEV_ENTRIES)} DEV entries once each, entry cap ${budget.ENTRY_CAP_USD:.2f}. "
           "DEV entries are tuned on; this is a development signal, not a result. The TEST entries are not in this report (rule F).", "",
           f"- **DEV count (smoke level, D2): {len(runs)} of {len(records)}** entries with a RUNS_* verdict; kinds: {dict(kinds) or 'none'} (`smoke_alive` = a 60 s smoke pass that nothing has confirmed; no sustained check in DEV).",
           f"- Adds something over earlier rounds (D4): **{'yes' if adds else 'no'}** — {why}.",
           f"- Cost [API-REPORTED]: ${total - est:.4f}; [ESTIMATED] (killed steps): ${est:.4f}; round total ${total:.4f}. BILLED: {billed}.",
           f"- Ledger after this round (lower bound, D-27): ${guard.ledger_usd:.4f} (base ${budget.LEDGER_BASE_USD} + v1.5 DEV spend ${spend.total_usd:.4f}); ceiling ${budget.LEDGER_CEILING_USD:.2f}; "
           f"DEV total ${spend.total_usd:.4f} of ${budget.DEV_TOTAL_CAP_USD:.2f}. Guard for another round: {'OK' if guard.ok else 'REFUSED — ' + '; '.join(guard.reasons)}.", "",
           "## Verdict per entry", "", "| id | entry | verdict | code | kind of final run | attempts | model attempts | cost USD |", "|---|---|---|---|---|---|---|---|"]
    for r in sorted(records, key=lambda r: (r.get("batch") or {}).get("entry_id")):
        res = r.get("result") or {}
        out.append(f"| {(r.get('batch') or {}).get('entry_id')} | {(r.get('corpus_entry') or {}).get('name')} | {res.get('verdict')} | {verdict_code(r)} | {final_kind(r) or ''} | "
                   f"{len(res.get('attempts') or [])} | {model_contribution(r)['attempts']} | {cost_of(r)['total']:.4f} |")
    out += ["", "## Failure classes", "", "Baseline class = the classifier's first reading of the as-published failure; ending = the verdict and its code.", "",
            "| id | baseline class | classifier readings in order | ending |", "|---|---|---|---|"]
    base = collections.Counter()
    for r in sorted(records, key=lambda r: (r.get("batch") or {}).get("entry_id")):
        codes = classifier_codes(r)
        base[codes[0] if codes else "(none)"] += 1
        out.append(f"| {(r.get('batch') or {}).get('entry_id')} | {codes[0] if codes else '(none)'} | {' → '.join(codes[:8]) or '(none)'} | {(r.get('result') or {}).get('verdict')} {verdict_code(r)} |")
    out += ["", f"Histogram, baseline class, this round: {dict(base.most_common())}.", "",
            f"Histogram, ending (verdict code), this round: {dict(collections.Counter(f'{(r.get('result') or {}).get('verdict')} {verdict_code(r)}'.strip() for r in records).most_common())}.", "",
            f"Histogram, ending, every earlier record of the DEV and gate entries (all versions, both arms of v1.3.2): {dict((history if history is not None else historical_histogram()).most_common())}.", "",
            "## Deterministic rules that fired (no model call)", ""]
    for r in sorted(records, key=lambda r: (r.get("batch") or {}).get("entry_id")):
        fired = rules_fired(r)
        out.append(f"- #{(r.get('batch') or {}).get('entry_id')}: " + ("; ".join(fired) if fired else "none"))
    out += ["", "## What the model contributed", "", "| id | calls by model | model attempts | env-delta ops | patches proposed | declined | rejected | citations | origin of the passing attempt |", "|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(records, key=lambda r: (r.get("batch") or {}).get("entry_id")):
        m = model_contribution(r)
        out.append(f"| {(r.get('batch') or {}).get('entry_id')} | {m['model_calls']} | {m['attempts']} | {m['env_delta_ops']} | {m['patches_proposed']} | {m['declined']} | {m['rejected']} | {m['citations']} | {m['final_attempt_origin'] or ''} |")
    out += ["", "## Stream flags (D-41)", "", "| id | operations | operations with a cut stream | largest stream (bytes) | OUTPUT_TRUNCATED |", "|---|---|---|---|---|"]
    for r in sorted(records, key=lambda r: (r.get("batch") or {}).get("entry_id")):
        s = stream_flags(r)
        out.append(f"| {(r.get('batch') or {}).get('entry_id')} | {s['operations']} | {s['truncated_operations'] or 'none'} | {s['largest_stream_bytes']} | {'yes' if s['output_truncated_verdict'] else 'no'} |")
    out += ["", "## Cost per entry [API-REPORTED unless marked]", "", "| id | sandbox | model | estimated (killed step) | total |", "|---|---|---|---|---|"]
    for r in sorted(records, key=lambda r: (r.get("batch") or {}).get("entry_id")):
        c = cost_of(r)
        out.append(f"| {(r.get('batch') or {}).get('entry_id')} | {c['sandbox'] - c['estimated']:.4f} | {c['model']:.4f} | {c['estimated']:.4f} [ESTIMATED] | {c['total']:.4f} |")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--out")
    ap.add_argument("--billed", default="AWAITED (the owner reads the account balance and reports it in chat)")
    args = ap.parse_args(argv)
    rounds = dev_records(ROOT / "runs", None)
    if args.round not in rounds:
        print(f"no DEV records for round {args.round}", file=sys.stderr)
        return 2
    text = build_report(args.round, rounds, billed=args.billed)
    out = Path(args.out) if args.out else ROOT / "reports" / "dev" / f"ROUND_{args.round}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
