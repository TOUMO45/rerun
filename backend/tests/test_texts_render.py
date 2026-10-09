"""flag-mode pass (owner, 2026-10-09, task 4): the README's result section and the Devpost texts are generated from reports/v1.9/figures.json by
reports/texts/render.py, in the owner's order, and no number is typed into a template."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "reports" / "texts"))

import render  # noqa: E402

# what a template may contain with a digit that is not a figure: code spans, link targets, defect ids (D-12), errata (E-3), harness versions and tags
# (harness-v1.9.0, rc4), the judging scales (1–10, 4/10) and the term "exit 0" (an exit status, not a count)
ALLOWED = re.compile(r"`[^`]*`|\]\([^)]*\)|\bD-\d+\b|\bE-\d+\b|v\d+(?:\.\d+)*(?:-rc\d+)?|\b1–10\b|\b\d{1,2}/10\b|\bexit 0\b")


def test_the_texts_are_what_the_templates_and_figures_json_give():
    assert render.main(["--check"]) == 0


def test_no_number_is_typed_into_a_template():
    for tpl in render.TEMPLATES.glob("*.md"):
        text = render.PLACEHOLDER.sub(" ", ALLOWED.sub(" ", tpl.read_text(encoding="utf-8")))
        assert not re.findall(r"\d", text), (tpl.name, re.findall(r".{0,30}\d.{0,30}", text)[:3])


def _section() -> str:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    return readme.split(render.START)[1].split(render.END)[0]


def test_the_readme_result_section_follows_the_owner_s_order():
    s = _section()
    marks = [s.index(m) for m in ("held-out repositories ran their documented command", "Diagnosis, TEST-C", "### The benchmark and its per-layer tables", "### Limits")]
    assert marks == sorted(marks)
    limits = s.split("### Limits")[1]
    assert "Anti-cheat is not a headline claim" in limits and "Erratum E-3" in limits and "Post-hoc, labelled, never merged into TEST-C" in limits
    assert "refused all 31 [DERIVED] honest controls" in s                     # the held-out half: the table only, with this note
    flag = s.split("The flag mode:")[1].split("**On real runs**")[0]
    assert "Derived from committed records" in flag and "chosen after the results were seen" in flag and "exercised by no cheat" in flag and "unmeasured" in flag


def test_no_generated_or_repository_text_says_the_audits_removed_fakes():
    pattern = re.compile(r"(?:audits?|the audit)[^.]{0,80}(?:removed|caught|stopped|worked against)[^.]{0,40}fakes?|guard that worked against fakes", re.I)
    for rel in ("README.md", "docs/submission/description.md", "docs/submission/devpost_answers.md", "docs/submission/criteria_map.md", "docs/submission/demo_script.md"):
        text = re.sub(r"\s+", " ", (ROOT / rel).read_text(encoding="utf-8"))
        for sentence in re.split(r"(?<=[.!?])\s", text):
            if pattern.search(sentence):
                assert re.search(r"\b(not|neither|never|no)\b", sentence, re.I), (rel, sentence[:200])
