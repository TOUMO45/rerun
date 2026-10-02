"""The sustained-run line (harness-v1.4.3-rc, D-42; owner's directive, chat 2026-10-02): no smoke artefact goes unlabelled.

A RUNS_* verdict after a repair is a SMOKE verdict: the documented command ran for `smoke_seconds` (60 s) without failing (smoke_exec). harness-v1.3.3's #11 was that
and nothing more, and harness-v1.4.2's #7 is the same kind of record. So, once the gate's entries are done, every RUNS_* entry whose smoke run was still alive at the
limit is re-executed ONCE, from the kept image its smoke command ran on (`execution.image` of the final attempt), for up to 600 s or to completion, and the outcome is
stored beside the smoke verdict. It is not a gate criterion and it changes no verdict; it labels what the smoke pass was.

Funding. A sandbox second costs about $0.0104 (API-reported records), so 600 s is about $6.2: more than a gate cap leaves after four entries. The sustained runs are
therefore funded from what the gate cap has left AFTER the entries (never from an entry's own cap, and never before an entry has run), split equally among the entries that
need one, at the owner's rate for a step whose cost is not reported ($0.0152/s, D-27) with a fixed reserve. The run lasts the smaller of 600 s and what that funds; a run
shorter than 600 s says so in its label ("funding-limited"). Below `MIN_SUSTAINED_SECONDS` (it must outlast the 60 s smoke window to say anything new) it is not run and the
record says why.

The command is the entry's documented command, unwrapped, on the image the smoke command ran on (tree + applied changes + environment). What it can say: it completed
(exit 0), it failed (exit code and the classifier's reading), or it was still running when the sandbox stopped it at the limit. It cannot say the result was reproduced.
"""

from __future__ import annotations

import math

from app.services import classifier, sandbox

SUSTAINED_SECONDS = 600
MIN_SUSTAINED_SECONDS = 90
FUNDING_RATE_USD_PER_S = 0.0152  # the owner's rate for a step whose cost is not reported (D-27): median 0.01013 x 1.5
RESERVE_USD = 0.05  # start-up and the sandbox's own overhead
RUNS_VERDICTS = ("RUNS_CLEAN", "RUNS_AFTER_REPAIR")
TAIL_CHARS = 2000


def final_run_of(record: dict) -> dict | None:
    """What a RUNS_* record offers to sustain, or None for any other verdict. `kind`: `smoke_alive` (the final attempt's smoke run was still running at its limit: this
    is what the sustained run exists for), `smoke_exited` (the command finished by itself inside the smoke window with exit 0: a completed run), `baseline_complete` (no
    smoke run: the as-published baseline ran to completion). `image` is the image the final smoke command ran on, when the record names one."""
    result = record.get("result") or {}
    if result.get("verdict") not in RUNS_VERDICTS:
        return None
    attempts = result.get("attempts") or []
    final = next((a for a in reversed(attempts) if a.get("chosen") is True and a.get("exit_code") == 0), None)
    if final is None:
        final = next((a for a in reversed(attempts) if a.get("exit_code") == 0 and a.get("execution")), None)
    execution = (final or {}).get("execution") or {}
    if not final or not execution:
        return {"kind": "baseline_complete", "attempt_number": None, "execution": None, "image": None}
    kind = "smoke_alive" if execution.get("outcome") == "alive_at_limit" else "smoke_exited"
    return {"kind": kind, "attempt_number": final.get("attempt_number"), "candidate": final.get("candidate"), "execution": execution,
            "image": execution.get("image")}


def funded_seconds(remaining_usd: float, entries_left: int) -> int:
    """The seconds one sustained run is funded for: its equal share of what is left, minus the reserve, at the rate for a step whose cost is not reported, capped at 600."""
    share = max(remaining_usd, 0.0) / max(entries_left, 1)
    return max(0, min(SUSTAINED_SECONDS, math.floor((share - RESERVE_USD) / FUNDING_RATE_USD_PER_S)))


def _tail(text: str) -> str:
    return text[-TAIL_CHARS:]


def _classification(step) -> dict | None:
    if step.exit_code == 0:
        return None
    c = classifier.classify(step.exit_code, step.stderr, step.stdout)
    return {"code": c.code, "evidence": (c.evidence or "")[:300]}


def outcome_of(step, *, funded: int, requested: int = SUSTAINED_SECONDS) -> tuple[str, str]:
    """(outcome, label) of a finished sustained step. The label is the sentence stored beside the smoke verdict."""
    seconds = round(step.elapsed_seconds)
    limited = " (funding-limited: the gate cap left less than requested)" if funded < requested else ""
    if step.timed_out:
        return "running_at_limit", (f"sustained run: still running when the sandbox stopped it at its {funded} s limit ({requested} s requested{limited}); "
                                    "it had not failed by then; this is not completion")
    if step.exit_code == 0:
        return "completed", f"sustained run: the command ran to completion in {seconds} s (exit code 0)"
    cls = _classification(step)
    return "failed", (f"sustained run: the command failed after {seconds} s (exit code {step.exit_code}; {cls['code']}: {cls['evidence'][:160]}); "
                      "the smoke pass came before this failure")


def run_sustained(record: dict, *, api_key: str, project_id: str = "", remaining_usd: float, entries_left: int = 1,
                  runner=sandbox.run_on_image, requested: int = SUSTAINED_SECONDS) -> dict | None:
    """The sustained-run record of one gate record, or None when its verdict is not RUNS_*. Runs at most one sandbox operation, never retries it, never raises for a sandbox
    failure (the record says what happened); `runner` is `sandbox.run_on_image` (tests pass a fake)."""
    final = final_run_of(record)
    if final is None:
        return None
    entry = record.get("corpus_entry") or {}
    command = entry.get("command") or ""
    doc: dict = {
        "record_kind": "sustained run (harness-v1.4.3, D-42, non-gating): the final smoke command re-executed from its kept image",
        "entry": (record.get("batch") or {}).get("entry_id"),
        "name": entry.get("name"),
        "verdict_of_record": (record.get("result") or {}).get("verdict"),
        "smoke_final": final,
        "command": command,
        "requested_seconds": requested,
        "rate_usd_per_s": FUNDING_RATE_USD_PER_S,
        "ran": False,
    }
    if final["kind"] == "baseline_complete":
        return {**doc, "outcome": "not_needed", "label": "no smoke artefact: the as-published baseline command ran to completion"}
    if final["kind"] == "smoke_exited":
        return {**doc, "outcome": "not_needed", "label": "no smoke artefact: the command finished by itself (exit code 0) inside the smoke window"}
    if not final["image"]:
        return {**doc, "outcome": "not_run", "reason": "the record names no kept image holding the tree, the applied changes and the environment of the final run",
                "label": "sustained run not made: no kept image holds the final run's tree, changes and environment; the smoke verdict stands unlabelled"}
    if not command:
        return {**doc, "outcome": "not_run", "reason": "the record has no documented command", "label": "sustained run not made: the record has no documented command"}
    funded = funded_seconds(remaining_usd, entries_left)
    doc.update(funded_seconds=funded, remaining_usd_before=round(remaining_usd, 6), entries_left=entries_left, reserve_usd=RESERVE_USD)
    if funded < MIN_SUSTAINED_SECONDS:
        return {**doc, "outcome": "not_run",
                "reason": f"${remaining_usd:.4f} left of the gate cap, shared by {entries_left} sustained run(s), funds {funded} s at ${FUNDING_RATE_USD_PER_S}/s; "
                          f"the minimum is {MIN_SUSTAINED_SECONDS} s (it must outlast the smoke window)",
                "label": f"sustained run not made: the gate cap left funds {funded} s, below the {MIN_SUSTAINED_SECONDS} s minimum; the smoke verdict stands unlabelled"}
    try:
        step = runner(api_key=api_key, project_id=project_id, image_id=final["image"], command=command, timeout_seconds=float(funded))
    except sandbox.SandboxTimeoutError as exc:
        estimated = round(funded * FUNDING_RATE_USD_PER_S, 6)
        return {**doc, "ran": True, "outcome": "running_at_limit", "via": "client_wait_timeout", "cost_usd": 0.0, "cost_estimated_usd": estimated,
                "cost_tag": "ESTIMATED: the client's wait ended before the API returned a result, so no cost was reported",
                "label": (f"sustained run: still running when the client's wait ended at its {funded} s limit ({requested} s requested); the API reported no result; "
                          "it had not failed by then; this is not completion"), "message": str(exc)[:300]}
    except Exception as exc:  # noqa: BLE001 - a failed sustained run is a record, never a reason to lose the gate's other records
        return {**doc, "ran": True, "outcome": "error", "cost_usd": 0.0, "cost_estimated_usd": 0.0, "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                "label": f"sustained run did not produce a result ({type(exc).__name__}); the smoke verdict stands unlabelled"}
    outcome, label = outcome_of(step, funded=funded, requested=requested)
    return {**doc, "ran": True, "outcome": outcome, "label": label, "exit_code": step.exit_code, "timed_out": step.timed_out,
            "seconds": round(step.elapsed_seconds, 3), "cost_usd": round(step.cost_usd, 6), "cost_estimated_usd": 0.0, "cost_tag": "API-REPORTED",
            "streams": step.streams(), "stdout_tail": _tail(step.stdout), "stderr_tail": _tail(step.stderr), "classification": _classification(step)}
