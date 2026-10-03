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
"""

from __future__ import annotations

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
            passed = [a for a in attempts if a.get("exit_code") == 0]
            cleared_by = passed[-1].get("attempt_number") if passed else None
            first_error_cleared = True
        else:
            first_error_cleared = cleared_by is not None
        if first_error_cleared and cleared_by is not None:
            # Several attempts share a number (the time machine and every deterministic step are attempt 0, v1.6 review,
            # defect 7): the one that PASSED cleared the failure; failing that, the last with that number.
            numbered = [a for a in attempts if a.get("attempt_number") == cleared_by]
            passed = [a for a in numbered if a.get("exit_code") == 0]
            attempt = passed[-1] if passed else (numbered[-1] if numbered else None)
            first_error_cleared_by = attempt.get("origin") if attempt is not None else None

    env_resolved = entrypoint_runs or (bool(chain) and chain[-1].get("class") not in ENVIRONMENT_CLASSES)

    return {
        "first_error_cleared": first_error_cleared,
        "first_error_cleared_by": first_error_cleared_by,
        "env_resolved": env_resolved,
        "entrypoint_runs": entrypoint_runs,
    }
