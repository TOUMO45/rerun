"""harness-v1.10 pass: run a set of planted patches through the harness's decision procedure (gate, a REAL run, the exit-zero check, the candidate adjudicator, the final
adjudicator, the outcome labels) at a given harness tag, and record the layer that stopped each patch, or that it was adopted.

    backend/.venv/Scripts/python.exe reports/v1.10/pipeline/measure.py --set heldout --worktree <tag worktree> --tag harness-v1.9.0 --out reports/v1.10/pipeline/heldout_v190 [--go]

`--set heldout` : the spent held-out half of the planted corpus (reports/v1.9/planted), 168 patches: the gate decides first, the ones it passes go on. `--set <dir>` : a patch set
directory with a manifest (the independent set, reports/v1.10/independent). The procedure and every definition are in PROTOCOL.md, committed before any run.

Without --go nothing is spent. Resumable: a patch already in results.jsonl is not run again. After the first 10 patches the projected total is printed and, when it exceeds
--projection-limit-usd, the run stops (exit 3) so that a seeded stratified subsample can be committed before the rest runs.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common  # noqa: E402

ROOT = common.ROOT
CHECKOUTS = ROOT / ".cache" / "planted_repos"
EXPLANATION = "Change proposed to make the documented command run."  # the same text for every patch: a label must not leak through the explanation
ORDER_SEED = 20261009


# ---------------------------------------------------------------------------------------------------------------------------------- the patch sets
def load_half(half: str = "heldout") -> list[dict]:
    corpus = {json.loads(l)["id"]: json.loads(l) for l in (ROOT / "reports/v1.9/planted/corpus.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()}
    ids = json.loads((ROOT / "reports/v1.9/planted/split.json").read_text(encoding="utf-8"))[half]
    return [corpus[i] for i in sorted(ids)]


def load_dir_set(directory: Path) -> list[dict]:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    rows = []
    for m in manifest:
        diff = (directory / "patches" / f"{m['id']}.patch").read_text(encoding="utf-8")
        rows.append({**m, "diff": diff, "base": m["repo"], "style": m.get("technique", "")})
    return rows


def originals_for(row: dict, bases: dict, files: tuple[str, ...]) -> dict[str, str]:
    repo = Path(bases[row["base"]]["checkout"])
    return {p: (repo / p).read_text(encoding="utf-8") for p in files if (repo / p).is_file()}


# ---------------------------------------------------------------------------------------------------------------------------------- one patch
class Meter:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.usd = 0.0
        self.done = 0

    def add(self, usd: float) -> None:
        with self.lock:
            self.usd += usd


def gate_stage(h, row: dict, scen: dict, bases: dict, documented: dict):
    """(record, files, gate): the gate's decision, the way the orchestrator calls it; `files` = the post-patch texts when it passes."""
    out = {"id": row["id"], "base": row["base"], "kind": row["kind"], "family": row["family"], "style": row.get("style"), "population": scen["population"],
           "image": scen["image"], "cost_usd": 0.0}
    tg = h.tamper_gate
    prepared = tg.prepare_patch(row["diff"])
    originals = originals_for(row, bases, prepared.paths)
    names = "\n".join(originals.values())
    kwargs = {"documented_files": documented[row["base"]]} if hasattr(tg, "documented_scripts") else {}
    gate = tg.check_patch(row["diff"], originals, eval_call_names=tg.heuristic_eval_call_names(names), model_call_names=tg.heuristic_model_call_names(names),
                          repo_root=Path(bases[row["base"]]["checkout"]), **kwargs)
    violations = list(gate.violations) or list(tg.py_compile_violations(gate.canonical_diff or row["diff"], originals))
    out["gate"] = {"decision": "REJECT" if violations else "PASS", "rules": sorted({v.rule for v in violations})}
    if violations:
        out["outcome"] = "gate"
        return out, None, gate
    files = tg.patched_sources(gate.canonical_diff or row["diff"], originals)
    if h.behaviour is not None:
        # harness-v1.10: the static half of the behavioural checks, after the gate and before the run (orchestrator `_candidate`): the patch's own changes and the command
        command = bases[row["base"]]["command"]
        found = h.behaviour.candidate_findings(originals, files, command_before=command, command_after=command, shadow_names=shadow_names_of(h, row["base"], bases))
        out["behaviour"] = {"static": [f.as_dict() for f in found]}
        if found and SKIP_STATIC:
            out["behaviour"]["static_skipped_for_the_ablation"] = True  # a diagnostic run: the static findings are recorded and NOT acted on, so the trace layer meets the patch alone
        elif found:
            out["outcome"] = "behaviour_static"
            return out, None, gate
    return out, files, gate


_SHADOW: dict[str, frozenset] = {}


def shadow_names_of(h, base: str, bases: dict) -> frozenset:
    """The packages the base repository's files import and do not define (behaviour.external_import_roots): a file a patch adds under one of these names would shadow the installed package."""
    if base not in _SHADOW:
        repo = Path(bases[base]["checkout"])
        _SHADOW[base] = h.behaviour.external_import_roots({p.relative_to(repo).as_posix(): p.read_text(encoding="utf-8", errors="replace") for p in h.behaviour.repo_python_files(repo)})
    return _SHADOW[base]


SKIP_STATIC = False  # --ablate-static: development / ablation only; a measurement never sets it
REPLAY: dict[str, dict] = {}  # patch id -> its confirmation record (--replay-runs); only for the harness-v1.9.0 measurement, which has no tracer to install


def replayed_step(h, rec: dict, scen: dict):
    """The sandbox step of a confirmation record, rebuilt from what it stored (exit code, the 1,200-character tails the adjudicator reads, timed_out): no sandbox call, no cost."""
    run = rec["run"]
    return h.sandbox.StepResult(command=scen["command"], exit_code=run["exit_code"], stdout=run.get("stdout_tail", ""), stderr=run.get("stderr_tail", ""), elapsed_seconds=0.0,
                                cost_usd=0.0, phase="repo_run", timed_out=bool(run.get("timed_out")))


def trace_plan_for(h, row: dict, scen: dict, bases: dict, files: dict):
    """The tracer's plan for one patch, from the same inputs the orchestrator's `_trace_plan` uses: the command's entry, the failure being repaired (population A: the unpatched run's
    stderr and stdout; population B: the recorded failure text, which carries no frame), the touched files before and after, the repository's Python files, the entry's source."""
    repo = Path(bases[row["base"]]["checkout"])
    repo_files = {p.relative_to(repo).as_posix() for p in h.behaviour.repo_python_files(repo)}
    old = {p: (repo / p).read_text(encoding="utf-8") for p in files if (repo / p).is_file()}
    baseline = scen.get("baseline") or {}
    stderr = baseline.get("stderr_tail", "")
    failure_text = ((stderr if h.behaviour.has_frames(stderr) else f"{stderr}\n{baseline.get('stdout_tail', '')}") if scen["population"] == "A" else scen["failure"])
    entry = h.behaviour.entry_of(scen["command"], repo_files)
    entry_source = (repo / entry).read_text(encoding="utf-8") if entry and (repo / entry).is_file() else None
    return h.behaviour.plan_trace(command=scen["command"], failure_text=failure_text, old_sources=old, new_sources=dict(files), repo_files=repo_files, entry_source=entry_source,
                                  read_source=lambda rel: (repo / rel).read_text(encoding="utf-8", errors="replace") if (repo / rel).is_file() else None)


def process(h, row: dict, scen: dict, bases: dict, guard, model_lock: threading.Lock, meter: Meter, documented: dict) -> dict:
    out, files, gate = gate_stage(h, row, scen, bases, documented)
    if files is None:
        return out
    started = time.monotonic()
    plan = None
    if h.behaviour is not None:
        plan = trace_plan_for(h, row, scen, bases, files)
        step = common.run_on_image(h, scen["image"], scen["command"], files, extras=(h.behaviour.install_command(plan.spec_b64),), env=h.behaviour.TRACE_ENV)
        clean, reports = h.behaviour.split_report(step.stderr, plan.nonce)
        step = replace(step, stderr=clean)
        report = h.behaviour.entry_report(reports)
        found = h.behaviour.trace_findings(report, plan, succeeded=step.exit_code == 0)
        out["behaviour"]["trace"] = {"status": "ok" if report is not None else "missing", "findings": [f.as_dict() for f in found], "plan": plan.as_dict()}
    elif row["id"] in REPLAY:
        # the run of this patch was already made by the confirmation script at the same tag, on the same image, with the same overlay and launcher: it IS the run of this measurement
        step = replayed_step(h, REPLAY[row["id"]], scen)
        out["run_replayed_from"] = "reports/v1.10/independent/confirm"
    else:
        step = common.run_on_image(h, scen["image"], scen["command"], files)
    out["cost_usd"] += step.cost_usd
    out["run"] = {"exit_code": step.exit_code, "timed_out": step.timed_out, "seconds": round(step.elapsed_seconds, 2), "wall_s": round(time.monotonic() - started, 1),
                  **common.tails(step, 1200)}
    if step.exit_code == 97 and "RERUN_OVERLAY_MISMATCH" in (step.stderr or ""):
        out["outcome"] = "void"
        return out
    res = common.sandbox_result(h, step)
    execution = h.smoke_exec.execution_record(common.SMOKE_SECONDS, step.exit_code, step.stdout, step.stderr)
    out["run"]["smoke"] = execution
    finding = h.exit_zero_check.finding_of(res) or (REPLAY.get(row["id"], {}).get("audit") if row["id"] in REPLAY else None)
    if step.exit_code != 0:
        c = h.classifier.classify(step.exit_code, step.stderr, step.stdout)
        out["run"]["classification"] = {"code": c.code, "evidence": (c.evidence or "")[:200]}
        out["outcome"] = "run"  # the patch did not make the documented command pass
        return out
    if finding:
        out["audit"] = finding
        out["outcome"] = "audit"  # exit 0 overruled by the exit-zero check (D-46): not a pass
        return out
    if plan is not None and out["behaviour"]["trace"]["findings"]:
        out["outcome"] = "behaviour_trace"  # harness-v1.10: the patched run did not do what a repair does (orchestrator: the candidate does not qualify)
        return out
    # passed the run: the candidate adjudicator, with the failure being repaired
    stage = h.candidate_stage(res, execution["outcome"])
    cand = {"number": 1, "diff": gate.canonical_diff or row["diff"], "env_delta": "[]", "exit_code": 0, "outcome": execution["outcome"], "stage": stage,
            "resource_kill": False, "output_tail": f"{step.stderr[-1200:]}\n{step.stdout[-800:]}", "explanation": EXPLANATION}
    current = {"phase": "repo_run", "setup_completed": 0, "outcome": "exited", "seconds": 1.0, "exit_code": 1}
    with model_lock:
        before = guard.spent_today_usd
        adj = h.adjudicator.adjudicate_candidates(h.client, h.deps.adjudicator_model, scen["failure"], [cand], cost_guard=guard, current_stage=current)
        out["cost_usd"] += guard.spent_today_usd - before
    out["adjudication"] = {"chosen": adj.chosen, "reasoning": adj.reasoning[:900], "adopted_reason": adj.adopted_reason, "model_called": adj.model_called, "fallback": adj.fallback}
    if adj.chosen is None:
        out["outcome"] = "adjudicator"
        return out
    # adopted: RUNS_AFTER_REPAIR, then the final, downgrade-only adjudicator, which sees the last five log lines (never the diff)
    lines = [f"[repair 1] tamper gate PASS for candidate(s) [1]; running them one after another, each in its own branch of the environment image",
             f"[repair 1 candidate 1] re-execution id={getattr(res, 'sandbox_id', None) or 'n/a'} exit_code=0; exit outcome changed",
             f"[adjudicator] qualifying candidate(s) [1]; chosen: 1 ({adj.adopted_reason or 'adjudicator'}); reasoning: {adj.reasoning[:300]}",
             f"[repair 1] candidate 1's env delta applied; build plan now: {{}}", "[verdict] RUNS_AFTER_REPAIR after 1 repair attempt(s)"]
    with model_lock:
        before = guard.spent_today_usd
        final = h.adjudicator.adjudicate(h.client, h.deps.adjudicator_model, "RUNS_AFTER_REPAIR", None, 1, "; ".join(lines[-5:]), cost_guard=guard)
        out["cost_usd"] += guard.spent_today_usd - before
    out["final_adjudicator"] = {"verdict": final.verdict, "downgraded": final.was_downgraded, "reason": final.downgrade_reason[:300], "attempted_upgrade": final.model_attempted_upgrade}
    try:
        result = {"verdict": final.verdict, "error_chain": [], "attempts": [{"attempt_number": 1, "candidate": 1, "gate_decision": "PASS", "diff_text": gate.canonical_diff or row["diff"],
                                                                         "exit_code": 0, "execution": execution, "chosen": True, "env_delta": [], "origin": "model"}]}
        out["labels"] = h.outcome_levels.compute(result)
    except Exception as exc:  # noqa: BLE001
        out["labels"] = {"error": f"{type(exc).__name__}: {exc}"[:200]}
    out["outcome"] = "final_adjudicator" if final.was_downgraded else "adopted"
    return out


# ---------------------------------------------------------------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", required=True, help="'heldout', 'dev' (the dev half: pilots and development) or a patch-set directory")
    ap.add_argument("--worktree", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--scenarios", default=str(HERE / "scenarios.json"))
    ap.add_argument("--cap-usd", type=float, default=35.0)
    ap.add_argument("--projection-limit-usd", type=float, default=35.0)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--ids", help="a file with one patch id per line: run only those (the committed subsample)")
    ap.add_argument("--retry-errors", action="store_true", help="move the records whose outcome is 'error' (a driver or API exception) to errors_first_attempt.jsonl and run those patches again, once")
    ap.add_argument("--replay-runs", help="a confirm/ directory (reports/v1.10/independent/confirm): patches with a recorded run there are not run again (harness-v1.9.0 measurement only)")
    ap.add_argument("--ablate-static", action="store_true", help="record the static findings but do not act on them (the trace layer alone): a diagnostic, labelled in every record")
    ap.add_argument("--no-replay-ids", help="a file of patch ids that are run again even though --replay-runs holds a record (the post-patch text of the two scripts differs by whitespace)")
    ap.add_argument("--go", action="store_true")
    ap.add_argument("--log-file")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.log_file:
        sys.stdout = sys.stderr = open(args.log_file, "a", encoding="utf-8", buffering=1)
    h = common.load_harness(Path(args.worktree), args.tag)
    scen_doc = json.loads(Path(args.scenarios).read_text(encoding="utf-8"))
    scen = scen_doc["scenarios"]
    bases_doc = {b["name"]: b for b in json.loads((ROOT / "reports/v1.9/planted/bases.json").read_text(encoding="utf-8"))["bases"]}
    bases = {n: {**b, "checkout": str(CHECKOUTS / b["repo"].replace("/", "_"))} for n, b in bases_doc.items()}
    documented = {n: (h.tamper_gate.documented_scripts(b["command"]) if hasattr(h.tamper_gate, "documented_scripts") else frozenset()) for n, b in bases_doc.items()}
    rows = load_half(args.set) if args.set in ("heldout", "dev") else load_dir_set(Path(args.set))
    rng = random.Random(ORDER_SEED)
    order = sorted(r["id"] for r in rows)
    rng.shuffle(order)
    if args.ids:
        keep = {l.strip() for l in Path(args.ids).read_text(encoding="utf-8").splitlines() if l.strip()}
        order = [i for i in order if i in keep]
    global SKIP_STATIC
    SKIP_STATIC = bool(args.ablate_static)
    if args.replay_runs:
        for l in (Path(args.replay_runs) / "results.jsonl").read_text(encoding="utf-8").splitlines():
            rec = json.loads(l)
            if rec.get("outcome") in ("confirmed", "not_confirmed") and "run" in rec:
                REPLAY[rec["id"]] = rec
        if args.no_replay_ids:
            for pid in Path(args.no_replay_ids).read_text(encoding="utf-8").split():
                REPLAY.pop(pid, None)
        print(f"{time.strftime('%H:%M:%S')} replay: {len(REPLAY)} recorded runs will not be run again", flush=True)
    by_id = {r["id"]: r for r in rows}
    results_path = out / "results.jsonl"
    if args.retry_errors and results_path.is_file():
        lines = [l for l in results_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        failed = [l for l in lines if json.loads(l).get("outcome") == "error"]
        if failed:
            with (out / "errors_first_attempt.jsonl").open("a", encoding="utf-8") as f:
                f.write("\n".join(failed) + "\n")
            results_path.write_text("\n".join(l for l in lines if l not in failed) + "\n", encoding="utf-8")
            print(f"{time.strftime('%H:%M:%S')} retry: {len(failed)} errored record(s) moved to errors_first_attempt.jsonl", flush=True)
    done = {json.loads(l)["id"] for l in results_path.read_text(encoding="utf-8").splitlines() if l.strip()} if results_path.is_file() else set()
    todo = [i for i in order if i not in done]
    print(f"{time.strftime('%H:%M:%S')} {args.set}: {len(rows)} patches, {len(order)} in the order, {len(done)} done, {len(todo)} to run at {h.tag} {h.head[:8]}", flush=True)
    if not args.go:
        return 0
    guard = h.CostGuard(daily_cost_ceiling_usd=args.cap_usd + 5, max_attempts_per_run=h.settings.max_attempts_per_run, model_prices_usd_per_1m=dict(h.settings.model_prices_usd_per_1m))
    meter, model_lock, write_lock = Meter(), threading.Lock(), threading.Lock()
    stopped = {"flag": False}

    def work(pid: str) -> None:
        if stopped["flag"]:
            return
        row = by_id[pid]
        try:
            rec = process(h, row, scen[row["base"]], bases, guard, model_lock, meter, documented)
        except Exception as exc:  # noqa: BLE001 - recorded, the run goes on
            rec = {"id": pid, "base": row["base"], "kind": row["kind"], "family": row["family"], "outcome": "error", "error": f"{type(exc).__name__}: {str(exc)[:300]}", "cost_usd": 0.0}
        rec["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        with write_lock:
            with results_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        meter.add(rec.get("cost_usd") or 0.0)
        with meter.lock:
            meter.done += 1
        print(f"{time.strftime('%H:%M:%S')} #{meter.done} {pid} -> {rec['outcome']} (${rec.get('cost_usd', 0):.4f}; total ${meter.usd:.4f})", flush=True)
        if meter.usd > args.cap_usd:
            stopped["flag"] = True
            print(f"CAP: ${meter.usd:.2f} > ${args.cap_usd:.2f}; stopping", flush=True)

    # the gate decides first, at no cost: its rejections are recorded now and never counted toward the cost projection
    passing = []
    for pid in todo:
        row = by_id[pid]
        rec, files, _ = gate_stage(h, row, scen[row["base"]], bases, documented)
        if files is None:
            rec["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            with results_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        else:
            passing.append(pid)
    print(f"{time.strftime('%H:%M:%S')} gate: {len(todo) - len(passing)} rejected, {len(passing)} go on to a real run", flush=True)
    todo = passing
    first, rest = todo[:10], todo[10:]
    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        list(pool.map(work, first))
    if first and len(done) == 0 and rest and not args.retry_errors:
        per = meter.usd / max(meter.done, 1)
        projected = meter.usd + per * len(rest) + scen_doc.get("baseline_spend_usd", 0.0)
        print(f"PROJECTION after {meter.done} patches: ${meter.usd:.4f} spent, ${per:.4f} each, ${projected:.2f} projected for {len(todo)} (+ baselines); limit ${args.projection_limit_usd:.2f}", flush=True)
        (out / "projection.json").write_text(json.dumps({"after": meter.done, "spent_usd": round(meter.usd, 6), "per_patch_usd": round(per, 6), "projected_total_usd": round(projected, 4),
                                                           "limit_usd": args.projection_limit_usd, "patches": len(todo)}, indent=1) + "\n", encoding="utf-8")
        if projected > args.projection_limit_usd:
            print("PROJECTION EXCEEDS THE LIMIT: stopped; commit a seeded stratified subsample before running the rest", flush=True)
            return 3
    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        list(pool.map(work, rest))
    (out / "spend.json").write_text(json.dumps({"harness_tag": h.tag, "harness_head": h.head, "patches_run": meter.done, "spend_usd_api_reported": round(meter.usd, 6),
                                                  "note": "sandbox steps' own reported cost plus the model calls' recorded cost"}, indent=1) + "\n", encoding="utf-8")
    print(f"done: {meter.done} patches, ${meter.usd:.4f}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
