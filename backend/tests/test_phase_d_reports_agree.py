"""Phase D6: the prose of each gate report, and the texts that repeat its figures, agree with the REPLAY rebuilt from the records.

The replay quotes a line of each report but only compares the line to the file; it never compared the figure in the line with the figure the records add up to. This does."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phase_d import passports, replay  # noqa: E402

DOLLAR = re.compile(r"\$(\d+)\.(\d+)")


def _text(rel: str) -> str:
    return (ROOT / rel).read_bytes().decode("utf-8").replace("\r\n", "\n")


def _doc(tag: str) -> dict:
    return json.loads(_text(f"{replay.REPLAY_DIR}/{tag}.json"))


def _summary() -> dict:
    return json.loads(_text(f"{replay.REPLAY_DIR}/summary.json"))


@pytest.mark.parametrize("tag", [t for t in replay.VERSIONS if t != "harness-v1.3.2"])
def test_the_gate_spend_a_report_states_is_the_sum_of_its_records_to_the_digits_it_states(tag):
    quote = passports.GATE_FILES[tag]["cost_line"]
    assert quote in _text(passports.GATE_FILES[tag]["report"]), (tag, "the quoted cost line is not in the report any more")
    whole, decimals = DOLLAR.search(quote).groups()
    stated = float(f"{whole}.{decimals}")
    batch = _doc(tag)["batch"]
    rebuilt = batch["measured"]["value"] + (batch["estimated"]["value"] or 0.0)
    assert abs(rebuilt - stated) <= 0.5 * 10 ** -len(decimals) + 1e-9, (tag, stated, rebuilt)


def test_the_last_gate_report_and_the_texts_that_repeat_it_state_the_rebuilt_figures():
    summary = _summary()
    total = summary["ledger"]["total"]["value"]
    gate = _doc("harness-v1.4.3")["batch"]
    spend = gate["measured"]["value"] + (gate["estimated"]["value"] or 0.0)
    docs = ("reports/corpus-v2.1/v1.4.3/gate/GATE_REPORT_v1.4.3.md", "METHODOLOGY.md", "CHANGELOG.md")
    for rel in docs:
        text = _text(rel)
        # every figure of the ledger total and of the gate spend that the document states, at any precision, is the rebuilt value rounded to that precision
        for figure in set(re.findall(r"(?<![\d.])29\.1\d*", text)):
            assert abs(float(figure) - total) <= 0.5 * 10 ** -len(figure.split(".")[1]) + 1e-9, (rel, figure, total)
        for figure in set(re.findall(r"(?<![\d.])3\.69\d*", text)):
            assert abs(float(figure) - spend) <= 0.5 * 10 ** -len(figure.split(".")[1]) + 1e-9, (rel, figure, spend)
        if rel == docs[0]:  # the other two also state the rooms of earlier gates
            for figure in set(re.findall(r"room \$(\d+\.\d+)", text)):
                assert abs(float(figure) - (32.0 - total)) <= 5e-5, (rel, figure)
    assert "29.1704" in _text(docs[0]) and "$3.69455" in _text(docs[0]) and "room $2.8296" in _text(docs[0])


def test_the_last_gate_reports_table_of_verdicts_is_the_verdicts_of_the_records():
    text = _text("reports/corpus-v2.1/v1.4.3/gate/GATE_REPORT_v1.4.3.md")
    for x in _doc("harness-v1.4.3")["entries"]:
        verdict = x["timeline"][-1]
        row = next(line for line in text.splitlines() if line.startswith(f"| #{int(x['entry']['id'])} "))
        assert verdict["verdict"] in row and f"`{verdict['taxonomy_code']}`" in row, (x["entry"]["id"], row[:120])
    # criterion (a), as stated in the report, is the count of RUNS_* verdicts in the records
    recovered = sum(1 for x in _doc("harness-v1.4.3")["entries"] if x["timeline"][-1]["verdict"] in ("RUNS_CLEAN", "RUNS_AFTER_REPAIR"))
    assert recovered == 0 and "**FAIL: 0 of 4**" in text


def test_the_headline_sentence_of_every_text_is_the_recomputed_one():
    h = _summary()["headline"]
    runs, apparent = h["gate_entry_runs"]["value"], h["apparent_recoveries"]["value"]
    assert (apparent, runs) == (2, 24)
    needle = f"{apparent} [API-REPORTED] of {runs} [API-REPORTED]"
    for rel in ("README.md", "docs/submission/description.md", "docs/submission/criteria_map.md", "docs/submission/devpost_answers.md"):
        assert needle in _text(rel), rel
    for rel in ("README.md", "docs/submission/description.md", "docs/submission/criteria_map.md", "docs/submission/devpost_answers.md", "docs/submission/demo_script.md"):
        assert not re.search(r"\b2 \[API-REPORTED\] of 20\b", _text(rel)), rel  # the stale denominator of the previous gate


def test_the_last_gate_reports_spend_table_and_criteria_rows_are_the_figures_of_the_records():
    text = _text("reports/corpus-v2.1/v1.4.3/gate/GATE_REPORT_v1.4.3.md")
    doc = _doc("harness-v1.4.3")
    totals = []
    for x in doc["entries"]:
        row = next(line for line in text.splitlines() if line.startswith(f"| #{int(x['entry']['id'])} "))
        spend, model = re.search(r"\| \$(\d+\.\d+) \(\$(\d+\.\d+)\) \|", row).groups()
        assert abs(float(spend) - x["cost"]["entry_total"]["value"]) <= 5e-5 and abs(float(model) - x["cost"]["model"]["value"]) <= 5e-5, (x["entry"]["id"], row[:100])
        totals.append(x["cost"]["entry_total"]["value"])
    figures = {f["criterion"]: f for f in doc["badge"]["figures"]}
    row = lambda crit: next(line for line in text.splitlines() if line.startswith(f"| ({crit}) "))  # noqa: E731
    assert f"{figures['b']['applied']['value']} applied of" in row("b")
    assert f"pass: {figures['c']['citations']['value']} attempts" in row("c")
    assert f"largest entry ${max(totals):.4f}" in row("d") and max(totals) <= 2.0 and figures["d"]["ok"] is True
    share = int(re.search(r"the largest used (\d+) % of it", text).group(1))
    cap = doc["entries"][0]["cost"]["per_entry_cap"]["value"]
    assert share == round(100 * max(totals) / cap) and f"every entry ran with the ${cap} cap" in text  # the sentence the tamper experiment changed (T4)
    assert (figures["a"]["ok"], figures["b"]["ok"], figures["c"]["ok"], figures["d"]["ok"], figures["e"]["ok"]) == (False, True, True, True, True)
    assert "**FAIL" in row("a") and all("pass" in row(c) for c in "bcde")


def test_the_entry_caps_the_readme_states_are_the_caps_of_the_records():
    """A number that exists somewhere in the REPLAY JSON is not a number that is right where it is used: the cap sentence is compared with each version's own caps."""
    caps = {}
    for tag in replay.VERSIONS[1:]:
        caps[tag] = sorted({x["cost"]["per_entry_cap"]["value"] for x in _doc(tag)["entries"]})
    readme = _text("README.md")
    sentence = readme.split("**Cost caps, as recorded.**")[1].split("Batch caps")[0]
    stated = [float(v) for v in re.findall(r"\$(\d+\.\d+) \[API-REPORTED\]", sentence)]
    assert stated == [2.0, 0.7819, 2.0, 1.25, 1.5, 1.75], stated
    assert caps["harness-v1.3.3"] == [2.0] and caps["harness-v1.3.4"][0] == 0.7819 and caps["harness-v1.3.4"][-1] == 2.0
    assert caps["harness-v1.4.0"] == [1.25] and caps["harness-v1.4.1"] == caps["harness-v1.4.2"] == [1.5] and caps["harness-v1.4.3"] == [1.75]
