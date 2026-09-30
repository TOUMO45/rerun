"""harness-v1.3.3, D-1/D-2/D-15: from what the repair model wrote to a diff that applies, before the tamper gate.

The 16 fixture cases are the source patches the v1.3.2 TREATMENT arm actually proposed (tests/fixtures/v133/patches/<entry>_<attempt>/:
diff.txt as stored in the record, meta.json = what happened then). The original file of each case is the pinned commit's file as committed
upstream: kept in git only where the repository's licence is permissive (M-FAC, MIT; see fixtures/v133/NOTICE.md), otherwise fetched from
GitHub and checked against the recorded git blob (fixture_fetch.py, SOURCES.json). Those tests carry the marker `requires_network` and are
skipped when the file cannot be fetched."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import fixture_fetch
from app.services import patch_pipeline
from app.services.orchestrator import _apply_diff_with_git
from app.services.patch_pipeline import PatchProblem, resolve_patch
from app.services.repairer import parse_repair_response
from app.services.tamper_gate import check_patch

PATCHES = Path(__file__).parent / "fixtures" / "v133" / "patches"

# What the pipeline can recover DETERMINISTICALLY from what the model wrote. The other five contain no usable change: two are header-only
# (no hunk at all), two name a line to remove but give no replacement, one invents context lines that are not in the file. Those are what the model-facing retry (same attempt, shown the file's own lines) is for; it cannot be
# measured offline and is measured live at the smoke gate.
RECOVERED = {"e03_a1", "e03_a2", "e04_a1", "e04_a2", "e04_a3", "e14_a1", "e14_a2", "e14_a3", "e17_a1", "e17_a2", "e17_a3"}
UNRECOVERABLE = {
    "e01_a2": "no hunks",
    "e08_a3": "no hunks",
    "e10_a1": "replacement lines are missing",
    "e10_a2": "changes anything",
    "e03_a3": "do not occur in the file",
}


def _as_checkout(work: Path) -> Path:
    """The harness's workdir is a git clone with core.autocrlf=false / core.eol=lf (intake.py); without that config a global
    autocrlf=true (this Windows host) would make `git apply` write CRLF files."""
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=work, check=True, capture_output=True)
    for key, value in (("core.autocrlf", "false"), ("core.eol", "lf")):
        subprocess.run(["git", "config", key, value], cwd=work, check=True, capture_output=True)
    return work


def _case(tmp_path: Path, name: str) -> tuple[Path, str]:
    d = PATCHES / name
    work = tmp_path / name
    try:
        original = fixture_fetch.ensure_original(name)
    except OSError as exc:  # no network (URLError is an OSError): these tests are requires_network
        pytest.skip(f"requires_network: cannot fetch the original of {name}: {exc}")
    shutil.copytree(original, work)  # a hash mismatch (ValueError) is NOT skipped: it fails
    return _as_checkout(work), (d / "diff.txt").read_text(encoding="utf-8")


def _params(names):
    """pytest params; a case whose original is not committed is marked requires_network."""
    src = fixture_fetch.sources()
    return [pytest.param(n, marks=[] if src[n]["original_committed"] else [pytest.mark.requires_network]) for n in sorted(names)]


def _params_with_reason(mapping):
    src = fixture_fetch.sources()
    return [pytest.param(n, r, marks=[] if src[n]["original_committed"] else [pytest.mark.requires_network]) for n, r in sorted(mapping.items())]


def test_only_permissively_licensed_originals_are_committed_and_every_other_one_is_pinned_by_hash():
    """The licence rule for fixtures: MIT/BSD/Apache may be committed (with NOTICE.md); anything else, or unlicensed, is fetched and hash-checked."""
    src = fixture_fetch.sources()
    assert set(src) == set(RECOVERED) | set(UNRECOVERABLE)
    for case, entry in src.items():
        on_disk = (PATCHES / case / "original").exists()
        assert on_disk == entry["original_committed"], case
        assert entry["original_committed"] == (entry["license_status"] in ("MIT", "BSD", "Apache")), case
        assert len(entry["commit"]) == 40 and all(len(f["git_blob_sha1"]) == 40 for f in entry["files"].values())
        if on_disk:  # the committed bytes are exactly the recorded blob
            for rel, want in entry["files"].items():
                assert fixture_fetch.blob_sha1((PATCHES / case / "original" / rel).read_bytes()) == want["git_blob_sha1"], (case, rel)
    notice = (PATCHES.parent / "NOTICE.md").read_text(encoding="utf-8")
    for repo in {e["repo"] for e in src.values()}:
        assert repo in notice  # every repository is listed with its licence status


def test_the_fixture_set_is_the_sixteen_patches_of_the_v132_treatment_arm():
    cases = sorted(p.name for p in PATCHES.iterdir() if p.is_dir())
    assert len(cases) == 16 and set(cases) == RECOVERED | set(UNRECOVERABLE)
    for name in cases:
        meta = json.loads((PATCHES / name / "meta.json").read_text(encoding="utf-8"))
        assert meta["record"].startswith("runs/corpus_v2_batch/harness-v1.3.2/treatment/")  # the pointer back to the record


@pytest.mark.parametrize("name", _params(RECOVERED))
def test_stored_patch_is_rebuilt_into_a_diff_that_applies_and_changes_the_file(tmp_path, name):
    work, diff = _case(tmp_path, name)
    target = json.loads((PATCHES / name / "meta.json").read_text(encoding="utf-8"))["files"][0]
    before = (work / target).read_text(encoding="utf-8")
    resolution = resolve_patch(work, diff_text=diff)
    assert resolution.paths == (target,) and resolution.notes
    _apply_diff_with_git(work, resolution.diff)  # the real apply step of the orchestrator
    after = (work / target).read_text(encoding="utf-8")
    assert after != before
    # the removed lines of the model's diff are gone, its added lines are in the file
    text = patch_pipeline._clean_text(diff)  # noqa: SLF001
    for patch in patch_pipeline.parse_lenient(diff):
        for hunk in patch.hunks:
            for kind, line in hunk.lines:
                if kind == "+" and line.strip():
                    assert line.strip() in after, line
    # and the tamper gate sees exactly the text that was applied (it may still REJECT on its own rules; that is its job)
    gate = check_patch(resolution.diff, {target: before})
    assert gate.canonical_diff.strip() == resolution.diff.strip() or gate.decision == "REJECT"
    assert text  # (keeps the cleaned form exercised)


@pytest.mark.parametrize("name,reason", _params_with_reason(UNRECOVERABLE))
def test_stored_patch_with_no_usable_change_is_refused_with_a_reason_the_model_can_act_on(tmp_path, name, reason):
    work, diff = _case(tmp_path, name)
    with pytest.raises(PatchProblem) as info:
        resolve_patch(work, diff_text=diff)
    assert reason in str(info.value)


def test_the_recorded_apply_rate_is_eleven_of_sixteen_deterministically():
    """harness-v1.3.2 applied 0 of these 16. Deterministic recovery applies 11 (68.75 %). The target of 80 % is NOT met offline:
    5 cases carry no usable change, and the retry that addresses them needs a live model."""
    assert len(RECOVERED) == 11 and len(RECOVERED) + len(UNRECOVERABLE) == 16


def test_a_placeholder_in_a_hunk_that_changes_something_is_refused_but_a_noop_hunk_with_one_is_skipped(tmp_path):
    repo = _repo(tmp_path, {"p.py": "a = 1\nb = 2\nc = 3\n"})
    with pytest.raises(PatchProblem, match="placeholder"):
        resolve_patch(repo, diff_text="--- a/p.py\n+++ b/p.py\n@@ -1,3 +1,3 @@\n a = 1\n-b = 2\n+b = 20\n ... (omitted for brevity)\n")
    r = resolve_patch(repo, diff_text="--- a/p.py\n+++ b/p.py\n@@ -1,1 +1,1 @@\n ... (omitted for brevity)\n@@ -2,1 +2,1 @@\n-b = 2\n+b = 20\n")
    assert any("skipped" in n for n in r.notes) and "+b = 20" in r.diff


def test_indented_markers_are_read_as_markers_only_when_the_hunk_would_otherwise_change_nothing(tmp_path):
    repo = _repo(tmp_path, {"q.py": "import os\nx = 1\n"})
    r = resolve_patch(repo, diff_text="--- a/q.py\n+++ b/q.py\n@@ -2,1 +2,1 @@\n -x = 1\n +x = 2\n")
    assert "+x = 2" in r.diff and "-x = 1" in r.diff
    # a hunk that already has real markers keeps a context line that merely starts with '-' as context
    repo2 = _repo(tmp_path / "two", {"q.py": "v = (1\n    -2)\nz = 0\n"})
    r2 = resolve_patch(repo2, diff_text="--- a/q.py\n+++ b/q.py\n@@ -1,3 +1,3 @@\n v = (1\n     -2)\n-z = 0\n+z = 5\n")
    assert "+z = 5" in r2.diff


def test_the_orchestrators_apply_step_sends_bytes_so_windows_does_not_corrupt_the_patch(tmp_path):
    """D-15: `subprocess.run(input=str, text=True)` turns LF into CRLF on Windows; `git apply` then reports 'patch does not apply' for a
    correct patch to an LF file (corpus-v2 entry 14 attempt 2, reproduced by replaying its gate-approved diff both ways)."""
    work, diff = _case(tmp_path, "e14_a2")
    resolution = resolve_patch(work, diff_text=diff)
    _apply_diff_with_git(work, resolution.diff)
    assert b"\r" not in (work / "main_optim.py").read_bytes()


# --- the gate: a header-only diff is not a patch (D-2) ------------------------------------------------------------------------


def test_the_gate_rejects_a_diff_with_headers_and_no_hunks():
    result = check_patch("--- a/train.py\n+++ b/train.py\n", {"train.py": "x = 1\n"})
    assert result.decision == "REJECT" and "no hunks" in result.violations[0].reason


# --- formats ----------------------------------------------------------------------------------------------------------------


def _repo(tmp_path: Path, files: dict[str, str | bytes]) -> Path:
    for rel, content in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(content if isinstance(content, bytes) else content.encode())
    return _as_checkout(tmp_path)


def test_file_edits_replace_one_exact_occurrence(tmp_path):
    repo = _repo(tmp_path, {"a.py": "x = 1\ny = 2\nz = 3\n"})
    r = resolve_patch(repo, file_edits=[{"path": "a.py", "old": "y = 2\n", "new": "y = 20\n"}])
    assert r.source == "file_edits" and "+y = 20" in r.diff and "-y = 2" in r.diff
    _apply_diff_with_git(repo, r.diff)
    assert (repo / "a.py").read_text() == "x = 1\ny = 20\nz = 3\n"


def test_file_edits_must_be_unambiguous_and_present(tmp_path):
    repo = _repo(tmp_path, {"a.py": "v = 1\nv = 1\nother = 5\n"})
    with pytest.raises(PatchProblem, match="occurs 2 times"):
        resolve_patch(repo, file_edits=[{"path": "a.py", "old": "v = 1\n", "new": "v = 2\n"}])
    with pytest.raises(PatchProblem, match="does not occur in a.py exactly as written"):
        resolve_patch(repo, file_edits=[{"path": "a.py", "old": "other = 6\n", "new": "other = 7\n"}])


def test_file_edits_tolerate_indentation_noise_but_only_when_unique(tmp_path):
    repo = _repo(tmp_path, {"a.py": "def f():\n    return  compute( 1 )\n"})
    r = resolve_patch(repo, file_edits=[{"path": "a.py", "old": "return compute( 1 )", "new": "    return compute(2)"}])
    assert "+    return compute(2)" in r.diff


def test_file_replacements_keep_the_files_line_endings_and_final_newline(tmp_path):
    repo = _repo(tmp_path, {"crlf.py": b"a = 1\r\nb = 2\r\n"})
    r = resolve_patch(repo, file_replacements=[{"path": "crlf.py", "content": "a = 1\nb = 3"}])
    _apply_diff_with_git(repo, r.diff)
    assert (repo / "crlf.py").read_bytes() == b"a = 1\r\nb = 3\r\n"


def test_a_file_without_a_final_newline_produces_a_diff_git_accepts(tmp_path):
    repo = _repo(tmp_path, {"n.py": "a = 1\nb = 2"})  # no trailing newline
    r = resolve_patch(repo, file_edits=[{"path": "n.py", "old": "b = 2", "new": "b = 3"}])
    assert "No newline at end of file" in r.diff
    _apply_diff_with_git(repo, r.diff)
    assert (repo / "n.py").read_text() == "a = 1\nb = 3"


def test_lenient_reading_of_the_shapes_models_actually_produce(tmp_path):
    repo = _repo(tmp_path, {"m.py": "import os\n\ndef f():\n    raise Exception('no gpu')\n\nf()\n"})
    # unknown counts, a fenced block, a context line whose leading space was dropped, a blank context line
    diff = "```diff\n--- a/m.py\n+++ b/m.py\n@@ -???,?? +???,?? @@\ndef f():\n-    raise Exception('no gpu')\n+    print('cpu fallback')\n\nf()\n```"
    r = resolve_patch(repo, diff_text=diff)
    _apply_diff_with_git(repo, r.diff)
    assert (repo / "m.py").read_text() == "import os\n\ndef f():\n    print('cpu fallback')\n\nf()\n"


def test_a_double_escaped_diff_and_a_split_header_are_read(tmp_path):
    repo = _repo(tmp_path, {"m.py": "a = 1\nb = 2\nc = 3\n"})
    escaped = "---\\na/m.py\\n+++ b/m.py\\n@@ -1,3 +1,3 @@\\n a = 1\\n-b = 2\\n+b = 20\\n c = 3\\n"
    r = resolve_patch(repo, diff_text=escaped)
    _apply_diff_with_git(repo, r.diff)
    assert (repo / "m.py").read_text() == "a = 1\nb = 20\nc = 3\n"


def test_the_claimed_line_number_only_breaks_ties_between_identical_blocks(tmp_path):
    repo = _repo(tmp_path, {"t.py": "x = 0\nfoo()\ny = 1\nfoo()\nz = 2\n"})
    diff = "--- a/t.py\n+++ b/t.py\n@@ -4,1 +4,1 @@\n-foo()\n+bar()\n"
    r = resolve_patch(repo, diff_text=diff)
    _apply_diff_with_git(repo, r.diff)
    assert (repo / "t.py").read_text() == "x = 0\nfoo()\ny = 1\nbar()\nz = 2\n"  # the second foo(), as claimed


# --- refusals ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/etc/passwd", "../outside.py", "C:\\x.py", "sub/../../escape.py"])
def test_paths_outside_the_repository_are_refused(tmp_path, path):
    repo = _repo(tmp_path / "repo", {"a.py": "x = 1\n"})
    (tmp_path / "outside.py").write_text("x = 1\n")
    with pytest.raises(PatchProblem):
        resolve_patch(repo, file_edits=[{"path": path, "old": "x = 1", "new": "x = 2"}])


def test_a_symlinked_path_is_refused(tmp_path):
    repo = _repo(tmp_path / "repo", {"real.py": "x = 1\n"})
    outside = tmp_path / "secret.py"
    outside.write_text("x = 1\n")
    try:
        (repo / "link.py").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks need privileges on this host")
    with pytest.raises(PatchProblem, match="symlink"):
        resolve_patch(repo, file_edits=[{"path": "link.py", "old": "x = 1", "new": "x = 2"}])
    assert outside.read_text() == "x = 1\n"


def test_creating_or_deleting_files_is_refused(tmp_path):
    repo = _repo(tmp_path, {"a.py": "x = 1\n"})
    with pytest.raises(PatchProblem, match="creates or deletes"):
        resolve_patch(repo, diff_text="--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n+x = 1\n")
    with pytest.raises(PatchProblem, match="not an existing file"):
        resolve_patch(repo, file_replacements=[{"path": "new.py", "content": "x = 1\n"}])


def test_one_format_per_reply_and_a_change_that_changes_nothing_is_refused(tmp_path):
    repo = _repo(tmp_path, {"a.py": "x = 1\n"})
    with pytest.raises(PatchProblem, match="exactly one"):
        resolve_patch(repo, diff_text="--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n",
                      file_edits=[{"path": "a.py", "old": "x = 1", "new": "x = 2"}])
    with pytest.raises(PatchProblem, match="identical"):
        resolve_patch(repo, file_edits=[{"path": "a.py", "old": "x = 1", "new": "x = 1"}])


# --- the repairer's reply ---------------------------------------------------------------------------------------------------


def test_repairer_parses_structured_edits_and_cited_sources():
    p = parse_repair_response({
        "file_edits": [{"path": "a.py", "old": "x", "new": "y"}], "code_diff": None, "env_delta": [],
        "cited_sources": [2, "3", True, 5], "explanation": "e",
    })
    assert p.has_code and p.has_change and not p.declined and p.has_diff
    assert p.cited_sources == (2, 5)  # only real integers; bools and strings are dropped
    empty = parse_repair_response({"file_edits": [], "file_replacements": None, "code_diff": None, "env_delta": []})
    assert empty.declined


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="the LF->CRLF translation of text-mode stdin is Windows behaviour")
def test_negative_control_text_mode_stdin_really_breaks_git_apply_on_windows(tmp_path):
    """Why the bytes fix matters: the v1.3.2 call, text=True, fails on the very same gate-approved diff on this host."""
    import subprocess

    work, diff = _case(tmp_path, "e14_a2")
    resolution = resolve_patch(work, diff_text=diff)
    old_style = subprocess.run(["git", "apply", "--whitespace=nowarn", "-"], cwd=work, input=resolution.diff,
                               capture_output=True, text=True)
    assert old_style.returncode != 0 and "patch does not apply" in old_style.stderr
