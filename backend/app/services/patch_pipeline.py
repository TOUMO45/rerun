"""From what the repair model wrote to a diff that `git apply` accepts, BEFORE the tamper gate (harness-v1.3.3, D-1/D-2).

Corpus-v2 on harness-v1.3.2: 16 model-written source patches, 0 applied. The failures were mechanical, not about the code:
hand-counted hunk headers (`Hunk is shorter than expected`), header-only diffs with no hunk, literal `\\n` escapes in the JSON
string, and context lines copied from memory instead of from the file. This module keeps the model's INTENT (which lines to
remove, which to add, where) and rebuilds the mechanics:

  1. `code_diff` is read leniently: fences and JSON escapes are undone, hunk line counts are ignored, a blank line inside a
     hunk is a blank context line.
  2. Each hunk is LOCATED in the real file: exact match of its context+removed lines (trailing whitespace ignored), else
     whitespace-normalized, else a fuzzy match that must still agree with every removed line. The claimed line number is only
     a tie-breaker. The removed lines must really exist; context is taken from the file, not from the model.
  3. The new file is built in memory and a canonical unified diff is regenerated with difflib (correct counts, correct
     `\\ No newline at end of file` markers).
  4. The result must pass `git apply --check` against the real tree. Only then does the tamper gate see it, and the gate
     sees exactly the text that will be applied.

The model may instead send `file_edits` ([{"path","old","new"}], `old` must occur exactly once) or `file_replacements`
([{"path","content"}], whole-file): same steps 3-4. A problem is raised as PatchProblem with a message written for the model
(what failed, and the file's own lines nearest to what it expected), which the orchestrator shows it once, in the same attempt.

Nothing here decides whether a change is acceptable: that stays with tamper_gate.check_patch. Paths must stay inside `root`
(no absolute paths, `..`, symlinks).
"""

from __future__ import annotations

import difflib
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from app.services import timeouts

MAX_FILE_BYTES = 400_000
FUZZY_MIN_RATIO = 0.85
_HUNK_RE = re.compile(r"^@@ -(\S+) \+(\S+) @@")  # counts are ignored; `@@ -???,?? +???,?? @@` (unknown) is accepted
_PLACEHOLDER_RE = re.compile(r"omitted for brevity|\.\.\. *\(|^\s*\.\.\.\s*$|rest of (the )?(file|code|function)", re.IGNORECASE)
_FENCE_RE = re.compile(r"^\s*```[\w-]*\s*$")


class PatchProblem(ValueError):
    """The change cannot be turned into an applicable diff. `str(exc)` is addressed to the model."""


@dataclass(frozen=True)
class PatchResolution:
    diff: str  # canonical unified diff, verified with `git apply --check`
    paths: tuple[str, ...]
    notes: tuple[str, ...] = ()  # how each hunk was located (exact / whitespace / fuzzy) or which format was used
    source: str = "code_diff"  # code_diff | file_edits | file_replacements


@dataclass
class _Hunk:
    old_start: int
    lines: list[tuple[str, str]] = field(default_factory=list)  # (' ' | '-' | '+', text without the marker)
    old_count: int | None = None  # as claimed in the @@ header (None when unknown, e.g. "-???,??"); a consistency hint only
    new_count: int | None = None

    @property
    def changes(self) -> bool:
        return any(kind in "+-" for kind, _ in self.lines)


@dataclass
class _FilePatch:
    path: str
    hunks: list[_Hunk] = field(default_factory=list)


# --- reading the model's diff ------------------------------------------------------------------------------------------


def _clean_text(text: str) -> str:
    text = text.strip("\n")
    if "\n" not in text and "\\n" in text:
        # the JSON string was double-escaped: real newlines arrived as the two characters backslash-n
        text = text.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"')
    lines = [ln for ln in text.splitlines() if not _FENCE_RE.match(ln)]
    return "\n".join(lines)


def _header_path(raw: str) -> str | None:
    path = raw.strip().split("\t", 1)[0].strip()
    if path == "/dev/null":
        return None
    if path.startswith(("a/", "b/")):
        path = path[2:]
    return path.replace("\\", "/")


def parse_lenient(diff_text: str) -> list[_FilePatch]:
    lines = _clean_text(diff_text).split("\n")
    files: list[_FilePatch] = []
    current: _FilePatch | None = None
    hunk: _Hunk | None = None
    i = 0
    while i < len(lines):
        line = lines[i]
        # `---` alone on a line, then `a/<path>`, then `+++ b/<path>`: the model wrote a newline where the header has a space
        if line.strip() == "---" and i + 2 < len(lines) and lines[i + 1].startswith(("a/", "b/")) and lines[i + 2].startswith("+++ "):
            line, lines[i + 1] = "--- " + lines[i + 1], lines[i + 2]
            lines[i] = line
            del lines[i + 2]
        if line.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
            path = _header_path(lines[i + 1][4:])
            if path is None or _header_path(line[4:]) is None:
                raise PatchProblem("the diff creates or deletes a file ('/dev/null' header); only edits to existing files are supported")
            current, hunk = _FilePatch(path), None
            files.append(current)
            i += 2
            continue
        match = _HUNK_RE.match(line)
        if match and current is not None:
            first = re.match(r"\d+", match.group(1))
            counts = [re.match(r"\d+,(\d+)$", part) for part in (match.group(1), match.group(2).lstrip("+"))]
            hunk = _Hunk(int(first.group(0)) if first else 1, old_count=int(counts[0].group(1)) if counts[0] else None,
                         new_count=int(counts[1].group(1)) if counts[1] else None)
            current.hunks.append(hunk)
            i += 1
            continue
        if hunk is not None:
            if line.startswith("\\"):
                pass  # "\ No newline at end of file"
            elif line.startswith("+"):
                hunk.lines.append(("+", line[1:]))
            elif line.startswith("-"):
                hunk.lines.append(("-", line[1:]))
            elif line.startswith(" "):
                hunk.lines.append((" ", line[1:]))
            else:
                hunk.lines.append((" ", line))  # the model dropped the leading space of a context line (or left it empty)
        i += 1
    for f in files:
        for h in f.hunks:
            # a trailing blank line produced by the final newline is not a context line
            while h.lines and h.lines[-1] == (" ", ""):
                h.lines.pop()
            # A hunk with no '+'/'-' at column 0 that has lines like " -old" / " +new" is a hunk whose markers were indented one
            # space (corpus-v2 entry 17 attempt 2). It is read that way ONLY because, read literally, it would change nothing.
            if not h.changes and any(text[:1] in "+-" and len(text) > 1 and kind == " " for kind, text in h.lines):
                h.lines = [(text[0], text[1:]) if kind == " " and text[:1] in "+-" and len(text) > 1 else (kind, text)
                           for kind, text in h.lines]
    return files


# --- locating a hunk in the real file ------------------------------------------------------------------------------------


def _norm_ws(line: str) -> str:
    return " ".join(line.split())


def _strip_eol(line: str) -> str:
    return line.rstrip("\r\n")


def _candidates(file_lines: list[str], block: list[str], key) -> list[int]:
    k = len(block)
    wanted = [key(b) for b in block]
    return [i for i in range(0, len(file_lines) - k + 1) if [key(_strip_eol(x)) for x in file_lines[i : i + k]] == wanted]


def _nearest(indices: list[int], hint: int) -> int:
    return min(indices, key=lambda i: (abs(i - hint), i))


def _locate(file_lines: list[str], block: list[str], removed: list[tuple[int, str]], hint: int) -> tuple[int, str]:
    """(start index, how) of `block` (context + removed lines, in order) in `file_lines`, or raise LookupError."""
    if not block:
        return min(max(hint, 0), len(file_lines)), "insertion"
    for key, how in ((lambda s: s.rstrip(), "exact"), (_norm_ws, "whitespace-normalized")):
        found = _candidates(file_lines, block, key)
        if found:
            return _nearest(found, hint), how
    # fuzzy: best window of the same length whose REMOVED lines each still agree (they are what will be deleted)
    k = len(block)
    target = [_norm_ws(b) for b in block]
    best: tuple[float, int] | None = None
    for i in range(0, len(file_lines) - k + 1):
        window = [_norm_ws(_strip_eol(x)) for x in file_lines[i : i + k]]
        ratio = difflib.SequenceMatcher(None, "\n".join(target), "\n".join(window), autojunk=False).ratio()
        if ratio < FUZZY_MIN_RATIO:
            continue
        if any(difflib.SequenceMatcher(None, target[j], window[j], autojunk=False).ratio() < 0.9 for j, _ in removed):
            continue
        score = ratio - min(abs(i - hint), 500) / 100000.0  # the claimed line number only breaks ties
        if best is None or score > best[0]:
            best = (score, i)
    if best is not None:
        return best[1], "fuzzy"
    raise LookupError


def _nearest_lines(file_lines: list[str], block: list[str], hint: int) -> str:
    """The file's own lines nearest to what the hunk expected, for the model's retry."""
    wanted = _norm_ws(" ".join(block[:3])) if block else ""
    best_i, best_r = max(hint - 1, 0), -1.0
    for i in range(0, max(len(file_lines), 1)):
        r = difflib.SequenceMatcher(None, wanted, _norm_ws(_strip_eol(file_lines[i]))).ratio() if wanted else 0.0
        if r > best_r:
            best_i, best_r = i, r
    lo, hi = max(best_i - 2, 0), min(best_i + 10, len(file_lines))
    return "\n".join(f"{n + 1:5d}: {_strip_eol(file_lines[n])}" for n in range(lo, hi))


# --- building the new file and the canonical diff --------------------------------------------------------------------------


# harness-v1.3.4 (D-18): names under which RERUN's own resolved lock may appear to the model; it is edited through env_delta only.
RESERVED_LOCK_NAMES = frozenset({".rerun-requirements.txt", "RERUN-managed lock (edit via env_delta only)", "rerun-managed lock"})


def _read(root: Path, rel: str) -> tuple[Path, str]:
    if rel.strip().lower() in {n.lower() for n in RESERVED_LOCK_NAMES} or rel.strip().lower().startswith("rerun-managed lock"):
        raise PatchProblem(
            f"{rel!r} is RERUN's managed lock, not a repository file: it cannot be edited with file_edits / code_diff; "
            "change packages with env_delta (pin / add / remove / pip_git)"
        )
    candidate = root / rel
    if not rel or rel.startswith(("/", "\\")) or ".." in Path(rel).parts or re.match(r"^[A-Za-z]:", rel):
        raise PatchProblem(f"path {rel!r} is not a repo-relative path inside the repository")
    parts = Path(rel).parts
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise PatchProblem(f"path {rel!r} goes through a symlink")
    try:
        resolved = candidate.resolve()
        if root.resolve() not in resolved.parents:
            raise PatchProblem(f"path {rel!r} resolves outside the repository")
    except OSError as exc:
        raise PatchProblem(f"path {rel!r} cannot be resolved: {exc}") from exc
    if not candidate.is_file():
        raise PatchProblem(f"{rel!r} is not an existing file in the repository (only edits to existing files are supported)")
    data = candidate.read_bytes()
    if len(data) > MAX_FILE_BYTES:
        raise PatchProblem(f"{rel!r} is larger than {MAX_FILE_BYTES} bytes")
    return candidate, data.decode("utf-8", errors="replace")


def _eol_of(text: str) -> str:
    return "\r\n" if text.count("\r\n") > text.count("\n") / 2 and "\r\n" in text else "\n"


def _apply_hunks(rel: str, original: str, hunks: list[_Hunk]) -> tuple[str, list[str]]:
    file_lines = original.splitlines(keepends=True)
    eol = _eol_of(original)
    edits: list[tuple[int, int, list[str]]] = []  # (start, length, replacement lines)
    notes: list[str] = []
    for number, hunk in enumerate(hunks, start=1):
        block = [text for kind, text in hunk.lines if kind in " -"]
        position = 0
        removed = []
        for kind, text in hunk.lines:
            if kind in " -":
                if kind == "-":
                    removed.append((position, text))
                position += 1
        if not hunk.changes:
            notes.append(f"{rel} hunk {number}: no '+' or '-' lines, skipped")
            continue
        placeholder = next((t for _, t in hunk.lines if _PLACEHOLDER_RE.search(t)), None)
        if placeholder is not None:
            raise PatchProblem(
                f"hunk {number} of {rel} contains a placeholder instead of code ({placeholder.strip()[:60]!r}); every line of a hunk must be "
                "a real line: context and removed lines copied from the file, added lines written out in full"
            )
        added = sum(1 for kind, _ in hunk.lines if kind == "+")
        removed_count = sum(1 for kind, _ in hunk.lines if kind == "-")
        if removed_count and not added and hunk.old_count and hunk.new_count and hunk.new_count >= hunk.old_count:
            raise PatchProblem(
                f"hunk {number} of {rel} removes {removed_count} line(s) and adds none, but its header says it replaces {hunk.old_count} line(s) "
                f"with {hunk.new_count}: the replacement lines are missing. Write the new lines with a '+' marker, or use file_edits."
            )
        try:
            start, how = _locate(file_lines, block, removed, hunk.old_start - 1)
        except LookupError:
            raise PatchProblem(
                f"hunk {number} of {rel}: the lines it keeps and removes do not occur in the file as written. "
                f"The file's own lines nearest to what you expected are:\n{_nearest_lines(file_lines, block, hunk.old_start)}\n"
                "Copy the lines you keep/remove exactly from the file content you were shown."
            ) from None
        replacement: list[str] = []
        cursor = start
        for kind, text in hunk.lines:
            if kind == " ":
                replacement.append(file_lines[cursor])
                cursor += 1
            elif kind == "-":
                cursor += 1
            else:
                replacement.append(text + eol)
        edits.append((start, len(block), replacement))
        notes.append(f"{rel} hunk {number}: {how} match at line {start + 1}")
    if not edits:
        raise PatchProblem(f"none of the hunks of {rel} changes anything (no '+' or '-' lines)")
    edits.sort(key=lambda e: e[0])
    for (s1, l1, _), (s2, _l2, _) in zip(edits, edits[1:]):
        if s1 + l1 > s2:
            raise PatchProblem(f"two hunks of {rel} overlap; merge them into one hunk")
    for start, length, replacement in reversed(edits):
        file_lines[start : start + length] = replacement
    if file_lines and not file_lines[-1].endswith(("\n", "\r")) and original.endswith(("\n", "\r")):
        file_lines[-1] += eol
    return "".join(file_lines), notes


def canonical_diff(rel: str, old_text: str, new_text: str) -> str:
    """A unified diff of `rel` with correct hunk counts and `\\ No newline at end of file` markers."""
    out = []
    for line in difflib.unified_diff(
        old_text.splitlines(keepends=True), new_text.splitlines(keepends=True), fromfile=f"a/{rel}", tofile=f"b/{rel}", n=3
    ):
        out.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    return "".join(out)


def git_apply_check(root: Path, diff: str) -> str | None:
    """None if `git apply --check` accepts `diff` against the real tree (nothing is modified), else git's error text."""
    # Bytes, not text=True: on Windows text mode turns every LF of the patch into CR LF and `git apply` then sees
    # context lines that no LF file contains ("patch does not apply" for a patch that is correct).
    proc = subprocess.run(
        ["git", "apply", "--check", "--whitespace=nowarn", "-"], cwd=root, input=diff.encode("utf-8"), capture_output=True,
        timeout=timeouts.GIT_LOCAL_S,
    )
    return None if proc.returncode == 0 else (proc.stderr.decode("utf-8", "replace").strip() or f"git apply exited {proc.returncode}")


# --- entry points ------------------------------------------------------------------------------------------------------------


def _finish(root: Path, rewritten: dict[str, tuple[str, str]], notes: list[str], source: str) -> PatchResolution:
    chunks = []
    for rel, (old, new) in rewritten.items():
        if old == new:
            raise PatchProblem(f"the change to {rel} leaves the file identical")
        chunks.append(canonical_diff(rel, old, new))
    diff = "".join(chunks)
    error = git_apply_check(root, diff)
    if error:
        raise PatchProblem(f"the rebuilt patch does not pass `git apply --check`: {error}")
    return PatchResolution(diff, tuple(rewritten), tuple(notes), source)


def from_diff(root: Path, diff_text: str) -> PatchResolution:
    files = parse_lenient(diff_text)
    if not files:
        raise PatchProblem("the diff contains no file changes (expected `--- a/<path>` / `+++ b/<path>` headers and @@ hunks)")
    rewritten: dict[str, tuple[str, str]] = {}
    notes: list[str] = []
    for patch in files:
        if not patch.hunks:
            raise PatchProblem(f"the diff for {patch.path} has headers but no hunks (@@ ... @@ followed by the changed lines)")
        if patch.path in rewritten:
            raise PatchProblem(f"{patch.path} appears twice in one diff")
        _, original = _read(root, patch.path)
        new_text, file_notes = _apply_hunks(patch.path, original, patch.hunks)
        rewritten[patch.path] = (original, new_text)
        notes.extend(file_notes)
    return _finish(root, rewritten, notes, "code_diff")


def from_file_edits(root: Path, edits: list[dict]) -> PatchResolution:
    rewritten: dict[str, tuple[str, str]] = {}
    notes: list[str] = []
    for n, edit in enumerate(edits, start=1):
        if not isinstance(edit, dict) or not all(isinstance(edit.get(k), str) for k in ("path", "old", "new")):
            raise PatchProblem(f"file_edits[{n}] must be an object with string fields path, old, new")
        rel = _header_path(edit["path"]) or ""
        _, original = _read(root, rel)
        text = rewritten[rel][1] if rel in rewritten else original
        old, new = edit["old"], edit["new"]
        if not old:
            raise PatchProblem(f"file_edits[{n}].old is empty")
        count = text.count(old)
        if count == 0:
            # tolerate trailing-whitespace / indentation noise: match by whitespace-normalized lines
            lines = text.splitlines(keepends=True)
            block = old.strip("\n").splitlines()
            found = _candidates(lines, block, _norm_ws) if block else []
            if len(found) != 1:
                raise PatchProblem(
                    f"file_edits[{n}].old does not occur in {rel} exactly as written. Nearest lines:\n"
                    f"{_nearest_lines(lines, block, 1)}"
                )
            start = found[0]
            eol = _eol_of(text)
            lines[start : start + len(block)] = [ln + eol for ln in new.strip("\n").splitlines()]
            text = "".join(lines)
        elif count > 1:
            raise PatchProblem(f"file_edits[{n}].old occurs {count} times in {rel}; include more surrounding lines so it is unique")
        else:
            text = text.replace(old, new, 1)
        rewritten[rel] = (original if rel not in rewritten else rewritten[rel][0], text)
        notes.append(f"{rel}: file_edits[{n}] replaced 1 occurrence")
    return _finish(root, rewritten, notes, "file_edits")


def from_file_replacements(root: Path, replacements: list[dict]) -> PatchResolution:
    rewritten: dict[str, tuple[str, str]] = {}
    for n, item in enumerate(replacements, start=1):
        if not isinstance(item, dict) or not all(isinstance(item.get(k), str) for k in ("path", "content")):
            raise PatchProblem(f"file_replacements[{n}] must be an object with string fields path, content")
        rel = _header_path(item["path"]) or ""
        _, original = _read(root, rel)
        content = item["content"]
        if len(content) > MAX_FILE_BYTES:
            raise PatchProblem(f"file_replacements[{n}].content is larger than {MAX_FILE_BYTES} bytes")
        eol = _eol_of(original)
        if eol == "\r\n":
            content = content.replace("\r\n", "\n").replace("\n", "\r\n")
        if original.endswith("\n") and not content.endswith("\n"):
            content += eol
        rewritten[rel] = (original, content)
    return _finish(root, rewritten, [f"{p}: whole-file replacement" for p in rewritten], "file_replacements")


def resolve_patch(root: Path, *, diff_text: str | None = None, file_edits: list[dict] | None = None,
                  file_replacements: list[dict] | None = None) -> PatchResolution:
    """One resolution for whichever format(s) the model used; several formats in one reply are refused (ambiguous)."""
    given = [name for name, value in (("code_diff", diff_text), ("file_edits", file_edits), ("file_replacements", file_replacements))
             if value]
    if len(given) != 1:
        raise PatchProblem(
            "send exactly one of code_diff, file_edits, file_replacements" if given else "no code change was given"
        )
    if diff_text:
        return from_diff(root, diff_text)
    if file_edits:
        return from_file_edits(root, file_edits)
    return from_file_replacements(root, file_replacements or [])
