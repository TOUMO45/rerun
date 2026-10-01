"""Phase D2: REPLAY of harness-v1.3.2 / v1.3.3 / v1.3.4 from committed records, cross-checked against the passports."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phase_d import build_replay, passports, records, replay  # noqa: E402

V132, V133, V134 = replay.VERSIONS
TAG_SUFFIX = re.compile(r" \[(MEASURED|ESTIMATED|DERIVED)\]")
CODE_SPAN = re.compile(r"(`+).+?\1")
NUMBER = re.compile(r"\d+(?:\.\d+)?(?:e-?\d+)?")


class CachedSource:
    """Every blob the build needs, read from git once; tests tamper with the in-memory copy."""

    def __init__(self) -> None:
        git = records.GitBlobSource()
        self.dirs = {rs.directory: git.list_dir(rs.directory) for rs in records.RECORD_SETS}
        paths = [p for listing in self.dirs.values() for p in listing if records.ENTRY_FILE.match(p.rsplit("/", 1)[1])]
        paths += [f["result"] for f in passports.GATE_FILES.values()] + [passports.RESULTS_TABLES]
        self.blobs = {p: git.read(p) for p in paths}

    def list_dir(self, directory: str) -> list[str]:
        return list(self.dirs[directory])

    def read(self, path: str) -> bytes:
        return self.blobs[path]


@pytest.fixture(scope="module")
def source() -> CachedSource:
    return CachedSource()


@pytest.fixture(scope="module")
def stored() -> dict[str, dict]:
    return replay.load_passports(ROOT)


@pytest.fixture(scope="module")
def docs(source, stored) -> dict[str, dict]:
    return replay.build_replay(source, stored)


@pytest.fixture(scope="module")
def files(source, stored) -> dict[str, bytes]:
    return replay.expected_files(source, stored)


def _md(files, tag: str) -> str:
    return files[f"{replay.REPLAY_DIR}/{tag}.md"].decode("utf-8")


def _entry(docs, tag: str, entry: str, record_set: str | None = None) -> dict:
    return next(x for x in docs[tag]["entries"] if x["entry"]["id"] == entry and record_set in (None, x["record_set"]))


def _walk(obj, path="$"):
    yield path, obj
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk(v, f"{path}[{i}]")


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _tagged(doc: dict) -> list[tuple[str, dict]]:
    return [(p, o) for p, o in _walk(doc) if isinstance(o, dict) and "tag" in o and "value" in o]


# ---------------------------------------------------------------- determinism, offline, stored files

def test_the_replay_output_is_byte_identical_across_two_runs(source, stored, files):
    again = replay.expected_files(source, stored)
    digest = lambda fs: hashlib.sha256(b"".join(k.encode() + b"\0" + v for k, v in sorted(fs.items()))).hexdigest()  # noqa: E731
    assert digest(again) == digest(files) and list(again) == list(files)
    assert sorted(files) == sorted([f"{replay.REPLAY_DIR}/{t}.{ext}" for t in replay.VERSIONS for ext in ("json", "md")] + [f"{replay.REPLAY_DIR}/index.md"])


def test_any_network_call_during_replay_fails(source, stored, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("network access during REPLAY")

    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, refuse)
    assert len(replay.expected_files(source, stored)) == 7


def test_the_stored_replay_files_are_identical_to_a_rebuild():
    assert build_replay.check() == []


def test_the_output_carries_no_build_timestamp_and_no_local_path(files, docs):
    for rel, content in files.items():
        text = content.decode("utf-8")
        assert "RERUN_Nvidia" not in text and "generated_at" not in text and "built_at" not in text, rel
    for doc in docs.values():
        assert set(doc) == {"schema", "harness_tag", "role", "badge", "scorecard", "batch", "entries"}


def test_the_index_lists_each_file_with_its_hash(files):
    index = files[f"{replay.REPLAY_DIR}/index.md"].decode("utf-8")
    for rel, content in files.items():
        if not rel.endswith("index.md"):
            assert hashlib.sha256(content).hexdigest() in index and rel.rsplit("/", 1)[1] in index


# ---------------------------------------------------------------- badges and scorecards

def test_the_exploratory_badge_is_on_v133_and_v134_and_absent_on_v132(docs, files):
    assert docs[V133]["badge"]["text"] == "EXPLORATORY — did not pass its pre-registered gate. a: 1/4 (measured), c: 0 citations in 7 searches."
    assert docs[V134]["badge"]["text"] == ("EXPLORATORY — did not pass its pre-registered gate. a: 0/4, "
                                           "c: 0 citations (7 attempts consulted, 21 refs, 6 reasons recorded).")
    for tag in (V133, V134):
        assert docs[tag]["badge"]["exploratory"] is True and docs[tag]["role"] == "EXPLORATORY"
        assert f"> `{docs[tag]['badge']['text']}`" in _md(files, tag)
        assert docs[tag]["badge"]["links"]["run_records"] and docs[tag]["badge"]["links"]["cost_line"]["quote"]
    assert docs[V132]["badge"]["exploratory"] is False and docs[V132]["role"] == "PRE-REGISTERED ANCHOR"
    assert "EXPLORATORY" not in _md(files, V132) and "EXPLORATORY" not in json.dumps(docs[V132])
    index = files[f"{replay.REPLAY_DIR}/index.md"].decode("utf-8")
    assert index.index(V132) < index.index(V133) < index.index(V134) and index.count("— EXPLORATORY") == 2


def test_the_badge_is_the_d1_badge_verbatim(docs, stored):
    for tag, doc in docs.items():
        originals = [p["badge"] for p in stored.values() if p["harness_tag"] == tag]

        def strip(obj):
            if isinstance(obj, dict):
                return {k: strip(v) for k, v in obj.items() if k != "ref"}
            return [strip(v) for v in obj] if isinstance(obj, list) else obj

        assert all(strip(doc["badge"]) == original for original in originals)


def test_each_version_scorecard_uses_its_own_measured_line(docs):
    def crit(tag):
        return {f["criterion"]: f for f in docs[tag]["scorecard"]["criteria"]}

    c133, c134 = crit(V133), crit(V134)
    assert (c133["a"]["recovered"]["value"], c133["a"]["entries"]["value"], c133["a"]["ok"]) == (1, 4, False)
    assert "smoke-limit artefact; measured line unchanged" in c133["a"]["annotation"]
    assert (c134["a"]["recovered"]["value"], c134["a"]["entries"]["value"], c134["a"]["ok"]) == (0, 4, False)
    assert [(c[k]["ok"]) for c in (c133, c134) for k in "abcd"] == [False, True, False, True] * 2
    assert (c134["b"]["applied"]["value"], c134["b"]["proposed"]["value"]) == (2, 4)
    assert (c133["c"]["citations"]["value"], c133["c"]["searches"]["value"]) == (0, 7)
    assert [c134["c"][k]["value"] for k in ("citations", "attempts_consulted", "references_consulted", "reasons_recorded")] == [0, 7, 21, 6]
    assert (c133["d"]["cost_cap_endings"]["value"], c134["d"]["cost_cap_endings"]["value"]) == (0, 2)
    assert docs[V133]["scorecard"]["gate_passed"] is False and docs[V134]["scorecard"]["gate_passed"] is False


def test_v132_is_the_anchor_0_of_16_with_control_and_treatment_separate(docs):
    primary = docs[V132]["scorecard"]["criteria"][0]
    assert (primary["recovered"]["value"], primary["denominator"]["value"], primary["recovered"]["tag"]) == (0, 16, "MEASURED")
    sets = {s["record_set"]: s for s in docs[V132]["scorecard"]["record_sets"]}
    assert list(sets) == ["control", "control/infra_retries", "treatment"]
    assert [len(sets[k]["records"]) for k in sets] == [20, 1, 20] and not set(sets["control"]["records"]) & set(sets["treatment"]["records"])
    counts = {k: {v["verdict"]: v["count"]["value"] for v in s["verdicts"]} for k, s in sets.items()}
    assert counts["control"] == {"BLOCKED": 17, "INDETERMINATE": 2, "RUNS_CLEAN": 1}
    assert counts["treatment"] == {"BLOCKED": 15, "INDETERMINATE": 4, "RUNS_CLEAN": 1}
    assert counts["control/infra_retries"] == {"INFRA_ERROR": 1}
    retry = _entry(docs, V132, "07", "control/infra_retries")
    assert retry["superseded_by"] == _entry(docs, V132, "07", "control")["record_id"]


# ---------------------------------------------------------------- numbers: tagged, and equal to the passport field

def test_every_number_in_the_replay_json_is_tagged_and_equals_its_passport_field(docs, stored):
    for tag, doc in docs.items():
        order = doc["batch"]["run_order"]
        for path, obj in _walk(doc):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if _is_number(value):
                        assert key == "value" and obj.get("tag") in passports.TAGS, f"{tag} {path}.{key}: untagged number {value!r}"
            elif isinstance(obj, list):
                assert not any(_is_number(v) for v in obj), f"{tag} {path}: bare number in a list"
        for path, obj in _tagged(doc):
            pointers = [k for k in ("ref", "sum_of", "count_of") if k in obj]
            assert len(pointers) == 1, f"{tag} {path}: a tagged value needs exactly one pointer to the passports"
            if "ref" in obj:
                field = replay.resolve(stored[obj["ref"]["record_id"]], obj["ref"]["field"])
                assert (field["value"], field["tag"]) == (obj["value"], obj["tag"]), f"{tag} {path}"
            elif "sum_of" in obj:
                upto = order[: order.index(obj["sum_of"]["run_order_through"]) + 1]
                parts = [replay.resolve(stored[rid], obj["sum_of"]["field"]) for rid in upto]
                assert obj["value"] == round(sum(p["value"] for p in parts), 10), f"{tag} {path}"
                assert {p["tag"] for p in parts} == {obj["tag"]}, f"{tag} {path}"
            else:
                count = obj["count_of"]
                assert obj["value"] == sum(1 for rid in count["records"] if replay.resolve(stored[rid], count["field"]) == count["equals"])
                assert obj["tag"] == "MEASURED"


def test_absent_values_keep_their_reason_and_pointer(docs, stored):
    for doc in docs.values():
        for path, obj in _walk(doc):
            if isinstance(obj, dict) and "value" in obj and obj["value"] is None:
                assert obj.get("reason") and ("ref" in obj or "sum_of" in obj), path
    cited = _entry(docs, V134, "03")["timeline"][2]["cited"]
    assert cited["reason"] == "tavily_sources empty on all attempts — consistent with D-21 open"
    assert docs[V132]["batch"]["estimated"] == {"value": None, "reason": "not recorded by harness-v1.3.2",
                                                "sum_of": {"field": "cost.estimated", "run_order_through": docs[V132]["batch"]["run_order"][-1]}}


def test_every_derived_value_carries_its_quoted_source_line_and_record_id(docs, source):
    by_id = {r.record_id: r for r in records.load_records(source)}
    seen = 0
    for doc in docs.values():
        for path, obj in _tagged(doc):
            if obj["tag"] != "DERIVED":
                continue
            seen += 1
            sources = obj["source"] if isinstance(obj["source"], list) else [obj["source"]]
            assert sources, path
            for src in sources:
                assert src["record_id"] in by_id and src["line"], path
                assert replay.resolve(by_id[src["record_id"]].data, src["field"]) == src["line"], path
    assert seen > 100


# ---------------------------------------------------------------- the entries the directive names

def test_entry_11_v133_shows_runs_after_repair_unchanged_with_the_artefact_annotation_beside_it(docs, files):
    entry = _entry(docs, V133, "11")
    verdict = entry["timeline"][-1]
    assert (verdict["step"], verdict["verdict"], verdict["recovery"]) == ("verdict", "RUNS_AFTER_REPAIR", True)
    note = next(n for n in verdict["annotations"] if n["id"] == "ENTRY-11-SMOKE-LIMIT-ARTEFACT")
    assert "smoke-limit artefact" in note["text"] and note["related_record"] == _entry(docs, V134, "11")["record_id"]
    assert [s["step"] for s in entry["timeline"]] == ["baseline", "era_lock", "verdict"]  # no model attempt: the time machine alone
    lines = _md(files, V133).splitlines()
    at = next(i for i, line in enumerate(lines) if line.startswith("- verdict: `RUNS_AFTER_REPAIR`"))
    assert lines[at + 1].startswith("  - annotation `ENTRY-11-SMOKE-LIMIT-ARTEFACT`")


def test_the_two_cost_cap_kills_in_v134_show_the_cap_line_crossed_at_the_recorded_second(docs, files):
    md = _md(files, V134)
    for entry_id, step_index, second in (("08", 1, 55), ("11", 3, 119)):
        entry = _entry(docs, V134, entry_id)
        execution = entry["timeline"][step_index]["execution"]
        line = execution["cap_line"]
        assert execution["killed"] is True and line["crossed"] is True
        assert (line["limit_second"]["value"], line["crossed_at_second"]["value"]) == (second, second)
        assert line["limit_second"]["tag"] == line["crossed_at_second"]["tag"] == "DERIVED"
        assert f"{second}s" in line["limit_second"]["source"]["line"] and f"stopped at {second}s" in line["crossed_at_second"]["source"]["line"]
        assert (execution["killed_by"]["value"], execution["killed_by"]["tag"]) == ("cost_guard", "DERIVED")
        assert entry["timeline"][-1]["reason_code"] == "COST_CAP"
        stopped = [op for op in entry["cost"]["operations"] if op["killed"]]
        assert len(stopped) == 1 and stopped[0]["stopped_at_second"]["value"] == second
        assert f"cap line at second {second} [DERIVED] crossed at second {second} [DERIVED]: `true`" in md
    assert _entry(docs, V134, "08")["timeline"][1]["execution"]["killed_step_seconds"]["value"] == 33
    kills = [(tag, x["entry"]["id"]) for tag, doc in docs.items() for x in doc["entries"] for s in x["timeline"] if s.get("execution", {}).get("killed")]
    assert kills == [(V134, "08"), (V134, "11")]


def test_each_attempt_shows_gate_outcome_citation_and_execution(docs):
    steps = _entry(docs, V134, "03")["timeline"]
    assert [s["step"] for s in steps] == ["baseline", "era_lock", "attempt", "attempt", "attempt", "verdict"]
    assert [s["outcome"] for s in steps[1:5]] == ["applied", "declined", "applied", "rejected"]
    assert steps[2]["consulted_count"]["value"] == 3 and steps[2]["reason_no_citation"]["value"] is None  # D-26
    assert steps[4]["reject_reason"] and steps[3]["silent_exit"] is True and isinstance(steps[3]["reason_no_citation"], str)
    assert _entry(docs, V134, "11")["timeline"][3]["outcome"] == "gate_passed_not_executed"
    assert steps[1]["era_lock"]["python"] == "3.6" and steps[1]["execution"]["seconds"]["value"] == 60


def test_cost_accumulates_against_the_entry_cap_and_the_batch_cap(docs):
    v134 = docs[V134]
    assert (round(v134["batch"]["measured"]["value"], 3), round(v134["batch"]["estimated"]["value"], 3), v134["batch"]["cap"]["value"]) == (3.112, 0.284, 3.5)
    assert (v134["batch"]["measured"]["tag"], v134["batch"]["estimated"]["tag"]) == ("MEASURED", "ESTIMATED")
    assert [x["entry"]["id"] for rid in v134["batch"]["run_order"] for x in v134["entries"] if x["record_id"] == rid] == ["11", "07", "03", "08"]
    last = _entry(docs, V134, "08")["cost"]
    assert last["batch_cumulative"]["measured"]["value"] == v134["batch"]["measured"]["value"] and last["batch_cumulative"]["over_batch_cap"] is False
    assert (last["entry_total"]["tag"], last["measured"]["tag"], last["estimated"]["tag"]) == ("ESTIMATED", "MEASURED", "ESTIMATED")
    assert not any(x["cost"]["over_entry_cap"] for x in v134["entries"])
    over = [x["entry"]["id"] for x in docs[V132]["entries"] if x["cost"]["over_entry_cap"]]
    assert over == ["13", "16"]  # D-7, shown as recorded
    assert round(docs[V132]["batch"]["measured"]["value"], 2) == 21.76 and docs[V133]["batch"]["estimated"]["value"] == 0.0


# ---------------------------------------------------------------- mismatch = build failure

def test_a_passport_that_disagrees_with_the_record_stops_the_build(source, stored, docs):
    rid = _entry(docs, V133, "11")["record_id"]
    for mutate in (
        lambda p: p["verdict"].__setitem__("verdict", "BLOCKED"),
        lambda p: p["cost"].__setitem__("value", 0.5),
        lambda p: p["attempts"][0]["exit_code"].__setitem__("value", 1),
        lambda p: p["badge"]["figures"][0]["recovered"].__setitem__("value", 0),
        lambda p: p["badge"].__setitem__("text", p["badge"]["text"].replace("1/4", "0/4")),
    ):
        tampered = copy.deepcopy(stored)
        mutate(tampered[rid])
        with pytest.raises(replay.ReplayError):
            replay.build_replay(source, tampered)

    kill = _entry(docs, V134, "08")["record_id"]
    for mutate in (
        lambda p: p["attempts"][0]["execution"]["funded_seconds"].__setitem__("value", 60),
        lambda p: p["attempts"][0]["execution"]["wall_seconds"]["source"].__setitem__("line", "[cost_guard] operation stopped at 55s"),
        lambda p: p["cost"]["operations"][0]["spend"].__setitem__("value", 0.1),
    ):
        tampered = copy.deepcopy(stored)
        mutate(tampered[kill])
        with pytest.raises(replay.ReplayError):
            replay.build_replay(source, tampered)

    missing = {k: v for k, v in stored.items() if k != rid}
    with pytest.raises(replay.ReplayError):
        replay.build_replay(source, missing)


def test_a_changed_record_with_unchanged_passports_stops_the_build(source, stored):
    class Tampered:
        def __init__(self, path, blob):
            self.path, self.blob = path, blob

        def list_dir(self, directory):
            return source.list_dir(directory)

        def read(self, path):
            return self.blob if path == self.path else source.read(path)

    path = "runs/corpus_v2_batch/harness-v1.3.3/smoke/11_JindongGu__VoteAttack.json"
    blob = source.read(path).replace(b'"verdict": "RUNS_AFTER_REPAIR"', b'"verdict": "RUNS_CLEAN"')
    assert blob != source.read(path)
    with pytest.raises(replay.ReplayError):
        replay.build_replay(Tampered(path, blob), stored)


# ---------------------------------------------------------------- replay.md: no number that is not in the JSON, none taken from text

def test_replay_md_contains_no_number_that_is_not_also_in_the_json(files):
    for tag in replay.VERSIONS:
        in_md = set(NUMBER.findall(_md(files, tag)))
        in_json = set(NUMBER.findall(files[f"{replay.REPLAY_DIR}/{tag}.json"].decode("utf-8")))
        assert in_md and in_md <= in_json, f"{tag}: {sorted(in_md - in_json)[:10]}"


def test_no_displayed_number_comes_from_text_every_one_is_a_tagged_passport_field(files, docs):
    """Outside quoted code spans, replay.md has no digit except a tagged value followed by its tag."""
    for tag in replay.VERSIONS:
        tagged = {(json.dumps(o["value"]), o["tag"]) for _, o in _tagged(docs[tag]) if _is_number(o["value"])}
        shown = set()
        for number, line in enumerate(_md(files, tag).splitlines(), 1):
            prose = CODE_SPAN.sub("", line)
            assert "`" not in prose, f"{tag}.md line {number}: unbalanced code span"
            position = 0
            for match in NUMBER.finditer(prose):
                assert match.start() >= position, f"{tag}.md line {number}"
                suffix = TAG_SUFFIX.match(prose, match.end())
                assert suffix, f"{tag}.md line {number}: number {match.group()!r} outside a quote without a tag"
                assert (match.group(), suffix.group(1)) in tagged, f"{tag}.md line {number}: {match.group()} [{suffix.group(1)}] is not a tagged value of the JSON"
                shown.add((match.group(), suffix.group(1)))
                position = suffix.end()
        assert shown, tag


def test_the_code_span_helper_quotes_any_text():
    for text in ("plain", "with ` one", "``two`` inside", "`edge`", "", "ends with `"):
        span = replay.code(text)
        assert CODE_SPAN.sub("", f"x {span} y") == "x  y", text
    assert replay.show({"value": 55, "tag": "DERIVED"}) == "55 [DERIVED]" and replay.show({"value": None, "reason": "r"}) == "null (`r`)"
