"""Seal of harness-v1.4.3 (option B over CHANGED files; owner, chat 2026-10-02): live checks of every sandbox-touching path through the REAL runner.

    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.4.3/seal/run_seal_v143.py                          # PLAN: what would run, ESTIMATED cost
    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.4.3/seal/run_seal_v143.py --go --max-usd X         # spends money (owner's cap, at most $1.50)
    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.4.3/seal/run_seal_v143.py --go --max-usd X --stage new   # one stage (resume after a stop)

What changed among the sandbox-touching files (scripts/run_corpus_v1_batch.py SANDBOX_TOUCHING_FILES): `sandbox.py` (D-41: the client asks for a 4 MiB output limit, each step
carries the API's `truncated` flags, sizes and hashes; D-42: `run_on_image`). `sandbox_limits.py`, `runner_env.py`, `smoke_exec.py` and `runner_hooks.py` are byte-identical to
harness-v1.4.2. EVERY entry of seal_verification.json lists sandbox.py, so the option-B rule ("an entry that lists a changed file is re-verified") re-verifies all 17: the sandbox
checks of the earlier seals are re-run here, unchanged, against the new blob, plus the new checks. Stages (in the order they run, cheapest decisive first):

  new    S1 a failing command writes 200,000 bytes of progress and a last line on stderr: the whole stream comes back, `truncated` false, sizes recorded (the D-41 test, live);
         S2 the same with 5 MiB: the API cuts at the limit we asked for (4 MiB exactly), `truncated` true, the last line is NOT returned, the harness labels it (OUTPUT_TRUNCATED);
         S3 `run_on_image` reopens a kept image by id and runs a command once, disposable (the sustained-run primitive); S4 the same stopped at a 3 s limit: the record shows
         whichever stop path the API took (the server's result with `timed_out`, or the client's wait).
  v141   K1 a step stopped at the operation limit keeps the layer built before it; K2 resume from that layer; L1/L2 the additive apt layer.            (v1.4.1 seal, re-run)
  v142   A, B (the branch-run cost), C, W0, W1, W2 the hooks and the exit wrapper; E0, E1a the evidence command after a calm run and a self-SIGKILL.   (v1.4.2 seal, re-run; E1b is informational and not repeated)
  v140   A, B, C, D the checkpoint layers, a branch run, hooks, a kept image reopened after a wait; E, F entry 7's recorded environment as a checkpoint.   (v1.4.0 seal, re-run)
  final  the 14 checks of scripts/run_seal_verification_v140.py: the download route, the archive upload, three torch installs, the runner-setup phase tag, the kill at the
         operation limit through both stop paths, the smoke launcher on Python 3.10 and 3.6.                                                        (v1.3.4 / v1.4.0 set, re-run)

Every record goes to runs/sandbox_verification/v1.4.3-seal/<stage>/, and runs/sandbox_verification/v1.4.3-seal/SEAL_RUN.json says which commit and which blobs of the five
sandbox-touching files the stages ran against. The driver refuses to start unless HEAD's harness paths are byte-identical to the tag harness-v1.4.3-rc and clean, and refuses to
record a stage if a blob changed while it ran: scripts/write_seal_verification_v143.py reads SEAL_RUN.json. Never runs without --go and --max-usd (at most $1.50: the owner's
seal bound). A stage that fails stops the seal (nothing further is run) and is reported.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
REPO_ROOT = ROOT  # where the code, the git repository and the earlier seals' records are; ROOT is only what the records of THIS seal are written relative to (tests move it)
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
OUT = ROOT / "runs" / "sandbox_verification" / "v1.4.3-seal"
MAX_SEAL_USD = 1.50
RC_TAG = "harness-v1.4.3-rc"
HARNESS_PATHS = ("backend/app", "backend/pyproject.toml", "scripts", "frontend/src", ".gitattributes")
SANDBOX_FILES = ("backend/app/services/sandbox.py", "backend/app/services/sandbox_limits.py", "backend/app/services/runner_env.py",
                 "backend/app/services/smoke_exec.py", "backend/app/services/runner_hooks.py")
STAGES = ("new", "v141", "v142", "v140", "final")
KILL_OP_SECONDS = 25.0  # K1's operation limit (v1.4.1 used 30 s; its killed step ran 23.6 s of them, so about 6 s went to the extract and the pip step: a shorter clock could stop it during pip)
MARKER = "FINAL_TRACEBACK_MARKER AssertionError: Torch not compiled with CUDA enabled"
TICK = "\r17.8%"
# The progress writer: no backslash in the embedded source (chr(13), chr(10)), the last line printed with print() so it ends in a newline.
EMIT = (b"import sys\n"
        b"total, code = int(sys.argv[1]), int(sys.argv[2])\n"
        b"tick = chr(13) + '17.8%'\n"
        b"sys.stderr.write(tick * (total // len(tick)))\n"
        b"print(chr(10) + '" + MARKER.encode() + b"', file=sys.stderr)\n"
        b"print('stdout-line')\n"
        b"sys.exit(code)\n")

# A stream of U+2588 (three bytes each in UTF-8): 4 MiB = 4,194,304 bytes is 1 byte past a multiple of 3, so the API's cut lands INSIDE a character. The SDK's own default decoding is a
# strict .decode() that raises inside `.wait()` for such a stream (the independent review of the rc found it); the harness asks for bytes and decodes with replacement.
EMIT_GLYPH = (b"import sys\n"
              b"count = int(sys.argv[1])\n"
              b"sys.stderr.buffer.write((chr(0x2588) * count).encode('utf-8'))\n"
              b"sys.stderr.buffer.flush()\n"
              b"sys.exit(1)\n")
GLYPH_COUNT = 1_500_000  # 4,500,000 bytes

# ESTIMATED cost of the new checks: a small operation costs about $0.002-0.012 (v1.4.2 seal records); S2 moves 9 MiB; S4 is stopped after 3 s.
NEW_ESTIMATES = {"S1": 0.015, "S2": 0.03, "S2b": 0.03, "S3": 0.03, "S4": 0.06}


def expected_stderr(total: int) -> str:
    """What the writer puts on stderr for `total`: whole ticks, a newline, the marker line."""
    return TICK * (total // len(TICK)) + "\n" + MARKER + "\n"


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout.strip()


def blobs() -> dict:
    return {f: _git("hash-object", f) for f in SANDBOX_FILES}


def precondition(git=_git) -> dict:
    """The seal runs against the release candidate and nothing else: HEAD's harness paths are byte-identical to the rc tag, and clean. Returns what to record."""
    try:
        git("rev-parse", "--verify", f"refs/tags/{RC_TAG}^{{commit}}")
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"REFUSED: the tag {RC_TAG} does not exist: tag the release candidate commit first") from exc
    changed = git("diff", "--name-only", RC_TAG, "HEAD", "--", *HARNESS_PATHS)
    dirty = git("status", "--porcelain", "--", *HARNESS_PATHS)
    if changed or dirty:
        raise SystemExit(f"REFUSED: the harness paths are not those of {RC_TAG} (changed since the tag: {changed.splitlines()[:5]}; uncommitted: {dirty.splitlines()[:5]})")
    return {"harness_rc_tag": RC_TAG, "rc_commit": git("rev-parse", RC_TAG), "head": git("rev-parse", "HEAD")}


def previous_cost(rel: str) -> float:
    """The API-reported cost of the same check in an earlier seal's record (planning only)."""
    rec = json.loads((REPO_ROOT / rel).read_text(encoding="utf-8"))
    value = rec.get("cost_usd", rec.get("completed_cost_usd", 0.0))
    return float(value) if isinstance(value, (int, float)) else 0.0


def plan() -> list[dict]:
    """(stage, op, estimated usd, source). Costs of re-run checks are the earlier records' own; new checks are NEW_ESTIMATES; K1 is the guard's estimate of its killed step."""
    rows = [{"stage": "new", "op": k, "usd": v, "source": "ESTIMATED: a small operation (v1.4.2 seal records $0.001-0.012)"} for k, v in NEW_ESTIMATES.items()]
    rows += [{"stage": "v141", "op": "run3_K1_operation_stopped_at_its_limit", "usd": round(KILL_OP_SECONDS * 0.0152, 4),
              "source": "ESTIMATED: the stopped step at $0.0152/s (D-27) for the operation limit; the API may report less"}]
    for stage, directory, names in (("v141", "v1.4.1-seal", ("run3_K2_resume_from_the_kept_layer", "run2_L1_image_without_a_compiler", "run2_L2_additive_apt_layer")),
                                    ("v142", "v1.4.2-seal", ("run1_A_ready_image", "run1_B_branch_run", "run1_C_runner_hooks", "run1_W0_hook_alone_sees_nothing",
                                                             "run1_W1_wrapper_prints_the_raise_site", "run1_W2_wrapper_on_python36", "run2_E0_calm_run_with_evidence",
                                                             "run2_E1a_self_sigkill_with_evidence")),
                                    ("v140", "v1.4.0-seal", ("run1_A_ready_image", "run1_B_branch_run", "run1_C_runner_hooks", "run1_D_reopen_kept_image",
                                                             "run2_E_entry07_checkpoint", "run2_F_reopen_apply_execute"))):
        for name in names:
            rows.append({"stage": stage, "op": name, "usd": previous_cost(f"runs/sandbox_verification/{directory}/{name}.json"), "source": f"{directory} record, API-reported"})
    for path in sorted((REPO_ROOT / "runs" / "sandbox_verification" / "final-v1.4.0").glob("*.json")):
        rows.append({"stage": "final", "op": path.stem, "usd": previous_cost(str(path.relative_to(REPO_ROOT))), "source": "final-v1.4.0 record (a stopped step's cost is not in it)"})
    return rows


# --- the new checks (S1-S4) ------------------------------------------------------------------------------------------------------

def _record(stage: str, name: str, blobs_now: dict, **fields) -> dict:
    directory = OUT / stage
    directory.mkdir(parents=True, exist_ok=True)
    doc = {"written_at": datetime.now(timezone.utc).isoformat(), "harness": RC_TAG, "code_blobs": blobs_now, **fields}
    (directory / f"{name}.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8", newline="\n")
    return doc


def _result_doc(result) -> dict:
    return {"run_id": result.sandbox_id, "cost_usd": result.total_cost_usd,
            "steps": [{"phase": s.phase, "command": s.command[:160], "exit": s.exit_code, "seconds": s.elapsed_seconds, "cost_usd": s.cost_usd} for s in (*result.rerun_steps, *result.steps)],
            "layers": [{"setup_commands": len(ops), "image": image} for ops, image in result.layers], "result_image": result.result_image,
            "streams": result.final.streams(), "max_rss_as_returned": result.final.max_rss, "stdout": result.final.stdout[-300:], "stderr_tail": result.final.stderr[-400:], "stderr_head": result.final.stderr[:60]}


def run_new(api_key: str, project_id: str, guard, blobs_now: dict) -> list[dict]:
    from app.services import orchestrator, sandbox

    docs = []

    def run(**kw):
        result = sandbox.run_build_and_execute(api_key=api_key, project_id=project_id, base_image="python:3.10-slim", install_commands=["true"], wall_clock_seconds=60,
                                               upload_files={"emit.py": EMIT}, **kw)
        guard.record_spend(result.total_cost_usd)
        return result

    total1 = 200_000
    s1 = run(execute_command=f"python3 emit.py {total1} 1")
    want1 = expected_stderr(total1).encode()
    ok1 = (s1.final.exit_code == 1 and s1.final.stderr == want1.decode() and not s1.final.stderr_truncated and not s1.final.stdout_truncated
           and s1.final.streams()["stderr"]["bytes"] == len(want1) and "stdout-line" in s1.final.stdout)
    docs.append(_record("new", "S1_200kb_stderr_whole", blobs_now, ok=ok1, expected_bytes=len(want1), limit_bytes=sandbox.OUTPUT_LIMIT_BYTES, **_result_doc(s1)))

    total2 = sandbox.OUTPUT_LIMIT_BYTES + 1024 * 1024
    s2 = run(execute_command=f"python3 emit.py {total2} 1")
    got2 = len(s2.final.stderr.encode())
    reason = orchestrator.output_cut_without_error(s2)
    ok2 = (s2.final.exit_code == 1 and s2.final.stderr_truncated is True and got2 == sandbox.OUTPUT_LIMIT_BYTES and MARKER not in s2.final.stderr
           and s2.final.streams()["stderr"]["truncated"] is True and bool(reason) and reason.startswith("OUTPUT_TRUNCATED: "))
    docs.append(_record("new", "S2_stream_over_the_limit_flagged", blobs_now, ok=ok2, requested_bytes=total2, returned_bytes=got2, limit_bytes=sandbox.OUTPUT_LIMIT_BYTES,
                        harness_reason=reason, **_result_doc(s2)))

    glyph = sandbox.run_build_and_execute(api_key=api_key, project_id=project_id, base_image="python:3.10-slim", install_commands=["true"], wall_clock_seconds=60,
                                          upload_files={"emit_glyph.py": EMIT_GLYPH}, execute_command=f"python3 emit_glyph.py {GLYPH_COUNT}")
    guard.record_spend(glyph.total_cost_usd)
    returned = glyph.final.stderr.encode("utf-8")
    ok2b = (glyph.final.exit_code == 1 and glyph.final.stderr_truncated is True and glyph.final.stderr.endswith("\ufffd")  # the half character became U+FFFD, no exception
            and glyph.final.streams()["stderr"]["truncated"] is True)
    docs.append(_record("new", "S2b_cut_inside_a_multibyte_character", blobs_now, ok=ok2b, glyph_bytes=GLYPH_COUNT * 3, returned_chars=len(glyph.final.stderr),
                        returned_bytes_after_replacement=len(returned), ends_with_replacement_character=glyph.final.stderr.endswith("\ufffd"),
                        harness_reason=orchestrator.output_cut_without_error(glyph), **_result_doc(glyph)))

    kept = run(execute_command=f"python3 emit.py 1000 0", checkpoint=sandbox.Checkpoint(keep_layers=True, keep_result=True))
    image = kept.result_image
    step = sandbox.run_on_image(api_key=api_key, project_id=project_id, image_id=image, command=f"python3 emit.py 3000 0", timeout_seconds=30)
    guard.record_spend(step.cost_usd)
    ok3 = bool(image) and step.exit_code == 0 and "stdout-line" in step.stdout and not step.timed_out and step.stderr == expected_stderr(3000)
    docs.append(_record("new", "S3_run_on_image_reopens_a_kept_image", blobs_now, ok=ok3, run_id=image, image=image, cost_usd=kept.total_cost_usd + step.cost_usd, exit_code=step.exit_code,
                        seconds=step.elapsed_seconds, streams=step.streams(), timed_out=step.timed_out, kept_image_run_cost_usd=kept.total_cost_usd))

    via, killed_cost, cost, timed_out, exit_code, message = "", 0.0, 0.0, None, None, ""
    try:
        stopped = sandbox.run_on_image(api_key=api_key, project_id=project_id, image_id=image, command="sleep 20; echo late", timeout_seconds=3)
        via, cost, timed_out, exit_code = "server_result_timed_out" if stopped.timed_out else "returned", stopped.cost_usd, stopped.timed_out, stopped.exit_code
        guard.record_spend(cost)
        ok4 = bool(stopped.timed_out) and "late" not in stopped.stdout
    except sandbox.SandboxTimeoutError as exc:
        via, message = "client_wait_timeout", str(exc)[:300]
        killed_cost = guard.record_killed_operation(0.0, 3.0, note="S4: sleep 20")
        cost, ok4 = killed_cost, True
    docs.append(_record("new", "S4_run_on_image_stopped_at_its_limit", blobs_now, ok=ok4, run_id=image, image=image, via=via, cost_usd=cost, timed_out=timed_out, exit_code=exit_code, message=message,
                        cost_tag="API-REPORTED" if via == "server_result_timed_out" else "ESTIMATED: the client's wait ended first, no cost reported (computed at $0.0152/s)"))
    return docs


# --- the stages of the earlier seals, re-run ----------------------------------------------------------------------------------------

def _redirect(module, stage: str, blobs_now: dict) -> None:
    """Point an earlier seal script at this seal's directory and make every record it writes carry the blobs the stage ran against."""
    module.OUT = OUT / stage
    original = module._record

    def record(name, **fields):
        # the record is this seal's: its provenance says so (the earlier script's own tag would name a release candidate that is not the one being sealed)
        return original(name, **{"code_blobs": blobs_now, "harness": RC_TAG, **fields})

    module._record = record


def run_v141(api_key, project_id, guard, blobs_now):
    mod = _load("reports/corpus-v2.1/v1.4.1/seal/run_seal_v141.py", "run_seal_v141")
    _redirect(mod, "v141", blobs_now)
    return mod.run_3(api_key, project_id, guard, KILL_OP_SECONDS) + mod.run_2(api_key, project_id, guard)


def run_v142(api_key, project_id, guard, blobs_now):
    """run 1 (A, B, C, W0, W1, W2) as in the v1.4.2 seal; run 2 without E1b (informational; its 25 s memory allocation is not a check of sandbox.py)."""
    mod = _load("reports/corpus-v2.1/v1.4.2/seal/run_seal_v142.py", "run_seal_v142")
    _redirect(mod, "v142", blobs_now)
    docs = mod.run_1(api_key, project_id, guard)
    from app.services import runner_hooks, sandbox

    def op(key, label, script):
        clock = mod._seconds(guard, key)
        return mod._guarded(f"run2_{label}", guard, lambda: sandbox.run_build_and_execute(
            api_key=api_key, project_id=project_id, base_image="python:3.10-slim", install_commands=["true"],
            execute_command=runner_hooks.evidence_command("python3 probe.py"), wall_clock_seconds=clock, upload_files={"probe.py": script}))

    e0, _ = op("E0", "E0_calm_run_with_evidence", mod.CALM_EXIT)
    if e0 is None:
        return [*docs, {"ok": False, "note": "E0 was stopped at its operation clock (its own failing record is in the stage directory)"}]
    guard.record_spend(e0.total_cost_usd)
    ev0 = runner_hooks.parse_evidence(e0.final.stderr, e0.final.stdout)
    docs.append(mod._record("run2_E0_calm_run_with_evidence", ok=e0.final.exit_code == 3 and ev0 is not None and ev0["exit_status"] == 3 and bool(ev0["mem_total_kb"])
                            and not runner_hooks.kill_evidenced(ev0), evidence=ev0, limit_quote=runner_hooks.limit_quote(ev0), **mod._result_doc(e0)))
    e1a, _ = op("E1a", "E1a_self_sigkill_with_evidence", mod.SELF_KILL)
    if e1a is None:
        return [*docs, {"ok": False, "note": "E1a was stopped at its operation clock (its own failing record is in the stage directory)"}]
    guard.record_spend(e1a.total_cost_usd)
    ev1 = runner_hooks.parse_evidence(e1a.final.stderr, e1a.final.stdout)
    killed = e1a.final.exit_code == 137 and ev1 is not None and runner_hooks.kill_evidenced(ev1)
    docs.append(mod._record("run2_E1a_self_sigkill_with_evidence", ok=killed and "Killed" in e1a.final.stderr and mod.classify_137(e1a), evidence=ev1,
                            limit_quote=runner_hooks.limit_quote(ev1), **mod._result_doc(e1a)))
    return docs


def run_v140(api_key, project_id, guard, blobs_now, wait_seconds: int = 600):
    mod = _load("reports/corpus-v2.1/v1.4.0/seal/run_seal_v140.py", "run_seal_v140")
    _redirect(mod, "v140", blobs_now)
    return mod.run_1(api_key, project_id, guard, wait_seconds) + mod.run_2(api_key, project_id, guard)


def run_final(api_key, project_id, guard, blobs_now):
    """The 14 verifier-script checks of the v1.4.0 seal, in its order, each in its own process through scripts/verify_*.py; the stage's cost is each record's own."""
    mod = _load("scripts/run_seal_verification_v140.py", "run_seal_verification_v140")
    mod.OUT = (OUT / "final").relative_to(ROOT).as_posix()  # the earlier script writes under its own root: the same place in production
    (ROOT / mod.OUT).mkdir(parents=True, exist_ok=True)
    docs = []
    for record, argv, env, what in mod.PLAN:
        done = ROOT / mod.OUT / record
        if done.is_file() and json.loads(done.read_text(encoding="utf-8")).get("ok") is True:
            print(f"-> {record}: already passed in an earlier invocation, not run again", flush=True)
            docs.append({"ok": True, "cost_usd": 0.0, "run_id": json.loads(done.read_text(encoding="utf-8")).get("run_id"), "skipped": True})
            continue
        expected = previous_cost(f"runs/sandbox_verification/final-v1.4.0/{record}")
        if guard.remaining_today_usd < expected:  # the same check's cost in the v1.4.0 seal: do not start what the cap cannot cover
            raise SystemExit(f"STOP: ${guard.remaining_today_usd:.4f} left under the seal cap, below the ${expected:.4f} this check cost in the v1.4.0 seal; {record} is not started")
        print(f"-> {record}: {what}", flush=True)
        ok, cost, rec = mod._run(record, argv, env)
        guard.record_spend(cost)
        docs.append({"ok": ok, "cost_usd": cost, "run_id": rec.get("run_id")})
        print(f"   ok={ok} cost ${cost:.4f}", flush=True)
        if not ok:
            return docs
    vias = set()
    for n in range(mod.MAX_KILL_RUNS):
        record = mod.KILL[0].format(n="" if n == 0 else f"_extra{n}")
        print(f"-> {record}: {mod.KILL[3]}", flush=True)
        ok, cost, rec = mod._run(record, mod.KILL[1], mod.KILL[2])
        guard.record_spend(cost)
        vias.add(rec.get("via"))
        docs.append({"ok": ok, "cost_usd": cost, "run_id": rec.get("run_id"), "via": rec.get("via")})
        print(f"   ok={ok} via={rec.get('via')} cost ${cost:.4f}", flush=True)
        if not ok:
            return docs
        if {"server_result_timed_out", "client_wait_timeout"} <= vias:
            return docs
    docs.append({"ok": False, "cost_usd": 0.0, "run_id": None, "note": f"both stop paths not seen in {mod.MAX_KILL_RUNS} runs ({sorted(map(str, vias))})"})
    return docs


RUNNERS = {"new": run_new, "v141": run_v141, "v142": run_v142, "v140": run_v140, "final": run_final}


def _load_summary(blobs_now: dict, state: dict) -> dict:
    """The summary of earlier invocations of this seal. It belongs to a release candidate (its rc commit and the blobs of the five files), not to a HEAD: data commits between
    invocations (partial records) are fine, since `precondition` already requires the harness paths to equal the rc tag."""
    path = OUT / "SEAL_RUN.json"
    if not path.is_file():
        return {**state, "blobs": blobs_now, "stages": {}, "started_at": datetime.now(timezone.utc).isoformat()}
    summary = json.loads(path.read_text(encoding="utf-8"))
    if summary.get("blobs") != blobs_now or summary.get("rc_commit") != state["rc_commit"]:
        raise SystemExit("REFUSED: SEAL_RUN.json belongs to another release candidate or other blobs of the sandbox-touching files; archive it and start the seal over")
    return summary


def stage_records(stage: str) -> list[dict]:
    """The records a stage left in its directory (every `*.json`), loaded."""
    directory = OUT / stage
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(directory.glob("*.json"))] if directory.is_dir() else []


def execute_stages(stages: list[str], summary: dict, guard, blobs_now: dict, *, api_key: str, project_id: str, wait_seconds: int, cap: float,
                   explicit: bool = False, runners: dict | None = None) -> int:
    """Run the stages in order and write SEAL_RUN.json after EACH, whatever happened in it: a stage that raised (the cap's refusal to start a check, an uncaught stop) is recorded
    with the money it spent so far and ok false, a stage's cost is cumulative over its attempts, and a stage is ok only if the docs it returned passed AND no record it left in its
    directory says otherwise (a stopped operation writes its own failing record and the older stage code returned early without a failing doc). Stages already ok are skipped on a
    resume unless named with --stage."""
    runners = runners or RUNNERS
    for stage in stages:
        if summary["stages"].get(stage, {}).get("ok") and not explicit:
            print(f"=== stage {stage}: already passed ({summary['stages'][stage].get('cost_usd', 0.0):.4f} spent), skipped ===", flush=True)
            continue
        before, error, docs = guard.spent_today_usd, None, []
        print(f"=== stage {stage} ===", flush=True)
        extra = (wait_seconds,) if stage == "v140" else ()
        try:
            docs = runners[stage](api_key, project_id, guard, blobs_now, *extra)
        except BaseException as exc:  # noqa: BLE001 - SystemExit included: the partial spend must be written down
            error = exc
        spent = guard.spent_today_usd - before
        moved = blobs() != blobs_now
        required = [d for d in docs if not d.get("informational")]
        bad = [r for r in stage_records(stage) if r.get("ok") is not True and not r.get("informational")]
        ok = error is None and not moved and bool(required) and all(d.get("ok") for d in required) and not bad
        previous = summary["stages"].get(stage, {})
        summary["stages"][stage] = {"ok": ok, "cost_usd": round(previous.get("cost_usd", 0.0) + spent, 6), "attempts": previous.get("attempts", 0) + 1,
                                    "finished_at": datetime.now(timezone.utc).isoformat(),
                                    "records": sorted(p.relative_to(ROOT).as_posix() for p in (OUT / stage).glob("*.json")),
                                    **({"stopped_by": f"{type(error).__name__}: {str(error)[:300]}"} if error is not None else {}),
                                    **({"failing_records": len(bad)} if bad else {}), **({"blobs_changed_while_running": True} if moved else {})}
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "SEAL_RUN.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
        total = sum(s.get("cost_usd", 0.0) for s in summary["stages"].values())
        print(f"stage {stage}: ok={ok} ${spent:.4f}; seal total ${total:.4f} of ${cap}", flush=True)
        if not ok:
            why = f"stopped by {type(error).__name__}: {error}" if error is not None else "a check did not pass" if not moved else "a sandbox-touching file changed while it ran"
            print(f"STOP: stage {stage}: {why}; nothing further is run", file=sys.stderr)
            return 1
    return 0 if all(summary["stages"].get(s, {}).get("ok") for s in STAGES) else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true", help="actually run (spends money; needs the owner's seal cap)")
    ap.add_argument("--max-usd", type=float, help="the seal cap (at most $1.50)")
    ap.add_argument("--stage", action="append", choices=STAGES, help="run only this stage (repeatable), even if it already passed; default: every stage that has not passed, in order")
    ap.add_argument("--wait-seconds", type=int, default=600, help="v140 stage: delay before the kept image is reopened")
    args = ap.parse_args(argv)
    stages = [s for s in STAGES if not args.stage or s in args.stage]
    rows = [r for r in plan() if r["stage"] in stages]
    print("v1.4.3 seal plan (ESTIMATED costs; the earlier records' own API-reported costs where a check is re-run):")
    for r in rows:
        print(f"  {r['stage']:6s} {r['op']:50s} ~${r['usd']:.4f}  ({r['source']})")
    print(f"  total ~${sum(r['usd'] for r in rows):.4f} [ESTIMATED]")
    if not args.go:
        print("PLAN ONLY: nothing was run and nothing was spent (pass --go and --max-usd to run).")
        return 0
    if args.max_usd is None or args.max_usd <= 0 or args.max_usd > MAX_SEAL_USD + 1e-9:
        print(f"REFUSED: --max-usd is required and must be at most ${MAX_SEAL_USD:.2f} (the owner's seal bound)", file=sys.stderr)
        return 2
    state = precondition()
    blobs_now = blobs()
    summary = _load_summary(blobs_now, state)
    from app.config import get_settings
    from app.services.cost_guard import CostGuard

    settings = get_settings()
    prior = sum(s.get("cost_usd", 0.0) for s in summary["stages"].values())
    guard = CostGuard(daily_cost_ceiling_usd=args.max_usd)
    guard.record_spend(prior)
    print(f"seal cap ${args.max_usd}; already spent in earlier invocations ${prior:.4f}")
    code = execute_stages(stages, summary, guard, blobs_now, api_key=settings.nebius_api_key, project_id=settings.nebius_project_id,
                          wait_seconds=args.wait_seconds, cap=args.max_usd, explicit=bool(args.stage))
    total = sum(s.get("cost_usd", 0.0) for s in summary["stages"].values())
    print(f"seal spend ${total:.4f} [sum of operation costs: API-reported, plus the estimate of any stopped step]; all stages ok: {code == 0}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
