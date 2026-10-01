"""Phase D5: submission texts. Every number in them is in the REPLAY JSON; no sentence says the LLM repair loop recovered an entry."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phase_d import dashboard, replay  # noqa: E402

# Grows by one file per deliverable commit.
DOCS = [
    "docs/submission/demo_script.md",
    "README.md",
    "docs/submission/devpost_answers.md",
    "docs/submission/description.md",
]
TAGGED_DOCS = [d for d in DOCS if d != "docs/submission/criteria_map.md"]

# A standalone number: not part of a word, an identifier, a hash or a dotted version.
NUMBER = re.compile(r"(?<![A-Za-z0-9_.])\d+(?:\.\d+)?(?![A-Za-z0-9_])")
TAG = re.compile(r"MEASURED|ESTIMATED|DERIVED")
TAG_MARK = re.compile(r"\[(?:MEASURED|ESTIMATED|DERIVED)\]")
# The only allowlist: timeline timestamps (m:ss) and the judging / rating scales.
ALLOWLIST = (re.compile(r"\b\d:\d\d\b"), re.compile(r"\b5-point\b"), re.compile(r"\b1[–-]10\b"), re.compile(r"\b\d{1,2}/10\b"), re.compile(r"\bout of 10\b"))
CODE_SPAN = re.compile(r"(`+).+?\1")
DEFECT_ID = re.compile(r"\bD-\d+\b")
LINK_TARGET = re.compile(r"\]\([^)]*\)")
LOOP = re.compile(r"\b(LLM|model|models|Nemotron|repair loop|repairer|Super|Nano|Ultra)\b", re.I)
RECOVERY = re.compile(r"\b(recover(?:ed|s|y|ies)?|repaired|fixed the|made it run|got it running|now runs)\b", re.I)
NEGATION = re.compile(r"\b(recovered 0|0 of|0/|zero|no |not |never|none|nothing|without|did not|does not|cannot|apparent|artefact|alone)\b", re.I)


def _strip_allowlist(text: str) -> str:
    for pattern in ALLOWLIST:
        text = pattern.sub(" ", text)
    return text


def _text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def allowed() -> set[str]:
    """Standalone numbers of the REPLAY JSON, plus the 4-decimal display form of every tagged value (the dashboard's dollar rule)."""
    tokens: set[str] = set()

    def walk(obj):
        if isinstance(obj, dict):
            if "tag" in obj and isinstance(obj.get("value"), (int, float)) and not isinstance(obj["value"], bool):
                tokens.add(f"{obj['value']:.4f}")
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    for rel in dashboard.INPUTS:
        raw = (ROOT / rel).read_text(encoding="utf-8")
        tokens |= set(NUMBER.findall(raw))
        walk(json.loads(raw))
    return tokens


@pytest.mark.parametrize("rel", DOCS)
def test_every_number_in_the_submission_text_is_in_the_replay_json(rel, allowed):
    missing = sorted(set(NUMBER.findall(_strip_allowlist(_text(rel)))) - allowed)
    assert not missing, f"{rel}: numbers that are not in the REPLAY JSON: {missing}"


@pytest.mark.parametrize("rel", TAGGED_DOCS)
def test_every_line_with_a_number_carries_a_tag(rel):
    """Outside code spans, link targets and defect ids, a line that shows a number also shows MEASURED, ESTIMATED or DERIVED."""
    for number, line in enumerate(_text(rel).splitlines(), 1):
        prose = DEFECT_ID.sub(" ", LINK_TARGET.sub("]", CODE_SPAN.sub(" ", _strip_allowlist(line))))
        if NUMBER.search(prose):
            assert TAG.search(line), f"{rel}:{number}: a number without a tag: {line[:120]!r}"


@pytest.mark.parametrize("rel", DOCS)
def test_no_sentence_states_or_implies_that_the_llm_repair_loop_recovered_an_entry(rel):
    text = re.sub(r"\s+", " ", CODE_SPAN.sub(" ", _text(rel)))
    for sentence in re.split(r"(?<=[.!?;:|])\s", text):
        if LOOP.search(sentence) and RECOVERY.search(sentence):
            assert NEGATION.search(sentence), f"{rel}: this sentence may imply the repair loop recovered something: {sentence[:200]!r}"


def test_the_claim_check_catches_a_positive_claim():
    bad = "The repair loop recovered entry 11."
    assert LOOP.search(bad) and RECOVERY.search(bad) and not NEGATION.search(bad)
    good = "The LLM repair loop recovered 0 of 8 gate entry-runs."
    assert NEGATION.search(good)
    assert set(NUMBER.findall("v1.3.4 D-27 55s a1b2 0.6781 $10.1349 entry 8")) == {"27", "0.6781", "10.1349", "8"}


def test_the_licence_is_at_the_repository_root_and_is_apache_2():
    licence = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Apache License" in licence and "Version 2.0, January 2004" in licence


# ---------------------------------------------------------------- demo script

def test_the_demo_script_fits_three_minutes_and_maps_every_numbered_sentence_to_a_record():
    text = _text("docs/submission/demo_script.md")
    stamps = [(int(m.group(1)) * 60 + int(m.group(2)), int(m.group(3)) * 60 + int(m.group(4)))
              for m in re.finditer(r"^\| (\d):(\d\d)–(\d):(\d\d) \|", text, flags=re.M)]
    assert stamps and stamps[0][0] == 0 and stamps[-1][1] <= 180
    assert all(a < b for a, b in stamps) and all(stamps[i][1] == stamps[i + 1][0] for i in range(len(stamps) - 1))
    spoken = [row.split("|")[4].strip() for row in re.findall(r"^\| \d:\d\d–\d:\d\d \|.*$", text, flags=re.M)]
    words = sum(len(TAG_MARK.sub(" ", s).split()) for s in spoken)  # the tags are shown on screen, not read aloud
    assert words <= 450, words  # about 150 words a minute
    claims = re.findall(r"^\| C\d+ \|.*$", text, flags=re.M)
    assert claims
    claimed = " ".join(row.split("|")[2] for row in claims)
    for sentence in re.split(r"(?<=[.!?])\s", " ".join(spoken)):
        if NUMBER.search(_strip_allowlist(sentence)):
            assert sentence.strip() in claimed, f"a spoken sentence with a number has no evidence row: {sentence!r}"
    for row in claims:
        cells = [c.strip() for c in row.split("|")]
        assert TAG.search(cells[3]) and ("@" in cells[4] or "summary.json" in cells[4]), row[:120]
    stored = replay.load_passports(ROOT)
    for record_id in set(re.findall(r"harness-v[\d.]+/\w+/\d\d@[0-9a-f]{64}", text)):
        assert record_id in stored, record_id
    for shown in set(re.findall(r"`((?:reports|runs|docs)/[^`#]+)", text)):
        assert (ROOT / shown).exists(), shown


# ---------------------------------------------------------------- README

README_SECTIONS = ["What it is", "The measured result", "How it works", "Where Nemotron is used", "Where Token Factory is used", "Where Tavily is used",
                   "Run it offline in one command", "Run it live", "Evidence and integrity", "Defect register summary and status rule", "Cost ledger",
                   "License", "Known limits"]


def _summary() -> dict:
    return json.loads((ROOT / replay.REPLAY_DIR / "summary.json").read_text(encoding="utf-8"))


def test_the_readme_has_the_required_sections_in_order():
    headings = re.findall(r"^## (.+)$", _text("README.md"), flags=re.M)
    assert headings == README_SECTIONS


def test_the_readme_names_the_models_exactly_as_the_records_do():
    text = _text("README.md")
    recorded = {r["model"] for v in _summary()["stack"]["versions"] for r in v["roles"]}
    assert recorded and set(re.findall(r"nvidia/[A-Za-z0-9._-]+", text)) == recorded
    assert "prompt-engineered" in text and "fine-tuned" in text


def test_the_readme_states_the_headline_the_badges_the_ledger_and_the_limits():
    text = _text("README.md")
    summary = _summary()
    for tag in (replay.VERSIONS[1], replay.VERSIONS[2]):
        badge = json.loads((ROOT / replay.REPLAY_DIR / f"{tag}.json").read_text(encoding="utf-8"))["badge"]["text"]
        assert f"`{badge}`" in text, tag
    assert "reports/phase-d/dashboard/index.html" in text and "python -m phase_d.build_dashboard" in text
    ledger = summary["ledger"]
    for part in ("total", "measured", "estimated"):
        assert f"${ledger[part]['value']:.4f}" in text
    assert "lower bound" in text and "D-27" in text
    for defect in ("D-21", "D-23", "D-25", "D-26", "D-27", "D-28"):
        assert defect in text.split("## Known limits")[1], defect
    for status, count in summary["inventory"]["defects_by_status"].items():
        assert f"`{status}`: {count['value']} [MEASURED]" in text
    assert "smoke-limit artefact" in text and "0 [MEASURED] of 8 [MEASURED]" in text
    for rel in set(re.findall(r"\]\(((?!https?:)[^)#]+)", text)):
        assert (ROOT / rel).exists(), rel


# ---------------------------------------------------------------- Devpost answers

def test_the_devpost_answers_mark_ratings_as_proposed_and_leave_the_owner_question_blank():
    text = _text("docs/submission/devpost_answers.md")
    sections = dict(re.findall(r"^## (.+?)\n(.*?)(?=^## |\Z)", text, flags=re.M | re.S))
    assert len(sections) == 11
    rated = [name for name, body in sections.items() if re.search(r"\b\d{1,2}/10\b", body)]
    assert len(rated) == 3 and all("PROPOSED" in sections[name] and "The owner decides." in sections[name] for name in rated)
    assert sections["How does it compare with other models?"].strip().startswith("Not measured.")
    assert sections["Prompt-engineered or fine-tuned?"].strip().startswith("Prompt-engineered.")
    assert sections["Did you use Tavily?"].strip().startswith("**Yes.**") and "never cited" in sections["Did you use Tavily?"]
    assert sections["Is this a new project or an existing one?"].strip() == "<!-- OWNER TO ANSWER: left blank on purpose -->"
    recorded = {r["model"] for v in _summary()["stack"]["versions"] for r in v["roles"]}
    assert set(re.findall(r"nvidia/[A-Za-z0-9._-]+", text)) == recorded


# ---------------------------------------------------------------- project description

def test_the_description_is_at_most_400_words_and_the_tagline_is_two_sentences():
    text = _text("docs/submission/description.md")
    tagline = text.split("## Tagline")[1].split("## Description")[0].strip()
    description = text.split("## Description")[1].strip()
    spoken = TAG_MARK.sub(" ", description).replace("**", "")
    assert len(spoken.split()) <= 400, len(spoken.split())
    assert len(re.findall(r"[.!?](?:\s|$)", TAG_MARK.sub("", tagline))) == 2
    assert "0 [MEASURED] of 8 [MEASURED]" in tagline and "0 [MEASURED] of 8 [MEASURED]" in description
    assert "EXPLORATORY" in description and "lower bound" in description and "smoke-limit artefact" in description
