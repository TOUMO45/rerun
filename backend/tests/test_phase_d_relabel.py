"""D-36 relabel guard: the tag MEASURED became API-REPORTED, a fourth tag BILLED was added, and no number changed value.

Three things are pinned here, none of them by a snapshot file:
  * the old tag word MEASURED appears on no product surface (the passports, REPLAY, the dashboard, the READMEs, the submission texts and the
    v1.4.0 budget note), except inside the one tag-definition sentence that says "formerly MEASURED" (at most once per surface);
  * BILLED appears only where the owner's account-balance reading is shown: the three BILLED lines of `ledger.billed` in the REPLAY summary and
    their display, never on a passport, a REPLAY version file or an API cost;
  * every tagged value the build produced before the relabel is still there with the same value: the values below are the ones the files held at
    commit 87b782e (before D-36), as a digest over (file, path, value) for the passports and the three REPLAY version files, and as a path -> value
    table for `replay/summary.json`. If a later change legitimately alters one of them, update the pin in the same commit and say why.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phase_d import check_dashboard, check_tags, dashboard, passports, replay  # noqa: E402

PHASE_D = ROOT / "reports" / "phase-d"
V132, V133, V134, V140, V141, V142, V143 = replay.VERSIONS
OLD_TAG = re.compile(r"(?<![A-Za-z_])MEASURED(?![A-Za-z_])")  # NOT_MEASURED is a stored verdict category of the pre-registered line, not the tag
SURFACE_TEXTS = ["README.md", "docs/submission/demo_script.md", "docs/submission/devpost_answers.md", "docs/submission/description.md",
                 "docs/submission/criteria_map.md", "docs/design/v1.4.0-budget.md"]
DEFINES_TAGS = {"README.md", "docs/design/v1.4.0-budget.md", "reports/phase-d/README.md", "reports/phase-d/replay/index.md", "reports/phase-d/dashboard/index.html"}
DEFINITION = "the sandbox API's reported operation cost, not account billing"
LEDGER_TEXTS = ["README.md", "docs/submission/devpost_answers.md", "docs/submission/description.md"]
HONEST = ("the sandbox API's reported operation cost", "at most $0.43 [BILLED]", "not reconciled", "D-36, open")
# the owner's two readings of the account balance (the second, $49.57, after the harness-v1.4.1 seal and gate): the latest is the account line
ACCOUNT_SOURCE = ("owner's second reading of the Nebius account balance page, 2026-10-01 (screenshot in chat); "
                  "whole account, cumulative, not per gate")
FIRST_READING_SOURCE = ("owner's reading of the Nebius account balance page, 2026-10-01 19:37 local time; "
                        "whole account, cumulative, not per gate")
INTERVAL_SOURCE = ("difference of the owner's two readings ($49.61 -> $49.57), the interval that holds the harness-v1.4.1 seal and gate "
                   "($3.8588 recorded in the ledger for that interval)")
NO_GATE_READING = "no balance reading was taken for this gate; the only readings are the account-level ones above"
AWAITED = "the owner's balance reading after this gate has not been received yet"
BILLED_VALUES = {"0.39", "0.43", "0.04"}  # the owner's readings (and the interval between them): the only BILLED figures

# digests over "<file>|<json path>|<value>" of every tagged value, from the files at commit 87b782e (before the relabel). They cover the 49 passports of
# harness-v1.3.2 / v1.3.3 / v1.3.4 and those versions' REPLAY files: the Phase D update for v1.4.0 / v1.4.1 / v1.4.2 adds files and annotations (strings),
# and changes no tagged value of these.
PRE_RELABEL_DIGESTS = {
    "passports": (49, "7cf9a036ef0c738a253a54d4c9fd3bf82ffede453e1cceb627cbbacdfa8bcf1e"),
    "harness-v1.3.2": "8f4de7c74fb6656587d62de2a08c09cf5b86e94319398139cfe6b3634a08eeb4",
    "harness-v1.3.3": "e3e400e522e11ece3af49dbdb58065dc2081569ae62270b1f4dc47a45dd02c46",
    "harness-v1.3.4": "a9dab66c93e07bce19f2e1f503b1232223c1c00f30cc24809fd1339dc955217d",
}
# replay/summary.json at commit 87b782e: path -> value of every tagged value
PRE_RELABEL_SUMMARY = {
    "$.headline.gate_entry_runs": 8,
    "$.headline.recovered_by_llm_loop": 0,
    "$.headline.apparent_recoveries": 1,
    "$.headline.apparent_recoveries_annotated_as_artefact": 1,
    "$.headline.recoveries_by_time_machine_alone": 1,
    "$.headline.with_recorded_model_attempt": 5,
    "$.inventory.records": 49,
    "$.inventory.defects": 28,
    "$.inventory.defects_by_status.fixed-and-gated": 11,
    "$.inventory.defects_by_status.fixed-unvalidated": 6,
    "$.inventory.defects_by_status.open": 11,
    "$.stack.versions[0].model_calls[0].calls": 40,
    "$.stack.versions[0].model_calls[0].prompt_tokens": 213833,
    "$.stack.versions[0].model_calls[0].completion_tokens": 97421,
    "$.stack.versions[0].model_calls[0].price_per_million_input_tokens": 0.06,
    "$.stack.versions[0].model_calls[0].price_per_million_output_tokens": 0.24,
    "$.stack.versions[0].model_calls[1].calls": 99,
    "$.stack.versions[0].model_calls[1].prompt_tokens": 380316,
    "$.stack.versions[0].model_calls[1].completion_tokens": 190006,
    "$.stack.versions[0].model_calls[1].price_per_million_input_tokens": 0.3,
    "$.stack.versions[0].model_calls[1].price_per_million_output_tokens": 0.9,
    "$.stack.versions[0].model_calls[2].calls": 38,
    "$.stack.versions[0].model_calls[2].prompt_tokens": 27663,
    "$.stack.versions[0].model_calls[2].completion_tokens": 13366,
    "$.stack.versions[0].model_calls[2].price_per_million_input_tokens": 1.0,
    "$.stack.versions[0].model_calls[2].price_per_million_output_tokens": 3.0,
    "$.stack.versions[0].search.records_with_search_configured": 20,
    "$.stack.versions[1].model_calls[0].calls": 3,
    "$.stack.versions[1].model_calls[0].prompt_tokens": 14862,
    "$.stack.versions[1].model_calls[0].completion_tokens": 6719,
    "$.stack.versions[1].model_calls[0].price_per_million_input_tokens": 0.06,
    "$.stack.versions[1].model_calls[0].price_per_million_output_tokens": 0.24,
    "$.stack.versions[1].model_calls[1].calls": 14,
    "$.stack.versions[1].model_calls[1].prompt_tokens": 67500,
    "$.stack.versions[1].model_calls[1].completion_tokens": 44038,
    "$.stack.versions[1].model_calls[1].price_per_million_input_tokens": 0.3,
    "$.stack.versions[1].model_calls[1].price_per_million_output_tokens": 0.9,
    "$.stack.versions[1].model_calls[2].calls": 3,
    "$.stack.versions[1].model_calls[2].prompt_tokens": 2120,
    "$.stack.versions[1].model_calls[2].completion_tokens": 1208,
    "$.stack.versions[1].model_calls[2].price_per_million_input_tokens": 1.0,
    "$.stack.versions[1].model_calls[2].price_per_million_output_tokens": 3.0,
    "$.stack.versions[1].search.records_with_search_configured": 4,
    "$.stack.versions[2].model_calls[0].calls": 4,
    "$.stack.versions[2].model_calls[0].prompt_tokens": 24147,
    "$.stack.versions[2].model_calls[0].completion_tokens": 9261,
    "$.stack.versions[2].model_calls[0].price_per_million_input_tokens": 0.06,
    "$.stack.versions[2].model_calls[0].price_per_million_output_tokens": 0.24,
    "$.stack.versions[2].model_calls[1].calls": 16,
    "$.stack.versions[2].model_calls[1].prompt_tokens": 99962,
    "$.stack.versions[2].model_calls[1].completion_tokens": 65605,
    "$.stack.versions[2].model_calls[1].price_per_million_input_tokens": 0.3,
    "$.stack.versions[2].model_calls[1].price_per_million_output_tokens": 0.9,
    "$.stack.versions[2].model_calls[2].calls": 4,
    "$.stack.versions[2].model_calls[2].prompt_tokens": 2794,
    "$.stack.versions[2].model_calls[2].completion_tokens": 1968,
    "$.stack.versions[2].model_calls[2].price_per_million_input_tokens": 1.0,
    "$.stack.versions[2].model_calls[2].price_per_million_output_tokens": 3.0,
    "$.stack.versions[2].search.records_with_search_configured": 4,
    "$.ledger.components[0].measured": 1.23641769,
    "$.ledger.components[1].measured": 1.26003552,
    "$.ledger.components[2].measured": 2.92978009,
    "$.ledger.components[2].estimated": 0.0,
    "$.ledger.components[3].measured": 1.31246477,
    "$.ledger.components[4].measured": 3.11200478,
    "$.ledger.components[4].estimated": 0.2842091127,
    "$.ledger.measured": 9.85070285,
    "$.ledger.estimated": 0.2842091127,
    "$.ledger.total": 10.1349119627,
    "$.ledger.kill_records[1].killed_seconds": 26.7,
    "$.ledger.kill_records[1].completed_cost": 0.0,
    "$.ledger.kill_records[2].killed_seconds": 26.3,
    "$.ledger.kill_records[2].completed_cost": 0.0,
}


def _read(rel: str) -> str:
    return (ROOT / rel).read_bytes().decode("utf-8").replace("\r\n", "\n")


def _phase_d_files() -> list[str]:
    return sorted(p.relative_to(ROOT).as_posix() for p in PHASE_D.rglob("*") if p.is_file())


def _summary() -> dict:
    return json.loads(_read("reports/phase-d/replay/summary.json"))


def _tagged_objects(doc) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []

    def walk(obj, path):
        if isinstance(obj, dict):
            if "tag" in obj and "value" in obj:
                out.append((path, obj))
            for k, v in obj.items():
                walk(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{path}[{i}]")

    walk(doc, "$")
    return out


def _tagged_pairs(doc) -> list[tuple[str, object]]:
    return [(path, obj["value"]) for path, obj in _tagged_objects(doc)]


def _digest(rels: list[str]) -> str:
    h = hashlib.sha256()
    for rel in rels:
        base = rel.removeprefix("reports/phase-d/")
        for path, value in _tagged_pairs(json.loads(_read(rel))):
            h.update(f"{base}|{path}|{json.dumps(value, ensure_ascii=False)}\n".encode("utf-8"))
    return h.hexdigest()


def _passport_files() -> list[str]:
    return sorted(p.relative_to(ROOT).as_posix() for p in (PHASE_D / "passports").rglob("*.json"))


def _within(node, ancestor) -> bool:
    while node is not None:
        if node is ancestor:
            return True
        node = node.parent
    return False


# ---------------------------------------------------------------- the old word

def test_the_old_tag_word_appears_nowhere_on_a_product_surface():
    surfaces = _phase_d_files() + SURFACE_TEXTS
    assert len(surfaces) > 60 and "reports/phase-d/dashboard/index.html" in surfaces and "reports/phase-d/replay/summary.json" in surfaces
    for rel in surfaces:
        text = _read(rel)
        hits = [m.start() for m in OLD_TAG.finditer(text)]
        allowed = [at for at in hits if text[max(0, at - 9):at] == "formerly "]  # the one tag-definition sentence
        assert len(hits) == len(allowed), f"{rel}: the old tag word outside a 'formerly MEASURED' sentence"
        assert len(allowed) == (1 if rel in DEFINES_TAGS else 0), f"{rel}: 'formerly MEASURED' must appear once where the tags are defined and nowhere else"


def test_the_stored_verdict_category_not_measured_is_not_the_tag_and_is_left_alone():
    """`NOT_MEASURED` is a category of the pre-registered primary line, quoted from results_tables.json; the tag word is not in it."""
    text = _read("reports/phase-d/replay/harness-v1.3.2.json")
    assert "NOT_MEASURED" in text and not OLD_TAG.search(text)


def test_the_kept_image_wording_the_owner_replaced_appears_on_no_surface():
    for rel in _phase_d_files() + SURFACE_TEXTS:
        assert "unbilled on available evidence" not in _read(rel), rel


def test_the_tag_vocabulary_is_api_reported_estimated_derived_and_billed():
    assert passports.TAGS == ("API-REPORTED", "ESTIMATED", "DERIVED", "BILLED")
    assert passports.RECORD_TAGS == passports.TAGS[:3] and "MEASURED" not in passports.TAGS and passports.SCHEMA.endswith("/v4")
    assert replay.SCHEMA.endswith("/v3") and replay.SUMMARY_SCHEMA.endswith("/v3")
    assert "NOT account billing" in passports.__doc__ and "BILLED" in passports.__doc__
    for rel in _passport_files() + [f"reports/phase-d/replay/{t}.json" for t in replay.VERSIONS]:
        for path, obj in _tagged_objects(json.loads(_read(rel))):
            assert obj["tag"] in passports.RECORD_TAGS, f"{rel} {path}"
    for _, obj in _tagged_objects(_summary()):
        assert obj["tag"] in passports.TAGS
    assert check_tags.violations({"x": {"value": 1, "tag": "MEASURED"}}) and check_tags.violations({"x": {"value": 1, "tag": "BILLED"}})


def test_every_surface_that_defines_the_tags_says_a_dollar_figure_is_the_apis_reported_cost_not_billing():
    versions = [f"reports/phase-d/replay/{t}.md" for t in replay.VERSIONS]
    for rel in sorted(DEFINES_TAGS) + versions:
        text = re.sub(r"\s+", " ", _read(rel))
        assert re.search(r"reported operation cost, not account billing", text), rel
    page = re.sub(r"\s+", " ", _read("reports/phase-d/dashboard/index.html"))
    assert f"a dollar figure with this tag is {DEFINITION}" in page


# ---------------------------------------------------------------- BILLED: only the owner's reading, only in ledger.billed

def test_billed_is_the_owners_balance_reading_in_ledger_billed_and_nowhere_else_in_the_summary():
    summary = _summary()
    assert [p for p, o in _tagged_objects(summary) if o["tag"] == "BILLED"] == (
        ["$.ledger.billed.account", "$.ledger.billed.readings[0]", "$.ledger.billed.readings[1]"] + [f"$.ledger.billed.gates[{i}]" for i in range(6)])
    billed = summary["ledger"]["billed"]
    account = billed["account"]
    assert (account["value"], account["tag"], account["currency"], account["bound"]) == (0.43, "BILLED", "USD", "at most")
    assert account["owner_reading"] == {"by": "owner", "source": ACCOUNT_SOURCE}
    assert "billing lag is unknown" in account["note"] and "cumulative, not per gate" in account["owner_reading"]["source"]
    assert "far less than the ledger recorded" in account["note"] and "not reconciled" in account["note"]
    # both readings are kept, each the owner's, never an API cost
    assert [(r["value"], r["owner_reading"]["source"], r["bound"]) for r in billed["readings"]] == [(0.39, FIRST_READING_SOURCE, "at most"), (0.43, ACCOUNT_SOURCE, "at most")]
    lines = {g["harness_tag"]: g for g in billed["gates"]}
    assert [(g["harness_tag"], g["for_component"]) for g in billed["gates"]] == [
        (V133, "gate-v133"), (V134, "gate-v134"), (V140, "gate-v140"), (V141, "gate-v141"), (V142, "gate-v142"), (V143, "gate-v143")]
    for tag in (V133, V134, V140):
        assert (lines[tag]["value"], lines[tag]["tag"], lines[tag]["reason"]) == (None, "BILLED", NO_GATE_READING)
    # the one gate whose interval holds the owner's two readings carries the difference, as BILLED, with that reading as its source
    assert (lines[V141]["value"], lines[V141]["tag"], lines[V141]["bound"]) == (0.04, "BILLED", "difference of two readings")
    assert lines[V141]["owner_reading"] == {"by": "owner", "source": INTERVAL_SOURCE} and "reason" not in lines[V141]
    # the readings after the last two gates have not been received: null, with that reason (a figure the owner has not given is never filled in)
    for tag in (V142, V143):
        assert (lines[tag]["value"], lines[tag]["tag"], lines[tag]["reason"]) == (None, "BILLED", AWAITED)
    # one BILLED line per gate that exists in the REPLAY, and the exploratory gates are the only gates the ledger has
    assert [c["key"] for c in summary["ledger"]["components"] if c["kind"] == "gate"] == [g["for_component"] for g in billed["gates"]]
    assert "never on an API cost" in billed["rule"] and "D-36" in billed["rule"]
    rest = copy.deepcopy(summary)
    rest["ledger"].pop("billed")
    assert "BILLED" not in json.dumps(rest)  # no API cost (a component, the ledger totals, a kill record) carries it
    replay.check_billed(summary)


def test_billed_is_on_no_passport_and_no_replay_version_file():
    for rel in _phase_d_files():
        if rel.startswith("reports/phase-d/passports/") or re.fullmatch(r"reports/phase-d/replay/harness-v[\d.]+\.(json|md)", rel) or rel.endswith("record_index.md"):
            assert "BILLED" not in _read(rel), rel
    index = _read("reports/phase-d/replay/index.md")
    assert index.count("BILLED") >= 2 and "`BILLED`: an account-balance reading taken by the owner" in index


def test_a_misused_billed_tag_stops_the_build():
    summary = _summary()
    for mutate in (
        lambda s: s["ledger"]["measured"].__setitem__("tag", "BILLED"),
        lambda s: s["ledger"]["components"][0]["measured"].__setitem__("tag", "BILLED"),
        lambda s: s["ledger"]["billed"]["gates"][0].__setitem__("reason", ""),
        lambda s: s["ledger"]["billed"]["gates"][0].__setitem__("value", 0.1),
        lambda s: s["ledger"]["billed"]["account"].__setitem__("owner_reading", {}),
        lambda s: s["ledger"]["billed"]["account"].__setitem__("tag", "API-REPORTED"),
    ):
        broken = copy.deepcopy(summary)
        mutate(broken)
        with pytest.raises(replay.ReplayError):
            replay.check_billed(broken)
    tampered = copy.deepcopy(replay.load_passports(ROOT))
    next(iter(tampered.values()))["cost"]["model"]["tag"] = "BILLED"  # BILLED on a passport value
    with pytest.raises(replay.ReplayError, match="unknown tag"):
        replay.build_replay(passports=tampered)


def test_the_dashboard_shows_the_owners_billed_readings_and_the_billed_lines_in_the_ledger():
    page = _read("reports/phase-d/dashboard/index.html")
    root = check_dashboard.parse(page)
    ledger = next(n for n in root.walk() if n.attrs.get("id") == "ledger")
    numbers = [n for n in check_dashboard.numbers(root) if n.attrs["data-tag"] == "BILLED"]
    # the latest account reading, the two readings, and the difference of the two on the one gate whose interval holds them: each from the owner, none from a record
    assert [(n.text(), n.attrs["data-value"], n.attrs["data-source"]) for n in numbers] == [
        ("$0.4300", "0.43", "owner-balance-reading"), ("$0.3900", "0.39", "owner-balance-reading"),
        ("$0.4300", "0.43", "owner-balance-reading"), ("$0.0400", "0.04", "owner-balance-reading")]
    assert all(_within(n, ledger) for n in numbers) and all(n.attrs.get("data-record") is None for n in numbers)
    chips = [n for n in root.walk() if n.tag == "span" and {"tag", "BILLED"} <= n.classes()]
    assert [_within(c, ledger) for c in chips] == [False] + [True] * 9  # the legend; the account line, the two readings, and one line per gate
    lines = [n for n in ledger.walk() if n.tag == "li" and n.attrs.get("id", "").startswith("billed-")]
    assert [n.attrs["id"] for n in lines] == ["billed-account", "billed-reading-0", "billed-reading-1", "billed-gate-v133", "billed-gate-v134",
                                              "billed-gate-v140", "billed-gate-v141", "billed-gate-v142", "billed-gate-v143"]
    assert "at most" in lines[0].text() and ACCOUNT_SOURCE in lines[0].text() and "billing lag is unknown" in lines[0].text()
    assert FIRST_READING_SOURCE in lines[1].text() and ACCOUNT_SOURCE in lines[2].text()
    assert all(NO_GATE_READING in n.text() and "BILLED" in n.text() for n in lines[3:6])
    assert INTERVAL_SOURCE in lines[6].text() and "difference of two readings" in lines[6].text()  # the one gate with a reading: the interval holding both
    assert all(AWAITED in n.text() and "BILLED" in n.text() for n in lines[7:9])
    assert "not account billing" in " ".join(ledger.text().split())
    assert check_dashboard.problems(page) == []


@pytest.mark.parametrize("rel", LEDGER_TEXTS)
def test_the_texts_that_state_a_ledger_figure_say_it_is_the_apis_reported_cost_and_show_the_balance_reading(rel):
    text = re.sub(r"\s+", " ", _read(rel))
    assert all(part in text for part in HONEST), rel


@pytest.mark.parametrize("rel", ["README.md", "docs/submission/devpost_answers.md", "docs/submission/description.md", "docs/submission/demo_script.md",
                                 "docs/submission/criteria_map.md"])
def test_billed_in_the_texts_is_only_the_owners_balance_reading(rel):
    text = _read(rel)
    assert set(re.findall(r"\$([\d.]+) \[?BILLED", text)) <= BILLED_VALUES  # the owner's readings (and their difference): the only BILLED figures
    assert not re.findall(r"\$(?:0\.39|0\.43|0\.04)(?!\d)(?! \[?BILLED)", text)  # and those figures are never shown without it
    for number, line in enumerate(text.splitlines(), 1):
        if "BILLED" in line:
            assert re.search(r"\$(?:0\.39|0\.43|0\.04) \[?BILLED|account-balance reading|account balance|BILLED lines|BILLED value none|Tags:", line), f"{rel}:{number}: {line[:120]!r}"
    if rel == "README.md":
        section = text.split("## Cost ledger")[1].split("## License")[0]
        assert "$49.61 of $50.00 at 19:37 local time, 2026-10-01" in section and "Nebius billing lag is unknown" in section
        # three gates without a reading, and the last two whose readings have not been received yet (the lines of ledger.billed.gates without a value)
        assert section.count("BILLED value none") == 5 and "has not been received" in section
        assert all(tag in section for tag in ("harness-v1.3.3", "harness-v1.3.4", "harness-v1.4.0", "harness-v1.4.1", "harness-v1.4.2", "harness-v1.4.3"))


# ---------------------------------------------------------------- no number changed value

def test_no_number_changed_value_in_the_passports_and_the_replay_version_files():
    original = (V132, V133, V134)
    rels = [r for r in _passport_files() if any(f"/passports/{tag}/" in r for tag in original)]
    count, digest = PRE_RELABEL_DIGESTS["passports"]
    assert len(rels) == count and _digest(rels) == digest
    assert len(_passport_files()) == 65  # the passports of v1.4.0 / v1.4.1 / v1.4.2 / v1.4.3 are new files, not changes
    for tag in original:
        assert _digest([f"reports/phase-d/replay/{tag}.json"]) == PRE_RELABEL_DIGESTS[tag], tag


# What the Phase D update for harness-v1.4.0 / v1.4.1 / v1.4.2 legitimately changed in the summary, each with its new value (the headline is now counted over every
# exploratory gate entry-run, the inventory and the register grew, the ledger gained the new seals, smokes and gates). Nothing else of the pre-relabel table moves.
UPDATED_BY_PHASE_D = {
    "$.headline.gate_entry_runs": 24,
    "$.headline.apparent_recoveries": 2,
    "$.headline.with_recorded_model_attempt": 17,
    "$.inventory.records": 65,
    "$.inventory.defects": 43,
    "$.inventory.defects_by_status.fixed-and-gated": 22,
    "$.inventory.defects_by_status.fixed-unvalidated": 9,
    "$.inventory.defects_by_status.open": 12,
}
RENAMED = {"$.headline.recovered_by_llm_loop": "$.headline.recoveries_with_applied_model_repair"}  # same definition, a name that implies no cause; 0 before v1.4.2, 1 now


def test_every_tagged_value_of_the_summary_before_the_relabel_is_still_there_with_the_same_value():
    now = dict(_tagged_pairs(_summary()))
    assert len(PRE_RELABEL_SUMMARY) == 73
    expected = {path: UPDATED_BY_PHASE_D.get(path, value) for path, value in PRE_RELABEL_SUMMARY.items() if path not in RENAMED and not path.startswith("$.ledger.")}
    changed = {path: (value, now.get(path, "MISSING")) for path, value in expected.items() if now.get(path, "MISSING") != value}
    assert not changed, changed
    assert PRE_RELABEL_SUMMARY["$.headline.recovered_by_llm_loop"] == 0 and now["$.headline.recoveries_with_applied_model_repair"] == 1  # v1.4.2 #7
    assert "$.headline.recovered_by_llm_loop" not in now
    # the ledger: the first five components and the two older kill records are exactly as before; the totals grew by the new seals, smokes and gates
    for path, value in PRE_RELABEL_SUMMARY.items():
        if path.startswith("$.ledger.components[") or path.startswith("$.ledger.kill_records["):
            assert now[path] == value, path
    assert (round(now["$.ledger.measured"], 4), round(now["$.ledger.estimated"], 4), round(now["$.ledger.derived"], 4), round(now["$.ledger.total"], 4)) == (
        26.2069, 1.4761, 1.4874, 29.1704)
    assert PRE_RELABEL_SUMMARY["$.ledger.total"] == 10.1349119627  # the pre-v1.4.0 figure, kept here as the record of what moved
