"""harness-v1.7.2 (D-47): a repair patch written with the wrong indentation for its file.

PURE. No network, no model call, no filesystem. NOT sandbox-touching.

The evidence. Live UI run of DEV #15 (`YuliaRubanova/latent_ode`, runs/live_ui/2026-10-05_dev15_latent_ode_api_certificate.json): `run_models.py` is
indented with TABS. Nemotron Super proposed six patches (all replacing the `raise Exception("Model not specified")` branch with a default model, or
setting a default flag after `parse_args()`), every one written with SPACES; the tamper gate refused all six as UNPARSEABLE_PATCH ("inconsistent use of
tabs and spaces", "unexpected indent", "unindent does not match any outer indentation level").

Two deterministic changes:

  1. `describe(text)`: the repair prompt names the target file's indentation ("TABS" or "N spaces"), so the model is told before it writes.
  2. `normalise_patch(diff, originals)`: BEFORE the tamper gate, when a patched .py file fails to parse with an IndentationError (TabError included)
     and the file's convention (`detect`) differs from the patch's (the file is tab-indented and the added lines use spaces, or the file uses N spaces
     per level and the added lines another unit), the ADDED lines' leading whitespace is rewritten to the file's convention and the parse is tried
     once more. Each changed group of lines (difflib opcodes between the original and the patched file) is placed at the level of the file line it
     replaces (the first non-blank removed line; for a pure insertion, the next non-blank line of the file), and keeps the model's own relative
     structure: level = anchor + (spaces - spaces of the group's first statement line) / the group's unit (the gcd of those differences). Lines inside a
     bracket or after a backslash (continuation lines) go one level under their statement; a line inside a string literal is never touched; a
     whitespace-only added line becomes empty.

     Refused (the patch goes to the gate unchanged, and the gate refuses it as before) when: the parse error is not an indentation error; the file's
     convention cannot be read; a statement line's level is not a whole level >= 0 under that rule; an added line mixes tabs and spaces; the patch adds
     a whole new file; any non-whitespace character would change; or the result still does not parse. The gate then checks the NORMALISED patch with
     every other rule (deleted eval calls, stubs, reduced scale, swallowed exceptions, size), and that normalised diff is what is applied.

The attempt record carries `indentation_normalised` ({"file", "from", "to", "lines", "parse_error"} per file).
"""

from __future__ import annotations

import ast
import difflib
import io
import math
import tokenize
from collections import Counter
from dataclasses import dataclass

_TAB = "\t"


@dataclass(frozen=True)
class Indentation:
    kind: str  # "tabs" | "spaces"
    width: int = 1  # spaces per level ("spaces"); 1 for tabs

    def unit(self) -> str:
        return _TAB if self.kind == "tabs" else " " * self.width

    def label(self) -> str:
        return "tabs" if self.kind == "tabs" else f"{self.width} spaces"

    def level_of(self, whitespace: str) -> int | None:
        if self.kind == "tabs":
            return len(whitespace) if set(whitespace) <= {_TAB} else None
        if set(whitespace) <= {" "} and len(whitespace) % self.width == 0:
            return len(whitespace) // self.width
        return None


def detect(text: str) -> Indentation | None:
    """The file's indentation convention from its INDENT tokens (continuation lines and strings do not count), or None."""
    increments: list[str] = []
    try:
        stack = [""]
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.INDENT:
                previous = stack[-1]
                increments.append(tok.string[len(previous):] if tok.string.startswith(previous) else tok.string)
                stack.append(tok.string)
            elif tok.type == tokenize.DEDENT:
                stack.pop()
    except (tokenize.TokenError, IndentationError, SyntaxError):
        increments = []
        for line in text.splitlines():
            ws = line[: len(line) - len(line.lstrip(" \t"))]
            if ws and line.strip():
                increments.append(ws)
    if not increments:
        return None
    tabs = sum(1 for inc in increments if inc.startswith(_TAB))
    if tabs * 2 > len(increments):
        return Indentation("tabs")
    widths = Counter(len(inc) for inc in increments if inc and set(inc) <= {" "})
    if not widths:
        return None
    return Indentation("spaces", widths.most_common(1)[0][0])


def describe(text: str, path: str = "") -> str:
    """One line for the repair prompt naming the file's indentation, or '' when it cannot be read."""
    conv = detect(text)
    if conv is None:
        return ""
    name = f" of {path}" if path else ""
    if conv.kind == "tabs":
        return (f"Indentation{name}: TABS (one tab character per level; in a JSON string write a tab as \\t). Every line you add must be indented "
                "with tabs, at the level of the lines around it; a line indented with spaces does not parse in this file.")
    return f"Indentation{name}: {conv.width} spaces per level. Every line you add must use {conv.width} spaces per level, at the level of the lines around it."


def _line_states(lines: list[str]) -> list[str]:
    """For each line: "string" (it starts inside a string literal), "cont" (it starts inside brackets or after a backslash) or "stmt"."""
    states: list[str] = []
    depth, quote, continued = 0, "", False
    for line in lines:
        states.append("string" if quote else ("cont" if depth > 0 or continued else "stmt"))
        continued = False
        i, n = 0, len(line)
        while i < n:
            ch = line[i]
            if quote:
                if ch == "\\":
                    i += 2
                    continue
                if line.startswith(quote, i):
                    i += len(quote)
                    quote = ""
                    continue
                i += 1
                continue
            if ch == "#":
                break
            if ch in "\"'":
                quote = ch * 3 if line.startswith(ch * 3, i) else ch
                i += len(quote)
                continue
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth = max(depth - 1, 0)
            i += 1
        if quote and len(quote) == 1:
            quote = ""  # an unterminated one-line string: the parser will say so
        stripped = line.rstrip("\r\n")
        if stripped.endswith("\\") and not quote:
            continued = True
    return states


def _ws(line: str) -> str:
    return line[: len(line) - len(line.lstrip(" \t"))]


def _eol(line: str) -> str:
    return line[len(line.rstrip("\r\n")):]


def normalise_source(old: str, new: str) -> tuple[str, dict] | None:
    """(normalised new text, record) when `new` fails to parse ONLY because of its added lines' indentation and the normalisation parses, else None."""
    try:
        ast.parse(new)
        return None
    except IndentationError as exc:  # TabError is an IndentationError
        error = f"{type(exc).__name__}: {exc.msg} (line {exc.lineno})"
    except (SyntaxError, ValueError):
        return None
    conv = detect(old)
    if conv is None:
        return None
    old_lines, new_lines = old.splitlines(keepends=True), new.splitlines(keepends=True)
    states = _line_states(new_lines)
    out = list(new_lines)
    units: set[int] = set()
    changed = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False).get_opcodes():
        if tag not in ("replace", "insert"):
            continue
        group = [j for j in range(j1, j2) if new_lines[j].strip()]
        statements = [j for j in group if states[j] == "stmt"]
        if not statements:
            continue
        spaces = [j for j in statements if " " in _ws(new_lines[j])]
        if any(_TAB in _ws(new_lines[j]) and " " in _ws(new_lines[j]) for j in group if states[j] != "string"):
            return None  # a line that mixes tabs and spaces: no reading of it is safe
        if any(_TAB in _ws(new_lines[j]) for j in statements) and spaces:
            return None  # some statement lines in tabs, some in spaces
        if not spaces:
            continue  # the group already uses tabs (or no indentation)
        base = len(_ws(new_lines[statements[0]]))
        diffs = [abs(len(_ws(new_lines[j])) - base) for j in statements if len(_ws(new_lines[j])) != base]
        unit = math.gcd(*diffs) if diffs else (conv.width if conv.kind == "spaces" else 4)
        if conv.kind == "spaces" and (not diffs or unit == conv.width):
            continue  # a space file: only a patch whose own unit is readable AND differs from the file's is a convention mismatch
        anchor_line = next((line for line in old_lines[i1:i2] if line.strip()), None)
        if anchor_line is None:
            anchor_line = next((line for line in old_lines[i1:] if line.strip()), None)
        if anchor_line is None:
            anchor_line = next((line for line in reversed(old_lines[:i1]) if line.strip()), "")
        anchor = conv.level_of(_ws(anchor_line))
        if anchor is None:
            return None
        units.add(unit)
        statement_ws: str | None = None
        for j in range(j1, j2):
            line = new_lines[j]
            if states[j] == "string":
                continue
            if not line.strip():
                if line.rstrip("\r\n"):
                    out[j] = _eol(line)
                    changed += 1
                continue
            body = line.lstrip(" \t")
            if states[j] == "stmt":
                offset = len(_ws(line)) - base
                if offset % unit:
                    return None
                level = anchor + offset // unit
                if level < 0:
                    return None
                statement_ws = conv.unit() * level
                replacement = statement_ws + body
            else:
                replacement = (statement_ws if statement_ws is not None else conv.unit() * anchor) + conv.unit() + body
            if replacement != line:
                out[j] = replacement
                changed += 1
    if not changed:
        return None
    if len(out) != len(new_lines) or any(a.lstrip(" \t") != b.lstrip(" \t") for a, b in zip(out, new_lines) if a.strip() or b.strip()):
        return None  # never a non-whitespace change
    text = "".join(out)
    try:
        ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    source = ("spaces (unit " + "/".join(str(u) for u in sorted(units)) + ")") if units else "spaces"
    return text, {"from": source, "to": conv.label(), "lines": changed, "parse_error": error}


def normalise_patch(diff_text: str, originals: dict[str, str]) -> tuple[str, list[dict]] | None:
    """(normalised canonical diff, one record per normalised file) or None (nothing to normalise, or a normalisation is refused: see the module)."""
    from app.services import patch_pipeline, tamper_gate  # pure helpers; imported here so this module's import list stays the standard library

    prepared = tamper_gate.prepare_patch(diff_text)
    if prepared.patch_set is None or prepared.violations or prepared.added_paths:
        return None
    originals = {tamper_gate._normalize_header_path(key)[0] or key: value for key, value in originals.items()}
    patched = tamper_gate.patched_sources(diff_text, originals)
    if set(patched) != set(prepared.paths) or not set(prepared.paths) <= set(originals):
        return None
    records: list[dict] = []
    for path in prepared.paths:
        if not path.endswith(".py"):
            continue
        done = normalise_source(originals[path], patched[path])
        if done is not None:
            patched[path] = done[0]
            records.append({"file": path, **done[1]})
    if not records:
        return None
    return "".join(patch_pipeline.canonical_diff(path, originals[path], patched[path]) for path in prepared.paths), records
