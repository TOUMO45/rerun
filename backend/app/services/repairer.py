"""Repairer (RERUN directive §3 must-have #5, §5.4 repair loop). Nemotron
Super proposes a minimal unified diff to fix a classified failure.

This module NEVER decides whether a proposed patch is acceptable — that
is `tamper_gate.check_patch()`'s job, and only its job (§2.1: the gate is
pure/deterministic/no model call). `repairer.py`'s only responsibility is
turning (failure classification + the one file most likely at fault) into
a candidate diff for the gate to check. A rejected proposal still consumes
one of the 3 attempts in §5.4 — that bookkeeping belongs to whatever
orchestrates the loop (not yet built), using `cost_guard.py`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace

from app.services.classifier import Classification
from app.services.model_client import (
    UNTRUSTED_CONTENT_NOTICE,
    ModelCallError,
    ModelResponseParseError,
    call_json_model,
    untrusted_block,
)

# Output budget incl. reasoning tokens (model_client retries once at 2x).
# Largest of the roles: the answer itself is a unified diff.
REPAIR_MAX_TOKENS = 8192

_SYSTEM_PROMPT = """You are a careful, minimal-diff software repair assistant fixing a \
single classified failure in someone else's research code so it can execute. You will \
be shown the failure's taxonomy code, the evidence line, the tail of the failing run's \
log, the current build plan and dependency file(s), and the content of the one file \
most likely responsible.

You can repair at two layers — use whichever actually addresses the failure:
- CODE: a change to the repository's own files, in ONE of three forms (RERUN rebuilds and checks the diff itself, so
  you never count hunk lines):
    "file_edits": [{"path": "<repo-relative>", "old": "<lines copied exactly from the file>", "new": "<replacement>"}]
        -- PREFERRED: `old` must occur exactly once in the file you were shown.
    "file_replacements": [{"path": "<repo-relative>", "content": "<the complete new file>"}]
    "code_diff": "<a unified diff>"  (headers, @@ hunks, every line written out; no placeholders like '...')
- ENVIRONMENT: structured edits to the build plan ("env_delta") — the right layer for \
missing system libraries, compilers, unavailable or incompatible package versions, \
packages that are not on PyPI, or the wrong Python version. The repository's files are \
never edited for these; RERUN rebuilds the environment from your delta.
When the repair layer hint says ENVIRONMENT, strongly prefer an env_delta.
You are also shown every top-level module the repository imports and, when RERUN has
resolved one, the currently locked environment. Compare them and fix ALL missing
third-party packages in ONE env_delta — do not fix only the single module named in the
error, since each attempt is expensive and bounded.

Rules, non-negotiable:
- Propose the SMALLEST possible change that could plausibly fix this specific failure.
- NEVER delete or comment out a call to an evaluation/metric/assertion function.
- NEVER replace a real model/inference call with a stub, mock, or hardcoded value.
- NEVER reduce a dataset size, epoch count, or sample count from its declared default.
- NEVER add a broad `except:`/`except Exception: pass` around code that previously ran
  to completion.
- Prefer changing the target file shown to you. You may touch another file in the
  repository if the fix genuinely needs it, using repo-relative `a/<path>` / `b/<path>`
  headers — never absolute paths, `..`, renames, or deleting files. Never modify test
  files, the classifier, or the tamper gate. Every file you touch is checked.
- Keep the diff under 40 changed lines.
- env_delta ops (each change is an object):
  {"op": "pin", "package": "<pip name>", "version": "<exact version>"}
  {"op": "unpin", "package": "<pip name>"}
  {"op": "add", "package": "<pip name>", "version": "<exact version or null>"}
  {"op": "remove", "package": "<pip name>"}   (never a package the code imports)
  {"op": "pip_git", "package": "<name>", "git_url": "https://github.com/<owner>/<repo>", "commit": "<full 40-hex sha>"}
  {"op": "apt", "package": "<debian package, e.g. build-essential>"}
  {"op": "python", "version": "3.7|3.8|3.9|3.10|3.11|3.12|3.13"}
  {"op": "pip_no_build_isolation", "package": "<pip name already in the environment>"}
      (installs everything else first, then builds that one package with
      `pip install --no-build-isolation` — only for a package whose build step
      fails with "No module named X" while X is already in the locked environment)
  EVERY change also needs "justification" (one line) and "evidence": a string copied
  VERBATIM from the failing run's log shown to you. Never use any other URL (no data,
  weights, or archives); git sources must be pinned to a full commit sha. Only use a
  git URL and commit you were actually given as evidence — never invent one.

A separate deterministic system will reject your patch outright if it violates any of
these — so follow them exactly, don't rely on the checker to catch a shortcut.

References: web search results are given to you as a numbered list [1]..[k], each with its URL and a snippet. The field
"cited_sources" is REQUIRED: the numbers of the references you actually used for this change (cite only what you used;
RERUN records the URL of every cited reference with the change and shows the whole list as "consulted"). An empty list is
allowed ONLY together with "reason_no_citation": one sentence saying why none of the references applied.

If the section "NO TRACEBACK FOUND" is present, the failing run exited non-zero without any error text. Do NOT guess a code
fix: a code change that does anything but ADD diagnostics (print / logging / traceback / faulthandler) is rejected. Either add
diagnostics so the next run shows the error, or fix the environment if the head/tail of the output shows an environment cause.

The "RERUN-managed lock" shown to you is NOT a repository file: RERUN generates it and installs from it. Never target it with
file_edits / file_replacements / code_diff (refused); change packages with env_delta.

Respond with ONLY a single JSON object, no prose, no markdown fences:
{
  "file_edits": [<edits as above>] or null,
  "file_replacements": null,
  "code_diff": null,
  "env_delta": [<zero or more env changes as above>],
  "cited_sources": [<REQUIRED: numbers of the references you used, e.g. [2]>],
  "reason_no_citation": "<REQUIRED when cited_sources is empty: why no reference applied>",
  "explanation": "<one sentence: what you changed and why it addresses the evidence>"
}
Use at most ONE of file_edits / file_replacements / code_diff. Set them all to null and env_delta to [] if you cannot
propose a safe minimal fix.""" + UNTRUSTED_CONTENT_NOTICE


CITATION_RULE = (
    "Citation rule: if your change uses ANYTHING from a numbered reference above (a version number, a package name, a flag, a code "
    "line, an API name), you MUST list that reference's number in \"cited_sources\". If none of them contributed, give an empty list "
    "and \"reason_no_citation\"."
)


def candidate_followup(previous: list[str], candidate_number: int) -> str:
    """harness-v1.4.0-rc: the follow-up that asks for candidate `candidate_number` (2 or 3) of the same failure: a DIFFERENT fix from
    the candidates already proposed this round (summarized), or a decline."""
    listed = "\n".join(f"- candidate {i}: {summary[:400]}" for i, summary in enumerate(previous, start=1)) or "- (none proposed)"
    return (
        f"You are now proposing candidate {candidate_number} for the SAME failure. Candidates already proposed this round (each will "
        f"be tried in its own sandbox branch):\n{listed}\nPropose a DIFFERENT fix (a different file, line, package or approach), "
        "or decline with empty fields if you have no other safe minimal fix. Reply with the complete JSON object."
    )


@dataclass(frozen=True)
class RepairProposal:
    diff_text: str | None  # the code diff
    explanation: str
    declined: bool = False
    # Raw env_delta list from the model; parsed and gated by env_repair.
    env_delta: tuple = ()
    # True if the first reply was invalid JSON and the model was re-asked.
    parse_retried: bool = False
    # harness-v1.3.3: structured code changes (patch_pipeline builds and checks the diff) and the numbers of the web
    # results the model says it used (the orchestrator validates them against what was actually offered).
    file_edits: tuple = ()
    file_replacements: tuple = ()
    cited_sources: tuple = ()
    # harness-v1.3.4 (D-21): whether the model gave the (required) cited_sources field at all, and its reason for an empty one.
    cited_sources_given: bool = False
    reason_no_citation: str = ""

    @property
    def has_diff(self) -> bool:
        return self.has_code and not self.declined

    @property
    def has_code(self) -> bool:
        return bool(self.diff_text) or bool(self.file_edits) or bool(self.file_replacements)

    @property
    def has_change(self) -> bool:
        return not self.declined and (self.has_code or bool(self.env_delta))


def build_repair_user_prompt(
    classification: Classification,
    target_file_path: str,
    target_file_content: str,
    external_context: str | None = None,
    *,
    repair_layer: str = "code",
    build_plan: dict | None = None,
    dependency_files: dict[str, str] | None = None,
    log_tail: str = "",
    imported_modules: list[str] | None = None,
    followup: str | None = None,
    resolved_lock: list[str] | None = None,
    silent_failure: dict | None = None,
) -> str:
    parts = [
        f"Taxonomy code: {classification.code} ({classification.family})",
        f"Repair layer hint: {repair_layer.upper()}",
        # Evidence is a line of the repo's own stderr/stdout.
        "Evidence:",
        untrusted_block("failure evidence from the run's output", classification.evidence),
        f"Target file: {target_file_path}",
        "Current file content:",
        untrusted_block(f"content of {target_file_path}", target_file_content),
    ]
    if build_plan is not None:
        # Our own plan, but it embeds repo-derived names — keep it delimited.
        parts.append("Current build plan:")
        parts.append(untrusted_block("current build plan", json.dumps(build_plan, indent=2)))
    for name, content in (dependency_files or {}).items():
        if name.startswith("RERUN-managed lock"):
            parts.append(f"{name} (NOT a repository file; file_edits on it are refused; change packages with env_delta):")
            parts.append(untrusted_block("RERUN-managed lock", content[:4000]))
            continue
        parts.append(f"Dependency file {name}:")
        parts.append(untrusted_block(f"dependency file {name}", content[:4000]))
    if silent_failure is not None:
        # harness-v1.3.4 (D-19): the run exited non-zero with no error text. Head and tail of BOTH streams, the exit code, and the rule.
        parts.append(
            f"NO TRACEBACK FOUND — do not guess; first add diagnostics. The failing run exited with code {silent_failure.get('exit_code')} "
            "and printed no traceback, exception line or error block. First 40 and last 80 lines of each stream follow."
        )
        parts.append("stdout (head + tail):")
        parts.append(untrusted_block("failing run stdout head+tail", silent_failure.get("stdout") or "(empty)"))
        parts.append("stderr (head + tail):")
        parts.append(untrusted_block("failing run stderr head+tail", silent_failure.get("stderr") or "(empty)"))
    if log_tail:
        parts.append("Tail of the failing run's log (quote `evidence` from here verbatim):")
        parts.append(untrusted_block("failing run log tail", log_tail))
    if resolved_lock:
        parts.append("Environment currently installed (RERUN's resolved lock for the repository's era):")
        parts.append(untrusted_block("resolved lock", "\n".join(resolved_lock)))
    if imported_modules:
        # Every top-level module the repo's code imports (AST, never run), so
        # one env_delta can add ALL missing packages at once instead of one per
        # attempt (gpt-2 needed numpy AND tensorflow; each cost an attempt).
        parts.append("Top-level modules imported anywhere in the repository's code:")
        parts.append(untrusted_block("imported modules", ", ".join(imported_modules)))
    if external_context:
        parts.append("Additional context (cited dependency/environment evidence):")
        parts.append(untrusted_block("web search results (Tavily)", external_context))
        # harness-v1.4.0-rc (directive step 1.5): the snippets above are given to the candidate generator with this rule.
        parts.append(CITATION_RULE)
    if followup:
        parts.append(followup)
    return "\n".join(parts)


def parse_repair_response(raw: dict) -> RepairProposal:
    # "diff" is the pre-env-layer key; still accepted.
    diff_text = raw.get("code_diff", raw.get("diff"))
    explanation = str(raw.get("explanation", ""))
    env_delta = raw.get("env_delta")
    if env_delta in (None, "", {}, []):
        env_delta = []
    elif not isinstance(env_delta, list):
        # Malformed deltas are passed through so the env gate rejects them
        # visibly, rather than being dropped here.
        env_delta = [env_delta]
    has_code = diff_text is not None and bool(str(diff_text).strip())

    def _list(key):
        value = raw.get(key)
        if value in (None, "", {}, []):
            return ()
        return tuple(value) if isinstance(value, list) else (value,)  # a malformed value is kept: patch_pipeline refuses it visibly

    file_edits, file_replacements = _list("file_edits"), _list("file_replacements")
    cited = tuple(c for c in _list("cited_sources") if isinstance(c, int) and not isinstance(c, bool))
    if not has_code and not env_delta and not file_edits and not file_replacements:
        return RepairProposal(diff_text=None, explanation=explanation or "model declined to propose a fix", declined=True)
    return RepairProposal(
        diff_text=str(diff_text) if has_code else None, explanation=explanation, env_delta=tuple(env_delta),
        file_edits=file_edits, file_replacements=file_replacements, cited_sources=cited,
        cited_sources_given=isinstance(raw.get("cited_sources"), list), reason_no_citation=str(raw.get("reason_no_citation") or "").strip(),
    )


def citation_field_problem(proposal: RepairProposal, n_references: int) -> str | None:
    """None if the proposal's citation field satisfies the schema given `n_references` references were offered; else what is missing."""
    if proposal.declined or n_references <= 0:
        return None
    if not proposal.cited_sources_given:
        return "the required field \"cited_sources\" is missing"
    if not proposal.cited_sources and not proposal.reason_no_citation:
        return "\"cited_sources\" is empty and \"reason_no_citation\" is missing"
    return None


def propose_repair(
    client,
    model: str,
    classification: Classification,
    target_file_path: str,
    target_file_content: str,
    external_context: str | None = None,
    cost_guard=None,
    *,
    repair_layer: str = "code",
    build_plan: dict | None = None,
    dependency_files: dict[str, str] | None = None,
    log_tail: str = "",
    imported_modules: list[str] | None = None,
    followup: str | None = None,
    resolved_lock: list[str] | None = None,
    silent_failure: dict | None = None,
    n_references: int = 0,
) -> RepairProposal:
    """Ask Nemotron Super for one candidate patch. A model-call failure
    (bad credentials, timeout, unparseable JSON) is surfaced as a declined
    proposal rather than a crash, so the orchestrator can record the
    attempt and either retry or move toward BLOCKED per §5.4 — it must
    never silently retry forever or fabricate a diff.
    """
    user_prompt = build_repair_user_prompt(
        classification,
        target_file_path,
        target_file_content,
        external_context,
        repair_layer=repair_layer,
        build_plan=build_plan,
        dependency_files=dependency_files,
        log_tail=log_tail,
        imported_modules=imported_modules,
        followup=followup,
        resolved_lock=resolved_lock,
        silent_failure=silent_failure,
    )
    parse_retried = False
    for try_number in (1, 2):
        try:
            raw = call_json_model(
                client,
                model=model,
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                cost_guard=cost_guard,
                max_tokens=REPAIR_MAX_TOKENS,
            )
            break
        except ModelResponseParseError as exc:
            # Found live (gpt-2, 2026-09-24): Super's reply was invalid JSON
            # and the whole repair attempt was lost. One re-ask, inside this
            # same attempt — it does NOT consume a repair attempt (the
            # orchestrator counts propose_repair calls, not model calls).
            # response_format=json_object was tested live and did not help
            # (DECISIONS.md 2026-09-24), so this is the mechanism.
            if try_number == 2:
                return RepairProposal(
                    diff_text=None,
                    explanation=f"repair model reply was not valid JSON twice: {exc}",
                    declined=True,
                    parse_retried=True,
                )
            parse_retried = True
            first_line = str(exc).splitlines()[0][:200]
            user_prompt = (
                f"{user_prompt}\n\nYour previous reply could not be parsed as JSON ({first_line}). "
                "Reply again with ONLY the single JSON object described in the instructions — "
                "escape every newline, quote and backslash inside the code_diff string."
            )
        except ModelCallError as exc:
            return RepairProposal(diff_text=None, explanation=f"repair model call failed: {exc}", declined=True)

    proposal = parse_repair_response(raw)
    # harness-v1.3.4 (D-21): cited_sources is required whenever references were offered; one re-ask, same attempt, then the proposal
    # is kept with the omission recorded (a good fix is not thrown away for a missing field, but the record says it was missing).
    problem = citation_field_problem(proposal, n_references)
    if problem:
        try:
            raw = call_json_model(
                client, model=model, system_prompt=_SYSTEM_PROMPT,
                user_prompt=f"{user_prompt}\n\nYour previous reply was rejected: {problem}. {n_references} numbered references were given to "
                            "you. Reply again with the complete JSON object, with \"cited_sources\" listing the reference numbers you used, "
                            "or an empty list plus \"reason_no_citation\".",
                cost_guard=cost_guard, max_tokens=REPAIR_MAX_TOKENS,
            )
            again = parse_repair_response(raw)
            if citation_field_problem(again, n_references) is None:
                proposal = again
            else:
                proposal = replace(again, reason_no_citation=f"(not given by the model after a re-ask: {problem})")
        except (ModelResponseParseError, ModelCallError) as exc:
            proposal = replace(proposal, reason_no_citation=f"(not given by the model; re-ask failed: {str(exc)[:80]})")
        parse_retried = True
    return replace(proposal, parse_retried=parse_retried) if parse_retried else proposal
