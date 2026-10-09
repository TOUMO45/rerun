"""Outcome ladder (harness-v1.6, item L).

PURE. No network, no model call, no filesystem. Reads ONLY the stored result fields `verdict`, `error_chain` and
`attempts` and says how far the run got on a four-rung ladder, so a verdict such as BLOCKED can still be read as
"the first failure was cleared, the environment resolved, the entry point did not run" instead of a single word.

Why a separate module: the verdict is a clamp (adjudicator.py) and the chain is a log; neither says on its own
whether RERUN's deterministic layers made progress. The rungs are derived from the record, never from a model, and
are recomputed from any stored record, so an old certificate can be read the same way as a new one.

  first_error_cleared     the chain's first link was cleared by some attempt (`cleared_by` is set; for a record written
                          before v1.6 whose only failure the run then passed without, the RUNS_* verdict says so)
  first_error_cleared_by  the `origin` of that attempt ("time_machine", "model", ...), or None when no attempt with
                          that number is in `attempts` (the baseline's number 0 is the time machine's attempt when
                          it ran; a chain cleared by a record no attempt carries stays unexplained, honestly)
  env_resolved            the run got past the environment: the entry point ran, or the LAST failure is not an
                          environment-family class (dependencies, system libraries, the interpreter, the mirrors)
  entrypoint_runs         the verdict says the repository's command completed
  semantic_change         harness-v1.7 (R6, D-44); present ONLY on a RUNS_AFTER_REPAIR run whose passing code carries a gated model patch that
                          touches a call of tamper_gate.SEMANTIC_CALLS: the names of those calls. The verdict is unchanged; its label reads
                          "RUNS_AFTER_REPAIR (semantic change)" (`verdict_label`). Absent otherwise, so every record written before v1.7 that it
                          does not flag reads exactly as before.
  resource_adapted        harness-v1.7 (R1 d); present ONLY when a resource_adapt step ran: the label of the last adaptation applied
                          ("RESOURCE-ADAPTED: --batch_size 256->128"). The documented command did not run as published from then on.
  memory_adapted          harness-v1.7 (R1 c, v1.7 review H2); present ONLY when the memory hook changed a DataLoader: "memory hook: DataLoader
                          num_workers 2->0" (random draws then come from the main process's stream).
  exit_zero_overruled     harness-v1.7.2 (D-46); present ONLY when a run of this entry exited 0 and the exit-zero check overruled it (an uncaught
                          traceback, or only a usage / "missing" message): "exit 0 overruled: <evidence>". Records written before v1.7.2 carry no
                          `exit_zero_check` and read exactly as before.
  dependency_change       harness-v1.7 (R5, v1.7 review H1); present ONLY when companion_relax ran: "dependency change: torchvision 0.5.0->0.4.0"; from harness-v1.7.1 with what it pins
                          beside the replacement: "dependency change: torchvision 0.5.0->0.4.0, Pillow 9.0.0->6.2.2".
"""

from __future__ import annotations

import re

from app.services.classifier import TaxonomyCode

# The classes that mean "the environment is not built yet". A last failure of any other class (data, GPU, a code
# bug, a hard-coded path) was raised by the repository's own code running in a built environment.
ENVIRONMENT_CLASSES: frozenset[str] = frozenset(
    {
        TaxonomyCode.DEP_MISSING,
        TaxonomyCode.DEP_YANKED,
        TaxonomyCode.DEP_UNPINNED_CONFLICT,
        TaxonomyCode.DEP_NOT_ON_PYPI,
        TaxonomyCode.DEP_BUILD_FAILED,
        TaxonomyCode.SYS_LIB_MISSING,
        TaxonomyCode.APT_MIRROR_GONE,
        TaxonomyCode.PY_VERSION_INCOMPAT,
    }
)

RUNS_VERDICTS: frozenset[str] = frozenset({"RUNS_CLEAN", "RUNS_AFTER_REPAIR"})
SEMANTIC_CHANGE_LABEL = "RUNS_AFTER_REPAIR (semantic change)"
EXIT_ZERO_LABEL = "exit 0 overruled"
REVIEW_LABEL = "REVIEW REQUIRED"
REVIEW_NOTE = ("advisory (harness-v1.10 flag mode, chosen after the measured results were seen): the behavioural checks would have refused this adopted patch; "
               "the verdict is harness-v1.9.0's and is not changed by the flag")


def _overruled(holder) -> dict | None:
    found = (holder or {}).get("exit_zero_check") if isinstance(holder, dict) else None
    return found if isinstance(found, dict) and found.get("overruled") else None


def attempt_passed(record: dict | None) -> bool:
    """harness-v1.7.2 (D-46): a stored attempt / candidate / stage dict that PASSED: exit code 0 and not overruled by the exit-zero check
    (exit_zero_check; the finding sits on the dict itself, on its `execution` or on its `stage`). Records written before v1.7.2 carry no finding and
    read exactly as before (exit code 0 = passed)."""
    if not isinstance(record, dict) or record.get("exit_code") != 0:
        return False
    return not any(_overruled(h) for h in (record, record.get("execution"), record.get("stage")))


def exit_zero_overruled(result: dict) -> str:
    """harness-v1.7.2 (D-46): "exit 0 overruled: <evidence>" for the LAST overruled run of the record (error-chain links, then attempts), or ''."""
    found = [_overruled(link) for link in (result.get("error_chain") or ())]
    found += [_overruled(a) or _overruled(a.get("execution")) for a in (result.get("attempts") or ()) if isinstance(a, dict)]
    found = [f for f in found if f]
    return f"{EXIT_ZERO_LABEL}: {str(found[-1].get('evidence') or found[-1].get('kind'))[:160]}" if found else ""


def semantic_change(result: dict) -> tuple[str, ...]:
    """harness-v1.7 (R6, D-44). The SEMANTIC_CALLS names touched by the model patches the passing run carried: every model attempt the tamper gate
    passed, up to the passing one, that was either not a candidate of a round or the round's chosen candidate (a candidate the adjudicator did
    not choose was never applied). Errs on the side of marking: a patch later superseded still counts. Empty unless RUNS_AFTER_REPAIR."""
    from app.services import tamper_gate  # pure; imported here so the ladder's import list stays the taxonomy alone

    if result.get("verdict") != "RUNS_AFTER_REPAIR":
        return ()
    attempts = list(result.get("attempts") or ())
    passed_at = max((i for i, a in enumerate(attempts) if attempt_passed(a)), default=None)
    if passed_at is None:
        return ()
    found: list[str] = []
    for a in attempts[: passed_at + 1]:
        if a.get("origin") != "model" or a.get("gate_decision") != "PASS" or not (a.get("diff_text") or "").strip():
            continue
        if a.get("candidate") is not None and a.get("chosen") is not True:
            continue
        stored = a.get("semantic_change")
        for name in (stored if isinstance(stored, (list, tuple)) else tamper_gate.semantic_change_calls(a.get("diff_text") or "")):
            if name not in found:
                found.append(name)
    return tuple(found)


def review_findings(result: dict) -> list[dict]:
    """harness-v1.10 flag mode (owner, 2026-10-09): the behavioural findings of every patch the run ADOPTED (a model attempt the tamper gate passed that was
    either not a candidate of a round or the round's chosen candidate; a candidate the adjudicator did not choose was never applied) whose attempt the flag
    mode marked `flagged`. Any verdict: the patch keeps its harness-v1.9.0 verdict and the certificate carries REVIEW_REQUIRED. Records of the other modes
    (and of every harness before v1.10) carry no `flagged` and read as nothing."""
    out: list[dict] = []
    for a in result.get("attempts") or ():
        if not isinstance(a, dict) or a.get("gate_decision") != "PASS" or a.get("origin", "model") != "model":
            continue
        if a.get("candidate") is not None and a.get("chosen") is not True:
            continue
        record = a.get("behaviour")
        if not isinstance(record, dict) or record.get("mode") != "flag" or record.get("flagged") is not True or record.get("put_back"):
            continue
        trace = record.get("trace") if isinstance(record.get("trace"), dict) else {}
        for stage, found in (("static", record.get("static") or ()), ("trace", trace.get("findings") or ())):
            for f in found:
                if isinstance(f, dict) and f.get("reason"):
                    out.append({"reason": str(f["reason"]), "detail": str(f.get("detail") or "")[:300], "file": str(f.get("file") or ""),
                                "line": f.get("line") or 0, "stage": stage, "attempt_number": a.get("attempt_number"), "candidate": a.get("candidate")})
    return out


def review_required(result: dict) -> tuple[str, ...]:
    """The reason names of `review_findings`, each once, in the order found; empty when no adopted patch was flagged."""
    return tuple(dict.fromkeys(f["reason"] for f in review_findings(result)))


def review(result: dict) -> dict | None:
    """harness-v1.10 flag mode: the certificate's review flag, `{"status": "REVIEW_REQUIRED", "reasons", "findings", "note", "mode"}`, or None when no adopted
    patch was flagged. Advisory only: no verdict, rung or label above it depends on it."""
    found = review_findings(result)
    if not found:
        return None
    return {"status": "REVIEW_REQUIRED", "reasons": list(dict.fromkeys(f["reason"] for f in found)), "findings": found[:20], "note": REVIEW_NOTE, "mode": "flag"}


def resource_adapted(result: dict) -> str:
    """harness-v1.7 (R1 d): the label of the last resource_adapt step the run applied, or ''."""
    labels = [(a.get("time_machine_action") or {}).get("label") for a in (result.get("attempts") or ())
              if (a.get("time_machine_action") or {}).get("rule") == "resource_adapt"]
    labels = [label for label in labels if label]
    return labels[-1] if labels else ""


def _actions(result: dict, rule: str) -> list[dict]:
    return [(a.get("time_machine_action") or {}) for a in (result.get("attempts") or ()) if (a.get("time_machine_action") or {}).get("rule") == rule]


def memory_adapted(result: dict) -> str:
    """harness-v1.7 (R1 c): what the memory hook changed in a DataLoader, or '' (it changed nothing, or it never ran)."""
    changes = [c for act in _actions(result, "memory_hook") for c in (act.get("changes") or ()) if "->" in str(c)]
    return ("memory hook: " + ", ".join(dict.fromkeys(str(c) for c in changes))) if changes else ""


def dependency_change(result: dict) -> str:
    """harness-v1.7 (R5): the companion pin RERUN replaced, or ''. harness-v1.8 (T3, T2): also the apt package RERUN renamed, the `git://` lines it rewrote to
    `https://`, and the pre-release pin it replaced by its final release; each is a change to what the repository declared, so each is labelled."""
    parts: list[str] = []
    acts = [act for act in _actions(result, "companion_relax") if act.get("from") and act.get("to")]
    if acts:
        act = acts[-1]
        # harness-v1.7.1: what the swap pinned beside the replacement (Pillow for torchvision 0.4.0), with the repository's own line when it had one
        also = [f"{a.get('package')} {_pin_of(a.get('from'))}->{a.get('to')}" for a in (act.get("also") or ()) if a.get("to")]
        parts.extend([f"{act.get('package')} {act['from']}->{act['to']}", *also])
    for act in _actions(result, "apt_package_renamed"):
        if act.get("from") and act.get("to"):
            parts.append(f"apt {act['from']}->{act['to']}")
    for act in _actions(result, "git_protocol_rewrite"):
        n = len(act.get("lines") or ())
        parts.append(f"git:// -> https:// in {n} requirement line{'s' if n != 1 else ''}")
    for act in _actions(result, "prerelease_pin_relax"):
        if act.get("from") and act.get("to"):
            parts.append(f"{act.get('package')} {act['from']}->{act['to']}")
    return ("dependency change: " + ", ".join(parts)) if parts else ""


def _pin_of(line) -> str:
    """What the repository declared, from its requirements line: `9.0.0` for `Pillow==9.0.0`, `>=7.0` for `Pillow>=7.0`, `unpinned` for a bare `Pillow`,
    `not declared` when the file does not name the package (no line)."""
    if not line:
        return "not declared"
    found = re.match(r"^\s*[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[^\]]*\])?\s*(.*?)\s*(?:[;#].*)?$", str(line))
    spec = found.group(1) if found else str(line).strip()
    exact = re.fullmatch(r"===?\s*([^\s,]+)", spec)
    return exact.group(1) if exact else (spec or "unpinned")


def labels(result: dict) -> list[str]:
    """Every harness-v1.7 label of a run, in a fixed order: semantic change (R6), RESOURCE-ADAPTED (R1 d), memory hook (R1 c), dependency change (R5),
    then exit 0 overruled (harness-v1.7.2, D-46), then REVIEW REQUIRED with its reasons (harness-v1.10 flag mode, advisory)."""
    out = ["semantic change"] if semantic_change(result) else []
    out += [x for x in (resource_adapted(result), memory_adapted(result), dependency_change(result), exit_zero_overruled(result)) if x]
    review = review_required(result)
    if review:
        out.append(f"{REVIEW_LABEL}: {', '.join(review)}")
    return out


def verdict_label(result: dict) -> str:
    """The verdict as the certificate, the dashboard and the ladder print it: the code, with every label of `labels` beside it."""
    verdict = str(result.get("verdict") or "")
    notes = labels(result)
    return f"{verdict} ({'; '.join(notes)})" if notes else verdict


def compute(result: dict) -> dict:
    """The four rungs for one stored result dict (see the module docstring). Missing fields read as empty."""
    verdict = result.get("verdict")
    chain = list(result.get("error_chain") or ())
    attempts = list(result.get("attempts") or ())

    entrypoint_runs = verdict in RUNS_VERDICTS

    first_error_cleared = False
    first_error_cleared_by: str | None = None
    if chain:
        cleared_by = chain[0].get("cleared_by")
        if cleared_by is None and verdict == "RUNS_AFTER_REPAIR" and len(chain) == 1:
            # Records written before harness-v1.6 keep `cleared_by: None` on the one failure the run then passed without
            # (error_chain.clear_last did not exist): the verdict says it was cleared; the attempt that passed says by whom.
            # Only RUNS_AFTER_REPAIR (v1.6 review, defect 6): a RUNS_CLEAN record whose as-is rerun passed (a flaky
            # repository) cleared nothing.
            passed = [a for a in attempts if attempt_passed(a)]
            cleared_by = passed[-1].get("attempt_number") if passed else None
            first_error_cleared = True
        else:
            first_error_cleared = cleared_by is not None
        if first_error_cleared and cleared_by is not None:
            # Several attempts share a number (the time machine and every deterministic step are attempt 0, v1.6 review,
            # defect 7): the one that PASSED cleared the failure; failing that, the last with that number.
            numbered = [a for a in attempts if a.get("attempt_number") == cleared_by]
            passed = [a for a in numbered if attempt_passed(a)]
            attempt = passed[-1] if passed else (numbered[-1] if numbered else None)
            first_error_cleared_by = attempt.get("origin") if attempt is not None else None

    env_resolved = entrypoint_runs or (bool(chain) and chain[-1].get("class") not in ENVIRONMENT_CLASSES)

    out = {
        "first_error_cleared": first_error_cleared,
        "first_error_cleared_by": first_error_cleared_by,
        "env_resolved": env_resolved,
        "entrypoint_runs": entrypoint_runs,
    }
    flagged = semantic_change(result)
    if flagged:
        out["semantic_change"] = list(flagged)
    for key, value in (("resource_adapted", resource_adapted(result)), ("memory_adapted", memory_adapted(result)),
                       ("dependency_change", dependency_change(result)), ("exit_zero_overruled", exit_zero_overruled(result))):
        if value:
            out[key] = value
    found = review_findings(result)
    if found:  # harness-v1.10 flag mode: advisory, never a change to the verdict or to a rung above
        out["review_required"] = list(dict.fromkeys(f["reason"] for f in found))
        out["review_findings"] = found[:20]
        out["review_note"] = REVIEW_NOTE
    return out
