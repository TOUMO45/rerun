"""harness-v1.8 (T7): a `file_edits` edit whose `old` was found by the whitespace-tolerant match has the indentation of its `new` re-based onto the
matched file lines, BEFORE the tamper gate.

The failing class, found in committed records (all five patches below are what the model really sent; the file is a short excerpt that keeps the
real lines, their real indentation and the real nesting of the target; the recorded files are CRLF, so every case runs in both line endings):

  * runs/live_scan/oos_v1.7.2/2026-10-05_njanakiev__openstreetmap-heatmap_api_certificate.json: three attempts refused as UNPARSEABLE_PATCH.
    Target `render_osm_data.py`, https://github.com/njanakiev/openstreetmap-heatmap at 77abf379fcfedda8d16fef0b350a305c2733edf2 (CRLF, 4 spaces).
    The model's `old` begins at a comment WITHOUT the line's indentation and carries its later lines 4 columns too deep (attempt 1 candidate 2);
    or starts 4 columns too deep (attempt 1 candidate 3); or is 10 columns too deep (attempt 2 candidate 1, whose first three edits already parse).
  * runs/corpus_v2_batch/harness-v1.5-final/test/20_XiaoxiaoGuo__fashion-retrieval.json: two attempts refused as UNPARSEABLE_PATCH ("unexpected
    indent", lines 192 and 65). Target `captioner/neuraltalk2/train.py`, https://github.com/XiaoxiaoGuo/fashion-retrieval at
    9ac8b2ca44f7aa16510384047b635ba093568165 (CRLF, 4 spaces). `old`/`new` are 16 columns (attempt 1 candidate 2) and 8 columns (attempt 3
    candidate 3, first edit) too deep.

Before T7 the resolver put `new` into the file as written, the file did not parse, the gate refused it, and indentation.normalise_patch (D-47,
tabs-vs-spaces) refused too, because the patch and the file use the same convention and only the absolute level is wrong. The "before" half of each
test below is the resolver with the re-basing step switched off; no network and no clone is needed (the originals are the excerpts)."""

from __future__ import annotations

import ast
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.services import indentation, patch_pipeline, tamper_gate
from app.services.orchestrator import _apply_diff_with_git
from app.services.patch_pipeline import resolve_patch
from test_v151_pins_and_removals import _fail, _ok, _pipeline

REPO_ROOT = Path(__file__).resolve().parents[2]
OSM_RECORD = REPO_ROOT / "runs" / "live_scan" / "oos_v1.7.2" / "2026-10-05_njanakiev__openstreetmap-heatmap_api_certificate.json"
FASHION_RECORD = REPO_ROOT / "runs" / "corpus_v2_batch" / "harness-v1.5-final" / "test" / "20_XiaoxiaoGuo__fashion-retrieval.json"

# --- excerpts of the two target files (the lines the recorded edits name, at their real indentation and nesting) -------------------------------

OSM_PATH = "render_osm_data.py"
OSM_EXCERPT = '''import bpy
import bmesh

def add_bars(grid, bm):
    for x in range(10):
        for y in range(10):
            if grid[x][y] > 0.001:
                T = 1
                if bpy.app.version < (2, 80, 0):
                    bmesh.ops.create_cube(bm, size=bar_width, matrix=T*S)
                else:
                    bmesh.ops.create_cube(bm, size=bar_width, matrix=T@S)

if __name__ == '__main__':
    res_x, res_y = 1280, 720

    # Remove all elements in scene
    if bpy.app.version < (2, 80, 0):
        bpy.ops.object.select_by_layer()
    else:
        bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

    # Set background color
    if bpy.app.version < (2, 80, 0):
        bpy.context.scene.world.horizon_color = (0.7, 0.7, 0.7)
    else:
        bpy.context.scene.world.color = (0.7, 0.7, 0.7)

    # Ambient occlusion
    bpy.context.scene.world.light_settings.use_ambient_occlusion = True
    if bpy.app.version < (2, 80, 0):
        bpy.context.scene.world.light_settings.samples = 8

    filepath = 'data/points_{}_{}_{}.json'.format(iso_a2, tag_key, tag_value)
'''

FASHION_PATH = "captioner/neuraltalk2/train.py"
FASHION_EXCERPT = '''def train(opt):
    infos = {}
    if opt.start_from is not None:
        infos = cPickle.load(f)
    if opt.load_best_score == 1:
        best_val_score = infos.get('best_val_score', None)

    model = models.setup(opt)
    model.cuda()

    while True:
        if iteration % opt.save_checkpoint_every == 0:
            best_flag = False
            if True: # if true
                if best_val_score is None or current_score > best_val_score:
                    best_flag = True

                if best_flag:
                    checkpoint_path = os.path.join(opt.checkpoint_path, 'model-best.pth')
                    torch.save(model.state_dict(), checkpoint_path)
                    print("model saved to {}".format(checkpoint_path))
                    with open(os.path.join(opt.checkpoint_path, 'infos_'+opt.id+'-best.pkl'), 'wb') as f:
                        cPickle.dump(infos, f)

        if epoch >= opt.max_epochs and opt.max_epochs != -1:
            break
'''


@dataclass(frozen=True)
class Recorded:
    name: str
    path: str
    excerpt: str
    edits: list
    recorded_violations: list
    rebased_edits: dict  # {line end: how many of the edits are re-based}; the others match exactly (an LF file: an exact substring)


def _unparseable(record: Path, attempts: str) -> list[tuple[str, list, list]]:
    data = json.loads(record.read_text(encoding="utf-8"))
    found = []
    for attempt in data["result"]["attempts"] if attempts == "result" else data["diffs"]:
        if "UNPARSEABLE_PATCH" not in json.dumps(attempt.get("gate_violations") or []):
            continue
        try:
            patch = json.loads(attempt["model_patch"])
        except (TypeError, ValueError):
            continue  # stored truncated at 6000 characters: not replayable (06_grigorisg9gr__rocgan)
        if patch.get("file_edits"):
            found.append((f"a{attempt['attempt_number']}c{attempt.get('candidate')}", patch["file_edits"], attempt["gate_violations"]))
    return found


def _recorded_cases() -> list[Recorded]:
    # a1c2/a1c3: all three edits are off by 4 columns (the third of a1c2 even parses as written, by accident: it lands inside the previous `else:`).
    # a2c1: the first three edits start at a comment without its indentation and are right otherwise (exact substrings in an LF file; in a CRLF
    # file the resolver finds them by the whitespace match and only a COMMENT line would move, which the parser does not read: not on offer, left as
    # written); only the fourth is off (by 10 columns).
    expected = {"a1c2": {"\n": 3, "\r\n": 3}, "a1c3": {"\n": 3, "\r\n": 3}, "a2c1": {"\n": 1, "\r\n": 1}}
    cases = [Recorded(f"osm-{n}", OSM_PATH, OSM_EXCERPT, edits, viol, expected[n]) for n, edits, viol in _unparseable(OSM_RECORD, "diffs")]
    expected_fashion = {"a1c2": {"\n": 1, "\r\n": 1}, "a3c3": {"\n": 1, "\r\n": 1}}  # a3c3: its second edit matches the file exactly
    cases += [Recorded(f"fashion-{n}", FASHION_PATH, FASHION_EXCERPT, edits, viol, expected_fashion[n])
              for n, edits, viol in _unparseable(FASHION_RECORD, "result")]
    return cases


CASES = _recorded_cases()
EOLS = pytest.mark.parametrize("eol", ["\n", "\r\n"], ids=["lf", "crlf"])


# --- helpers ---------------------------------------------------------------------------------------------------------------------------------


def _checkout(root: Path, files: dict[str, str], eol: str = "\n") -> Path:
    """A real git checkout (the harness's: autocrlf off) holding `files`, their line ends converted to `eol` (CRLF files stay CRLF)."""
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
    for key, value in (("core.autocrlf", "false"), ("core.eol", "lf")):
        subprocess.run(["git", "config", key, value], cwd=root, check=True, capture_output=True)
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.replace("\n", eol).encode("utf-8"))
    return root


def _resolve(work: Path, edits: list[dict], monkeypatch=None, *, rebase: bool = True):
    """The resolver as it is, or (rebase=False) as it was before T7: the re-basing step switched off."""
    if not rebase:
        with monkeypatch.context() as m:
            m.setattr(indentation, "rebase_edit", lambda *a, **k: None, raising=False)
            return resolve_patch(work, file_edits=edits)
    return resolve_patch(work, file_edits=edits)


def _patched(work: Path, rel: str, resolution) -> bytes:
    """The bytes of `rel` after the real apply step (git apply) of the resolved diff."""
    _apply_diff_with_git(work, resolution.diff)
    return (work / rel).read_bytes()


def _rebase_notes(resolution) -> list[str]:
    return [n for n in resolution.notes if "re-based" in n]


def _no_ws(text: str) -> str:
    return "".join(text.split())


# --- (a) the five recorded patches: before = unparseable and refused, after = parses ----------------------------------------------------------


def test_the_record_holds_the_five_replayable_unparseable_patches():
    assert [c.name for c in CASES] == ["osm-a1c2", "osm-a1c3", "osm-a2c1", "fashion-a1c2", "fashion-a3c3"]
    for case in CASES:
        assert [v["rule"] for v in case.recorded_violations] == ["UNPARSEABLE_PATCH"]
        assert case.path in json.dumps(case.edits)


@EOLS
@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_a_recorded_patch_did_not_parse_before_and_parses_after_re_basing(tmp_path, monkeypatch, case, eol):
    before_work = _checkout(tmp_path / "before", {case.path: case.excerpt}, eol)
    original = (before_work / case.path).read_text(encoding="utf-8")  # the gate is handed the file as the orchestrator reads it
    originals = {case.path: original}
    ast.parse(original)

    # BEFORE: the model's text is substituted as written; the file does not parse; the gate refuses it; D-47 refuses too
    old = _resolve(before_work, case.edits, monkeypatch, rebase=False)
    broken = _patched(before_work, case.path, old).decode("utf-8")
    with pytest.raises(IndentationError):
        ast.parse(broken)
    assert [v.rule for v in tamper_gate.check_patch(old.diff, originals).violations] == ["UNPARSEABLE_PATCH"]
    assert indentation.normalise_patch(old.diff, originals) is None
    assert not _rebase_notes(old)

    # AFTER: the same edits, the same file
    after_work = _checkout(tmp_path / "after", {case.path: case.excerpt}, eol)
    new = _resolve(after_work, case.edits)
    fixed_bytes = _patched(after_work, case.path, new)
    fixed = fixed_bytes.decode("utf-8")
    ast.parse(fixed)
    assert "UNPARSEABLE_PATCH" not in [v.rule for v in tamper_gate.check_patch(new.diff, originals).violations]
    assert indentation.normalise_patch(new.diff, originals) is None  # nothing left for D-47 to do: it parses
    assert len(_rebase_notes(new)) == case.rebased_edits[eol]  # (g) one note per re-based edit

    # (d) the file's line end is preserved, line for line
    assert fixed_bytes.count(b"\n") == fixed_bytes.count(b"\r\n" if eol == "\r\n" else b"\n")
    if eol == "\n":
        assert b"\r" not in fixed_bytes
    # (f) only leading whitespace differs from what the model wrote: every non-whitespace character is the model's, in the same order
    assert _no_ws(fixed) == _no_ws(broken)
    assert len(fixed.splitlines()) == len(broken.splitlines())
    for a, b in zip(fixed.splitlines(), broken.splitlines()):
        assert a.lstrip(" \t") == b.lstrip(" \t")
    # the file keeps its own convention: spaces only, a whole number of 4-space levels on every code line
    for line in fixed.splitlines():
        lead = line[: len(line) - len(line.lstrip(" \t"))]
        assert "\t" not in lead
        if line.strip() and not line.lstrip().startswith("#"):
            assert len(lead) % 4 == 0, line


@EOLS
@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_the_gate_sees_the_re_based_patch_and_judges_it_by_its_own_rules(tmp_path, case, eol):
    work = _checkout(tmp_path, {case.path: case.excerpt}, eol)
    originals = {case.path: (work / case.path).read_text(encoding="utf-8")}
    resolution = resolve_patch(work, file_edits=case.edits)
    gate = tamper_gate.check_patch(resolution.diff, originals)
    assert gate.canonical_diff.strip() == resolution.diff.strip() or gate.decision == "REJECT"
    assert not [v for v in gate.violations if v.rule == "UNPARSEABLE_PATCH"]
    # the notes say what was done, in the attempt record's own words
    notes = _rebase_notes(resolution)
    assert notes and all("harness-v1.8, T7" in n and "line(s) re-based onto the matched lines" in n for n in notes)
    assert notes[0].startswith(f"{case.path}: file_edits[")


# --- (b) an exact match is never changed ----------------------------------------------------------------------------------------------------

SMALL = "def f(x):\n    if x:\n        y = 1\n    return y\n"


@EOLS
def test_an_exact_match_is_substituted_as_written_even_when_its_new_text_does_not_parse(tmp_path, monkeypatch, eol):
    """`old` found verbatim (an exact substring in an LF file; line for line, indentation included, in a CRLF file): `new` is never touched."""
    edit = {"path": "m.py", "old": "    if x:\n        y = 1", "new": "    if x:\n        y = 2\n      z = 3"}  # `z` unindents to no outer level
    assert indentation.rebase_edit(["    if x:", "        y = 1"], edit["old"].splitlines(), edit["new"].splitlines()) is None  # nothing on offer
    work = _checkout(tmp_path / "now", {"m.py": SMALL}, eol)
    now = _resolve(work, [edit])
    before = _resolve(_checkout(tmp_path / "was", {"m.py": SMALL}, eol), [edit], monkeypatch, rebase=False)
    assert now.diff == before.diff and not _rebase_notes(now)
    assert "+      z = 3" in now.diff  # exactly as the model wrote it
    with pytest.raises(IndentationError):
        ast.parse(_patched(work, "m.py", now).decode("utf-8"))


def test_a_comment_started_mid_line_in_an_lf_file_is_an_exact_substring_and_is_not_re_based(tmp_path, monkeypatch):
    src = "def f(x):\n    # keep\n    if x:\n        y = 1\n    return y\n"
    edit = {"path": "m.py", "old": "# keep\n    if x:", "new": "# kept\n    if x:"}
    now = _resolve(_checkout(tmp_path / "now", {"m.py": src}), [edit])
    was = _resolve(_checkout(tmp_path / "was", {"m.py": src}), [edit], monkeypatch, rebase=False)
    assert now.diff == was.diff and not _rebase_notes(now) and "+    # kept" in now.diff


# --- (c) re-basing that does not produce a parsing file changes nothing --------------------------------------------------------------------


@EOLS
def test_when_re_basing_would_still_not_parse_the_patch_is_left_byte_identical(tmp_path, monkeypatch, eol):
    # the model's frame is the file's plus 4 (a consistent shift) but its `new` also has a real syntax error: an unclosed parenthesis
    edit = {"path": "m.py", "old": "        if x:\n            y = 1", "new": "        if x:\n            y = (1\n            z = 2"}
    matched = ["    if x:", "        y = 1"]
    assert indentation.rebase_edit(matched, edit["old"].splitlines(), edit["new"].splitlines()) is not None  # a re-basing IS on offer ...
    now = _resolve(_checkout(tmp_path / "now", {"m.py": SMALL}, eol), [edit])
    was = _resolve(_checkout(tmp_path / "was", {"m.py": SMALL}, eol), [edit], monkeypatch, rebase=False)
    assert now.diff == was.diff and now.notes == was.notes and not _rebase_notes(now)  # ... and refused: the moved text does not parse either
    assert now.diff.encode("utf-8") == was.diff.encode("utf-8")


@EOLS
def test_when_the_model_text_already_parses_it_is_left_as_written_even_if_it_could_be_re_based(tmp_path, monkeypatch, eol):
    """`old` was written 4 columns too deep but `new` is right: re-basing by `old`'s offset would BREAK it, so the text the gate always saw stays."""
    edit = {"path": "m.py", "old": "        if x:\n            y = 1", "new": "    if x:\n        y = 2\n        z = 3"}
    assert indentation.rebase_edit(["    if x:", "        y = 1"], edit["old"].splitlines(), edit["new"].splitlines()) is not None  # on offer
    now = _resolve(_checkout(tmp_path / "now", {"m.py": SMALL}, eol), [edit])
    was = _resolve(_checkout(tmp_path / "was", {"m.py": SMALL}, eol), [edit], monkeypatch, rebase=False)
    assert now.diff == was.diff and not _rebase_notes(now)
    ast.parse(_patched(_checkout(tmp_path / "applied", {"m.py": SMALL}, eol), "m.py", now).decode("utf-8"))


def test_a_comment_left_at_column_zero_that_parses_is_left_as_written(tmp_path, monkeypatch):
    """CRLF: `old` starts at a comment (no indentation) and its other lines are exact. The comment lands at column 0, which parses: untouched."""
    src = "def f(x):\n    # keep\n    if x:\n        y = 1\n    return y\n"
    edit = {"path": "m.py", "old": "# keep\n    if x:\n        y = 1", "new": "# kept\n    if x:\n        y = 2"}
    matched = ["    # keep", "    if x:", "        y = 1"]
    moved = indentation.rebase_edit(matched, edit["old"].splitlines(), edit["new"].splitlines())
    assert moved is not None and moved.lines[0] == "    # kept" and moved.structural == 0  # only the comment would move: not worth offering
    now = _resolve(_checkout(tmp_path / "now", {"m.py": src}, "\r\n"), [edit])
    was = _resolve(_checkout(tmp_path / "was", {"m.py": src}, "\r\n"), [edit], monkeypatch, rebase=False)
    assert now.diff == was.diff and not _rebase_notes(now) and "+# kept" in now.diff


def test_the_decision_is_per_file_a_parsing_file_is_left_as_written_beside_a_re_based_one(tmp_path, monkeypatch):
    """Two files in one patch: `a.py` does not parse as written and is re-based; `b.py` has an edit with a re-basing on offer (its `old` is 4 columns
    deep) but its `new` is right and parses as written, so it stays exactly as the model wrote it."""
    bad = {"path": "a.py", "old": "        if x:\n            y = 1", "new": "        if x:\n            y = 2"}
    fine = {"path": "b.py", "old": "        if x:\n            y = 1", "new": "    if x:\n        y = 2"}
    files = {"a.py": SMALL, "b.py": SMALL}
    now = _resolve(_checkout(tmp_path / "now", files), [bad, fine])
    was = _resolve(_checkout(tmp_path / "was", files), [bad, fine], monkeypatch, rebase=False)
    assert [n for n in now.notes if "re-based" in n] and all(n.startswith("a.py:") for n in _rebase_notes(now))
    chunks = {c.split("\n", 1)[0]: c for c in ("--- " + part for part in now.diff.split("--- ")[1:])}
    was_chunks = {c.split("\n", 1)[0]: c for c in ("--- " + part for part in was.diff.split("--- ")[1:])}
    assert chunks["--- a/b.py"] == was_chunks["--- a/b.py"]  # b.py: byte-identical to the resolver without the step
    assert chunks["--- a/a.py"] != was_chunks["--- a/a.py"] and "+        y = 2" in chunks["--- a/a.py"]


def test_a_file_that_is_not_python_is_never_re_based(tmp_path, monkeypatch):
    """Whitespace match in a YAML file: nothing here can check that it still parses, so the step is not even asked."""
    src = "steps:\n  - run: a\n  - run: b\n"
    edit = {"path": "ci.yml", "old": "      - run: a\n      - run: b", "new": "      - run: a\n      - run: c"}
    asked: list = []
    with monkeypatch.context() as m:
        m.setattr(indentation, "rebase_edit", lambda *a, **k: asked.append(a), raising=False)
        now = resolve_patch(_checkout(tmp_path, {"ci.yml": src}), file_edits=[edit])
    assert not asked and not _rebase_notes(now) and "+      - run: c" in now.diff


# --- (e) a tab-indented file -----------------------------------------------------------------------------------------------------------------

TABS = "def f(x):\n\tif x:\n\t\ty = 1\n\treturn y\n"


@EOLS
def test_a_tab_indented_file_is_re_based_in_tabs(tmp_path, monkeypatch, eol):
    edit = {"path": "m.py", "old": "\t\t\tif x:\n\t\t\t\ty = 1", "new": "\t\t\tif x:\n\t\t\t\ty = 2\n\t\t\t\tz = 3"}  # two tabs too deep
    was_work = _checkout(tmp_path / "was", {"m.py": TABS}, eol)
    was = _resolve(was_work, [edit], monkeypatch, rebase=False)
    broken = _patched(was_work, "m.py", was).decode("utf-8")
    with pytest.raises(IndentationError):
        ast.parse(broken)
    work = _checkout(tmp_path / "now", {"m.py": TABS}, eol)
    now = _resolve(work, [edit])
    out = _patched(work, "m.py", now).decode("utf-8")
    ast.parse(out)
    assert len(_rebase_notes(now)) == 1
    assert out == "def f(x):\n\tif x:\n\t\ty = 2\n\t\tz = 3\n\treturn y\n".replace("\n", eol)  # the file's tabs and its line end
    assert not any(line.startswith(" ") for line in out.splitlines())  # no space ever leads a line
    assert _no_ws(out) == _no_ws(broken)  # (f)


def test_tabs_written_as_spaces_are_left_to_d47_not_re_based(tmp_path, monkeypatch):
    """The model's spaces against a tab file are the D-47 case (indentation.normalise_patch): T7 does not touch them, so D-47's record is unchanged."""
    edit = {"path": "m.py", "old": "    else:\n        y = 1", "new": "    else:\n        y = 2"}
    src = "def f(x):\n\tif x:\n\t\ty = 0\n\telse:\n\t\ty = 1\n\treturn y\n"
    now = _resolve(_checkout(tmp_path / "now", {"m.py": src}), [edit])
    was = _resolve(_checkout(tmp_path / "was", {"m.py": src}), [edit], monkeypatch, rebase=False)
    assert now.diff == was.diff and not _rebase_notes(now)
    originals = {"m.py": src}
    done = indentation.normalise_patch(now.diff, originals)
    assert done is not None and done[1][0]["to"] == "tabs"


# --- rebase_edit on its own --------------------------------------------------------------------------------------------------------------------


def _rebase(matched, old, new):
    return indentation.rebase_edit(matched, old, new)


def test_rebase_edit_anchors_the_first_line_on_the_file_and_shifts_the_rest_by_what_the_matched_lines_show():
    matched = ["    # c", "    if a:", "        b()", "    else:", "        d()"]
    old = ["# c", "        if a:", "            b()", "        else:", "            d()"]
    new = ["# c", "        if a is not None:", "            b()", "        else:", "            d()", "            e()"]
    done = _rebase(matched, old, new)
    assert done is not None
    assert done.lines == ["    # c", "    if a is not None:", "        b()", "    else:", "        d()", "        e()"]
    assert done.changed == 6 and done.structural == 5 and done.shift == -4 and done.first_line is True  # (the comment is the sixth)
    assert [x.lstrip(" \t") for x in done.lines] == [x.lstrip(" \t") for x in new]  # (f)


def test_rebase_edit_moves_a_block_that_is_too_shallow_deeper():
    done = _rebase(["            if a:", "                b()"], ["    if a:", "        b()"], ["    if a:", "        b()", "        c()"])
    assert done is not None and done.lines == ["            if a:", "                b()", "                c()"] and done.shift == 8


def test_rebase_edit_does_nothing_when_the_model_frame_is_already_the_files():
    lines = ["    if a:", "        b()"]
    assert _rebase(lines, list(lines), ["    if a:", "        b()", "          c()"]) is None  # an exact match: not even a misindented new line


def test_rebase_edit_a_single_stripped_first_line_is_anchored_on_the_matched_line():
    done = _rebase(["        x = 1"], ["x = 1"], ["x = 2"])
    assert done is not None and done.lines == ["        x = 2"] and done.shift is None and done.first_line


def test_rebase_edit_without_evidence_for_a_multi_line_new_it_declines():
    # only the stripped first line is known: where the model thinks the later lines sit cannot be read, so nothing is guessed
    assert _rebase(["        if a:"], ["if a:"], ["if a:", "    b()"]) is None


def test_rebase_edit_declines_when_the_matched_lines_disagree_on_the_offset():
    assert _rebase(["    if a:", "        b()"], ["  if a:", "    b()"], ["  if a:", "    b()", "    c()"]) is None  # 2-space model, 4-space file
    assert _rebase(["    if a:", "        b()"], ["        if a:", "        b()"], ["        if a:", "        b()"]) is None  # flattened


def test_rebase_edit_declines_on_tabs_against_spaces_and_on_mixed_lines():
    assert _rebase(["\tif a:", "\t\tb()"], ["    if a:", "        b()"], ["    if a:", "        c()"]) is None
    assert _rebase(["    if a:", "        b()"], ["\tif a:", "\t\tb()"], ["\tif a:", "\t\tc()"]) is None
    assert _rebase(["    if a:", "        b()"], ["   \tif a:", "        b()"], ["    if a:", "        c()"]) is None


def test_rebase_edit_declines_when_a_line_would_go_left_of_column_zero():
    assert _rebase(["if a:", "    b()"], ["        if a:", "            b()"], ["        if a:", "            b()", "    c()"]) is None


def test_rebase_edit_leaves_strings_blank_lines_and_comments_alone_and_moves_continuations_with_their_statement():
    matched = ["    x = f(", "        1,", "        2)", "    s = '''", "  keep", "'''", "", "    # n"]
    old = ["        x = f(", "            1,", "            2)", "        s = '''", "  keep", "'''", "  ", "# n"]
    new = ["        x = f(", "            1,", "            2)", "        s = '''", "  keep", "'''", "  ", "# n", "        y = g(", "                   3)"]
    done = _rebase(matched, old, new)
    assert done is not None
    assert done.lines[:8] == ["    x = f(", "        1,", "        2)", "    s = '''", "  keep", "'''", "  ", "# n"]
    assert done.lines[8:] == ["    y = g(", "               3)"]
    assert [x.lstrip(" \t") for x in done.lines] == [x.lstrip(" \t") for x in new]


def test_rebase_edit_never_changes_a_non_whitespace_character_over_a_sweep_of_offsets():
    block = ["if a:", "    b(1, 'x')", "else:", "    c = [1,", "         2]"]
    for file_indent in (0, 4, 8, 12):
        for model_indent in (0, 2, 4, 6, 8, 16, 26):
            f_ws, m_ws = " " * file_indent, " " * model_indent
            matched = [f_ws + line for line in block]
            old = [m_ws + line for line in block]
            new = old + [m_ws + "    d = 1", m_ws + "e = 2"]
            done = _rebase(matched, old, new)
            if done is None:
                continue
            assert len(done.lines) == len(new)
            assert [x.lstrip(" \t") for x in done.lines] == [x.lstrip(" \t") for x in new]
            assert all(len(x) - len(x.lstrip(" ")) == len(y) - len(y.lstrip(" ")) + file_indent - model_indent
                       for x, y in zip(done.lines, new) if x.strip() and not x.lstrip().startswith(("2", "'")))


# --- in the pipeline: resolved, gated, applied, recorded --------------------------------------------------------------------------------------


def test_in_the_pipeline_a_re_based_edit_is_gated_applied_and_recorded(tmp_path):
    """The shape of the osm-heatmap patch (`old` starts at a comment without its indentation, later lines 4 columns too deep) on a small program."""
    program = ("import sys\n\ndef main(model):\n    # pick a model\n    if model == 'a':\n        m = 1\n    else:\n"
               "        raise Exception(\"Model not specified\")\n    print(m)\n\nmain(None)\n")
    fix = {"file_edits": [{"path": "train.py",
                           "old": "# pick a model\n        if model == 'a':\n            m = 1\n        else:\n            raise Exception(\"Model not specified\")",
                           "new": "# pick a model\n        if model == 'a':\n            m = 1\n        else:\n            m = 2"}],
           "env_delta": [], "cited_sources": [], "reason_no_citation": "none", "explanation": "default"}
    failing = _fail("Traceback (most recent call last):\n  File \"train.py\", line 11, in <module>\n    main(None)\n"
                    "  File \"train.py\", line 8, in main\n    raise Exception(\"Model not specified\")\nException: Model not specified\n")
    result, _, _, _ = _pipeline(tmp_path, [failing, _ok()], files={"train.py": program}, replies=[fix])
    assert result.verdict == "RUNS_AFTER_REPAIR", result.full_log[-1500:]
    attempt = [a for a in result.attempts if a.origin == "model"][-1]
    assert attempt.gate_decision == "PASS"
    assert any("re-based onto the matched lines" in note and "harness-v1.8, T7" in note for note in attempt.patch_notes)
    assert "+        m = 2" in attempt.diff_text and "# pick a model" not in "".join(
        line for line in attempt.diff_text.splitlines() if line[:1] in "+-" and line[:3] not in ("+++", "---"))  # the comment stays where it was
    assert attempt.model_patch  # what the model sent is kept beside the applied diff
    applied = (tmp_path / "train.py").read_text(encoding="utf-8")
    ast.parse(applied)
    assert "    # pick a model\n    if model == 'a':\n        m = 1\n    else:\n        m = 2\n    print(m)\n" in applied
    assert attempt.as_dict().get("indentation_normalised") in (None, [])  # D-47 had nothing to do


def test_patch_pipeline_calls_the_rebase_through_the_indentation_module():
    """The seam the tests above switch off for their 'before' halves."""
    assert callable(indentation.rebase_edit) and patch_pipeline.indentation is indentation
