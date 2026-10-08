"""harness-v1.9, task 3 c and d.

c (D-73, TEST-C g-meta): the blocker printed a literal `{tried_paths}`. The regression test the owner asked for: no human-facing sentence of a blocker report
may carry an unfilled template field, for every taxonomy class, for evidence shaped like every recorded one, and for every committed record under runs/.
A field quoted inside backticks is the record's own text (a verbatim error line), not a template hole, and is allowed.

d (D-72, TEST-C minmaxot): a write into a directory that does not exist was DATA_MISSING ("the dataset the repository expects at output/..."). It is now
OUTPUT_DIR_MISSING, the blocker says RERUN creates the directory, and output_dir builds the one `mkdir -p` the orchestrator runs.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.services import blocker, classifier, output_dir
from app.services.classifier import TaxonomyCode

ROOT = Path(__file__).resolve().parents[2]
FIELD = re.compile(r"\{[A-Za-z_]\w*\}")
SENTENCE_FIELDS = ("what_a_human_must_supply", "next_action")

G_META = "raise FileNotFoundError(f'Features file not found in any of: {tried_paths}')"
MINMAXOT = """Traceback (most recent call last):
  File "dcot/base_case.py", line 116, in <module>
    np.savetxt('output/objective_values_base' + str(N_inf) + '_' + str(run_K), objective_values)
  File "<__array_function__ internals>", line 6, in savetxt
  File "/usr/local/lib/python3.7/site-packages/numpy/lib/npyio.py", line 1368, in savetxt
    open(fname, 'wt').close()
FileNotFoundError: [Errno 2] No such file or directory: 'output/objective_values_base1_0'
"""
READ_MISSING = """Traceback (most recent call last):
  File "recalibrate.py", line 388, in main
    ((y_probs_val, y_val), (y_probs_test, y_test)) = unpickle_probs(fname)
  File "recalibrate.py", line 40, in unpickle_probs
    with open(file, 'rb') as f:
FileNotFoundError: [Errno 2] No such file or directory: 'saved_logits/probs_densenet40_c10_logits.p'
"""
EVIDENCE = ("", G_META, MINMAXOT.strip().splitlines()[-1], "ModuleNotFoundError: No module named 'foo'", "{weird} {x} text with {braces}",
            "FileNotFoundError: {path_template}/data.csv", "No such file or directory: '{root}/x'")


def unfilled(text: str | None) -> list[str]:
    """Template fields outside backtick-quoted spans."""
    outside = re.sub(r"`[^`]*`", "", text or "")
    return FIELD.findall(outside)


def _report(code: str, evidence: str, baseline: dict | None = None) -> dict | None:
    rec = {"verdict": "BLOCKED", "error_chain": [{"error": evidence, "class": code, "attribution": "REPO", "phase": "repo_run"}], "attempts": []}
    if baseline:
        rec["baseline"] = baseline
    return blocker.report(rec)


@pytest.mark.parametrize("code", TaxonomyCode.ALL)
@pytest.mark.parametrize("evidence", EVIDENCE)
def test_no_class_sentence_carries_an_unfilled_template_field(code, evidence):
    out = _report(code, evidence)
    assert out is not None
    for field in SENTENCE_FIELDS:
        assert unfilled(out.get(field)) == [], (code, evidence, field, out.get(field))


def _committed_records():
    for path in sorted((ROOT / "runs").rglob("*.json")):
        if path.stat().st_size > 40_000_000:
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(doc, dict) and isinstance(doc.get("result"), dict) and "error_chain" in doc["result"]:
            cert = doc.get("certificate") or {}
            yield path.relative_to(ROOT).as_posix(), {**doc["result"], "baseline": cert.get("baseline"), "full_log": cert.get("full_log")}
        elif isinstance(doc, dict) and "error_chain" in doc and "verdict" in doc:  # a downloaded certificate (live scans)
            yield path.relative_to(ROOT).as_posix(), {"verdict": doc["verdict"], "error_chain": doc.get("error_chain") or [], "attempts": doc.get("diffs") or [],
                                                      "baseline": doc.get("baseline"), "full_log": doc.get("full_log")}


def test_no_committed_record_s_blocker_carries_an_unfilled_template_field():
    seen, bad = 0, []
    for name, rec in _committed_records():
        out = blocker.report(rec)
        seen += 1
        if out is None:
            continue
        for field in SENTENCE_FIELDS:
            if unfilled(out.get(field)):
                bad.append((name, field, out.get(field)))
    assert seen > 100
    assert bad == []


def test_g_meta_names_the_documented_placeholder_and_never_the_raise_line():
    out = _report("DATA_MISSING", G_META, {"execute_command": "python G-Meta/train.py --data_dir PATH/G-Meta_Data/arxiv/ --epoch 10 --task_setup Disjoint"})
    assert out["cause"] == "DOCUMENTED_PATH_PLACEHOLDER"
    assert "`PATH/G-Meta_Data/arxiv/`" in out["what_a_human_must_supply"]
    assert "{tried_paths}" not in out["what_a_human_must_supply"] and "{tried_paths}" not in out["next_action"]


def test_without_a_placeholder_the_class_default_uses_the_generic_wording():
    out = _report("DATA_MISSING", G_META, {"execute_command": "python G-Meta/train.py --epoch 10"})
    assert out["diagnosis"] == "class_default"
    assert out["what_a_human_must_supply"] == "the dataset the repository expects at the path the code opens, obtained as its README describes"


def test_a_real_missing_path_beside_a_placeholder_keeps_the_path():
    """DEV img-comp-reference: `original.png` is missing; the command also carries `[model_path]`. The path the error names is the better sentence."""
    out = _report("DATA_MISSING", "FileNotFoundError: [Errno 2] No such file or directory: 'original.png'", {"execute_command": "sh compress.sh original.png [model_path]"})
    assert out["diagnosis"] == "class_default"
    assert "original.png" in out["what_a_human_must_supply"]


# ---- d: OUTPUT_DIR_MISSING --------------------------------------------------------------------------------------------------------------------------
def test_a_write_into_a_missing_directory_is_not_missing_data():
    c = classifier.classify(1, MINMAXOT)
    assert c.code == TaxonomyCode.OUTPUT_DIR_MISSING
    assert c.family == "Environment"
    assert "output/objective_values_base1_0" in c.evidence


def test_a_read_of_a_missing_file_stays_data_missing():
    assert classifier.classify(1, READ_MISSING).code == TaxonomyCode.DATA_MISSING


def test_the_blocker_says_rerun_creates_the_directory():
    out = _report(TaxonomyCode.OUTPUT_DIR_MISSING, MINMAXOT.strip().splitlines()[-1])
    assert out["fixable_by"] == "deterministic"
    assert "creates the directory of output/objective_values_base1_0" in out["what_a_human_must_supply"]
    assert "dataset" not in out["what_a_human_must_supply"]


def test_the_mkdir_command():
    miss = output_dir.detect(MINMAXOT)
    assert miss.directory == "output" and miss.write_line.startswith("np.savetxt(")  # the innermost frame of the program's own code
    # `|| true`: the step stays in the run's setup commands, so a path component that is a file must not break every later execution (review, M4)
    assert output_dir.mkdir_command(miss, "python dcot/base_case.py") == ("mkdir -p -- output || true", "output")
    assert output_dir.mkdir_command(miss, "cd dcot && python base_case.py") == ("mkdir -p -- dcot/output || true", "dcot/output")


@pytest.mark.parametrize("path, why", [
    ("objective_values", "no directory part"),
    ("/abs/out/file.txt", "not a path inside the repository"),
    ("~/models/x.pth", "not a path inside the repository"),
    ("../outside/x.txt", "leaves the repository"),
    ("out;rm -rf x/f.txt", "leaves the repository or carries characters"),
])
def test_the_mkdir_command_refuses_unsafe_or_pointless_directories(path, why):
    miss = output_dir.Miss(path, path.rsplit("/", 1)[0] if "/" in path else "", "np.save(x)", f"FileNotFoundError: [Errno 2] No such file or directory: '{path}'")
    command, reason = output_dir.mkdir_command(miss, "python x.py")
    assert command is None and why in reason


@pytest.mark.parametrize("writer", ["torch.save(model.state_dict(), 'ckpt/model.pth')", "plt.savefig('figs/a.png')", "df.to_csv('results/table.csv')",
                                    "with open('logs/run.txt', 'w') as f:", "json.dump(obj, open('out/a.json', mode='w'))"])
def test_every_write_form_is_recognised(writer):
    text = f'Traceback (most recent call last):\n  File "x.py", line 3, in <module>\n    {writer}\nFileNotFoundError: [Errno 2] No such file or directory: \'ckpt/model.pth\'\n'
    assert output_dir.detect(text) is not None


def test_the_orchestrator_runs_the_step_before_any_model_call():
    src = (ROOT / "backend" / "app" / "services" / "orchestrator.py").read_text(encoding="utf-8")
    dispatch = src.index("classification.code == classifier.TaxonomyCode.OUTPUT_DIR_MISSING")
    assert src.index("def _auto_output_dir") < dispatch
    assert "state.runner_extras.append(command)" in src[src.index("def _auto_output_dir"): dispatch]
