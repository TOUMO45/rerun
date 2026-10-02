"""Phase D2: REPLAY of harness-v1.3.2 / v1.3.3 / v1.3.4 / v1.4.0 / v1.4.1 / v1.4.2 / v1.4.3 from committed records, cross-checked against the passports."""

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

V132, V133, V134, V140, V141, V142, V143 = replay.VERSIONS
TAG_SUFFIX = re.compile(r" \[(API-REPORTED|ESTIMATED|DERIVED)\]")
CODE_SPAN = re.compile(r"(`+).+?\1")
NUMBER = re.compile(r"\d+(?:\.\d+)?(?:e-?\d+)?")


class CachedSource:
    """Blobs read from git once and cached; tests tamper with the in-memory copy."""

    def __init__(self) -> None:
        self.git = records.GitBlobSource()
        self.dirs: dict[str, list[str]] = {}
        self.blobs: dict[str, bytes] = {}

    def list_dir(self, directory: str) -> list[str]:
        if directory not in self.dirs:
            self.dirs[directory] = self.git.list_dir(directory)
        return list(self.dirs[directory])

    def read(self, path: str) -> bytes:
        if path not in self.blobs:
            self.blobs[path] = self.git.read(path)
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


@pytest.fixture(scope="module")
def summary(files) -> dict:
    return json.loads(files[f"{replay.REPLAY_DIR}/summary.json"].decode("utf-8"))


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
    assert sorted(files) == sorted([f"{replay.REPLAY_DIR}/{t}.{ext}" for t in replay.VERSIONS for ext in ("json", "md")] + [f"{replay.REPLAY_DIR}/index.md", f"{replay.REPLAY_DIR}/summary.json"])


def test_any_network_call_during_replay_fails(source, stored, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("network access during REPLAY")

    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, refuse)
    assert len(replay.expected_files(source, stored)) == 16


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

def test_the_exploratory_badge_is_on_every_gated_version_and_absent_on_v132(docs, files):
    assert docs[V133]["badge"]["text"] == "EXPLORATORY — did not pass its pre-registered gate. a: 1/4 (measured), c: 0 citations in 7 searches."
    assert docs[V134]["badge"]["text"] == ("EXPLORATORY — did not pass its pre-registered gate. a: 0/4, "
                                           "c: 0 citations (7 attempts consulted, 21 refs, 6 reasons recorded).")
    for tag in (V133, V134, V140, V141, V142, V143):
        assert docs[tag]["badge"]["exploratory"] is True and docs[tag]["role"] == "EXPLORATORY"
        assert f"> `{docs[tag]['badge']['text']}`" in _md(files, tag)
        assert docs[tag]["badge"]["links"]["run_records"] and docs[tag]["badge"]["links"]["cost_line"]["quote"]
    assert docs[V132]["badge"]["exploratory"] is False and docs[V132]["role"] == "PRE-REGISTERED ANCHOR"
    assert "EXPLORATORY" not in _md(files, V132) and "EXPLORATORY" not in json.dumps(docs[V132])
    index = files[f"{replay.REPLAY_DIR}/index.md"].decode("utf-8")
    assert index.index(V132) < index.index(V133) < index.index(V134) < index.index(V140) < index.index(V141) < index.index(V142) < index.index(V143) and index.count("— EXPLORATORY") == 6
    # each version's own measured line, as recorded (the figures are never merged across versions)
    assert docs[V140]["badge"]["text"] == ("EXPLORATORY — did not pass its pre-registered gate. a: 0/4, "
                                           "c: 3 citations (" + docs[V140]["badge"]["text"].split("c: 3 citations (")[1])
    assert docs[V141]["badge"]["text"].startswith("EXPLORATORY — did not pass its pre-registered gate. a: 0/4, c: 6 citations (")
    assert docs[V142]["badge"]["text"].startswith("EXPLORATORY — did not pass its pre-registered gate. a: 1/4, c: 0 citations (")
    assert docs[V143]["badge"]["text"].startswith("EXPLORATORY — did not pass its pre-registered gate. a: 0/4, c: 7 citations (")
    assert "annotation" not in docs[V143]["badge"]["figures"][0]  # no RUNS_* verdict in the last gate: nothing to annotate as a smoke-criterion pass
    # a smoke-criterion pass is said to be one, beside the figure
    a142 = docs[V142]["badge"]["figures"][0]
    assert a142["annotation"] == passports.SMOKE_CRITERION_NOTE and "annotation" not in docs[V141]["badge"]["figures"][0]
    assert [f["criterion"] for f in docs[V142]["badge"]["figures"]] == ["a", "b", "c", "d", "e"] and docs[V142]["badge"]["figures"][4]["ok"] is True


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
    assert (primary["recovered"]["value"], primary["denominator"]["value"], primary["recovered"]["tag"]) == (0, 16, "API-REPORTED")
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
                        assert key == "value" and obj.get("tag") in passports.RECORD_TAGS, f"{tag} {path}.{key}: untagged number {value!r}"  # never BILLED here
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
                assert obj["tag"] == "API-REPORTED"


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
    assert kills == [(V134, "08"), (V134, "11"), (V140, "08"), (V140, "11")]  # harness-v1.4.1 and v1.4.2 stopped no operation


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
    assert (v134["batch"]["measured"]["tag"], v134["batch"]["estimated"]["tag"]) == ("API-REPORTED", "ESTIMATED")
    assert [x["entry"]["id"] for rid in v134["batch"]["run_order"] for x in v134["entries"] if x["record_id"] == rid] == ["11", "07", "03", "08"]
    last = _entry(docs, V134, "08")["cost"]
    assert last["batch_cumulative"]["measured"]["value"] == v134["batch"]["measured"]["value"] and last["batch_cumulative"]["over_batch_cap"] is False
    assert (last["entry_total"]["tag"], last["measured"]["tag"], last["estimated"]["tag"]) == ("ESTIMATED", "API-REPORTED", "ESTIMATED")
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


# ---------------------------------------------------------------- summary.json: headline, defect register, ledger

def test_the_headline_counts_are_tagged_counts_of_records(summary, docs):
    h = summary["headline"]
    lists = ("artefact", "smoke_criterion_recovery", "per_version")
    values = {k: v["value"] for k, v in h.items() if k not in lists}
    # the count over EVERY exploratory gate entry-run (six gates of four entries), not over the first two gates only
    assert values == {"gate_entry_runs": 24, "apparent_recoveries": 2, "apparent_recoveries_annotated_as_artefact": 1,
                      "recoveries_by_time_machine_alone": 1, "recoveries_with_applied_model_repair": 1, "with_recorded_model_attempt": 17}
    assert "v1.4.3" in h["gate_entry_runs"]["count_of"]["where"]
    gate = {x["record_id"] for tag in (V133, V134, V140, V141, V142, V143) for x in docs[tag]["entries"]}
    for key, v in h.items():
        if key not in lists:
            assert v["tag"] == "API-REPORTED" and v["value"] == len(v["count_of"]["records"]) and set(v["count_of"]["records"]) <= gate
    assert set(h["gate_entry_runs"]["count_of"]["records"]) == gate
    assert [(a["harness_tag"], a["entry"]) for a in h["artefact"]] == [(V133, "11")] and "smoke-limit artefact" in h["artefact"][0]["annotation"]["text"]
    assert [(a["harness_tag"], a["entry"]) for a in h["smoke_criterion_recovery"]] == [(V142, "07")]
    assert "smoke-criterion verdict" in h["smoke_criterion_recovery"][0]["annotation"]["text"]
    # every apparent recovery is exactly one of the two: the artefact (no model attempt) or the smoke-criterion recovery (an applied model repair)
    assert set(h["apparent_recoveries"]["count_of"]["records"]) == set(h["recoveries_by_time_machine_alone"]["count_of"]["records"]) | set(
        h["recoveries_with_applied_model_repair"]["count_of"]["records"])
    per = {p["harness_tag"]: tuple(p[k]["value"] for k in ("entry_runs", "apparent_recoveries", "indeterminate", "blocked")) for p in h["per_version"]}
    assert per == {V133: (4, 1, 0, 2), V134: (4, 0, 2, 2), V140: (4, 0, 2, 2), V141: (4, 0, 0, 4), V142: (4, 1, 3, 0), V143: (4, 0, 1, 3)}
    assert [p["gate_passed"] for p in h["per_version"]] == [False] * 6


def test_the_headline_build_stops_if_the_records_stop_supporting_it(docs):
    changed = copy.deepcopy(docs)
    next(x for x in changed[V133]["entries"] if x["entry"]["id"] == "11")["timeline"][-1]["annotations"] = []
    with pytest.raises(replay.ReplayError):
        replay._headline(changed)
    changed = copy.deepcopy(docs)  # the smoke-criterion recovery loses its annotation: the statement no longer holds
    next(x for x in changed[V142]["entries"] if x["entry"]["id"] == "07")["timeline"][-1]["annotations"] = []
    with pytest.raises(replay.ReplayError):
        replay._headline(changed)
    changed = copy.deepcopy(docs)  # a new apparent recovery that is neither
    next(x for x in changed[V141]["entries"] if x["entry"]["id"] == "07")["timeline"][-1]["verdict"] = "RUNS_AFTER_REPAIR"
    with pytest.raises(replay.ReplayError):
        replay._headline(changed)


def test_the_defect_register_is_d1_to_d43_with_quoted_sources(summary, source, docs):
    rows = summary["defects"]["rows"]
    assert [r["id"] for r in rows] == [f"D-{i}" for i in range(1, 44)]
    assert {r["status"] for r in rows} == {"fixed-and-gated", "fixed-unvalidated", "open"} == set(summary["defects"]["status_rule"])
    status = {r["id"]: r["status"] for r in rows}
    assert all(status[f"D-{i}"] == "open" for i in (1, 6, 7, 12, 13, 21, 25, 26, 27, 28, 36, 43))  # a partial fix stays open; a gate that died stays open (D-43)
    # the last gate observed D-39, D-40 and D-41 fixed live; the sustained-run line (D-42) made no live run, so it is fixed-unvalidated
    assert all(status[f"D-{i}"] == "fixed-and-gated" for i in (23, 24, 30, 32, 33, 34, 37, 38, 39, 40, 41)) and all(status[f"D-{i}"] == "fixed-unvalidated" for i in (29, 31, 35, 42))
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in ("fixed-and-gated", "fixed-unvalidated", "open")}
    assert counts == {"fixed-and-gated": 22, "fixed-unvalidated": 9, "open": 12}
    # D-24 was fixed after the third exploratory gate and labelled unvalidated then; its basis is still the offline test, and since the sealed versions carry it the
    # last gate report shows the rule firing live: that gate line is what moves it to fixed-and-gated (and the row says so)
    d24 = next(r for r in rows if r["id"] == "D-24")
    assert d24["status"] == "fixed-and-gated" and d24["basis"][0]["path"] == "backend/tests/test_d24_build_essential.py"
    assert d24["basis"][0]["quote"].startswith("def test_") and any(b["path"].endswith("GATE_REPORT_v1.4.2.md") for b in d24["basis"])
    d23 = next(r for r in rows if r["id"] == "D-23")
    assert d23["status"] == "fixed-and-gated" and any("The checkpoint fix worked as designed" == b["quote"] for b in d23["basis"])
    for r in rows:
        for src in [r["registered"]] + r["basis"]:
            assert src["quote"] in (ROOT / src["path"]).read_bytes().decode("utf-8").replace("\r\n", "\n"), r["id"]
        assert not re.search(r"\d", r["title"] + r["note"]), r["id"]  # no number is displayed from this text
        if r["status"] == "fixed-and-gated":  # a committed gate report line (or METHODOLOGY) states the fix was observed working live
            assert len(r["basis"]) >= 1 and any("smoke_gate" in b["path"] or "/gate/GATE_REPORT_" in b["path"] or b["path"] == "METHODOLOGY.md" for b in r["basis"]), r["id"]
    annotated = {r["id"]: {p["record_id"] for p in r["passports"]} for r in rows}
    assert len(annotated["D-28"]) == 40 and len(annotated["D-13"]) == 4
    assert annotated["D-26"] == {_entry(docs, V134, "03")["record_id"]} and annotated["D-24"] == {_entry(docs, V134, "07")["record_id"]}
    # D-41 (stderr truncated at 65,535 bytes, confirmed by the probe) sits beside the entry-3 record of every version, beside the last gate's entry 3 where the fix was seen,
    # beside the one silent-exit record that was checked and found not cut, and beside the records the D6 scan flags (build logs that end mid-line, the pre-registered entries 3 and 6,
    # a RUNS_AFTER_REPAIR record whose verdict does not rest on the stream)
    short = {rid.split("@")[0] for rid in annotated["D-41"]}
    assert short == {"harness-v1.3.2/treatment/03", "harness-v1.3.2/treatment/06", "harness-v1.3.3/treatment/03", "harness-v1.3.3/treatment/11", "harness-v1.3.4/treatment/03",
                     "harness-v1.4.0/treatment/03", "harness-v1.4.0/treatment/08", "harness-v1.4.1/treatment/03", "harness-v1.4.1/treatment/11", "harness-v1.4.2/treatment/03",
                     "harness-v1.4.2/treatment/08", "harness-v1.4.3/treatment/03"}
    assert annotated["D-37"] == {_entry(docs, tag, "07")["record_id"] for tag in (V140, V141, V142)}
    assert annotated["D-38"] == {_entry(docs, V141, "11")["record_id"], _entry(docs, V142, "11")["record_id"], _entry(docs, V143, "11")["record_id"]}
    assert annotated["D-43"] == {_entry(docs, V143, "03")["record_id"], _entry(docs, V143, "07")["record_id"]}
    assert annotated["D-39"] == {_entry(docs, V141, "08")["record_id"], _entry(docs, V143, "03")["record_id"]}
    assert annotated["D-40"] == {_entry(docs, V142, "03")["record_id"], _entry(docs, V142, "11")["record_id"], _entry(docs, V143, "11")["record_id"]}
    assert annotated["D-42"] == set()  # harness-level: the sustained-run line ran on no entry


def test_a_missing_defect_quote_stops_the_build(docs, source, monkeypatch):
    from phase_d import defects

    broken = copy.deepcopy(defects.REGISTER)
    broken[0]["basis"][0]["quote"] = "this sentence is not in the report"
    monkeypatch.setattr(defects, "REGISTER", broken)
    with pytest.raises(replay.ReplayError):
        replay.build_summary(docs, source)


def test_the_ledger_is_recomputed_from_records_split_and_a_lower_bound(summary, source, stored):
    ledger = summary["ledger"]
    assert [c["key"] for c in ledger["components"]] == [
        "seal-attempt-one-v133", "seal-repeat-v133", "gate-v133", "seal-v134", "gate-v134", "seal-v140-optionb", "seal-v140", "smoke-v140", "gate-v140",
        "seal-v141", "smoke-v141", "gate-v141", "seal-v142", "smoke-v142", "gate-v142", "probe-d41", "seal-v143-new", "seal-v143-v141", "seal-v143-v142",
        "seal-v143-v140", "seal-v143-final", "interrupted-gate-attempts-v143", "smoke-v143", "gate-v143"]
    total_m = total_e = total_d = 0.0
    for c in ledger["components"]:
        if c["kind"] == "seal":
            value = 0.0
            for part in c["measured"]["sum_of_records"]:
                for rid in part["records"]:
                    path, sha = rid.split("@")
                    blob = source.read(path)
                    assert hashlib.sha256(blob).hexdigest() == sha
                    value += json.loads(blob)[part["field"]]
            if c["estimated"]["value"] is None:
                assert c["estimated"] == {"value": None, "reason": "no estimate field in the seal-verification records"}
            else:  # a seal that stopped an operation: the estimate is a stored field (or a difference of two), each part pointing at its record
                assert c["key"] in ("seal-v140", "seal-v141", "seal-v143-v141") and c["estimated"]["tag"] == "ESTIMATED"
                parts = c["estimated"]["sum_of_records"]
                assert c["estimated"]["value"] == round(sum(p["estimated_part"]["value"] for p in parts), 10)
                for p in parts:
                    record = json.loads(source.read(p["record"].split("@")[0]))
                    stored_value = (record["cost"]["estimated_upper_bound_usd"] if "cost" in record and isinstance(record["cost"], dict)
                                    else round(record["cost_usd"] - record["measured_completed_usd"], 10))
                    assert p["estimated_part"]["value"] == stored_value and p["estimated_part"]["record_field"]["record"] == p["record"]
                total_e += c["estimated"]["value"]
        elif c["kind"] == "interrupted":
            # spend parsed from the cost guard's own log lines of gate attempts that were killed before they wrote a record: DERIVED, each part quoting its line
            value = 0.0
            assert c["measured"]["value"] == 0.0 and c["estimated"]["value"] is None and c["derived"]["tag"] == "DERIVED"
            parts = c["derived"]["sum_of_parts"]
            assert len(parts) == 16 and c["derived"]["value"] == round(sum(x["value"] for x in parts), 10)
            for part in parts:
                path, sha = part["source"]["record_id"].split("@")
                blob = source.read(path)
                assert hashlib.sha256(blob).hexdigest() == sha and part["tag"] == "DERIVED"
                assert part["source"]["line"].strip() in blob.decode("utf-8").replace("\r\n", "\n")
                assert any(f"{part['value']:.{n}f}" in part["source"]["line"] for n in (4, 6)), part
            total_d += c["derived"]["value"]
        elif c["kind"] == "smoke":
            value = 0.0
            for part in c["measured"]["sum_of_records"][0]["fields"]:
                path, sha = part["record"].split("@")
                blob = source.read(path)
                assert hashlib.sha256(blob).hexdigest() == sha
                data = json.loads(blob)
                value += resolve_field(data, part["field"])
            assert c["estimated"]["value"] is None and "D-27" in c["estimated"]["reason"]
        else:
            value = sum(stored[rid]["cost"]["measured"]["value"] for rid in c["measured"]["sum_of"]["records"])
            assert c["estimated"]["value"] == round(sum(stored[rid]["cost"]["estimated"]["value"] for rid in c["estimated"]["sum_of"]["records"]), 10)
            total_e += c["estimated"]["value"]
        assert c["measured"] ["value"] == round(value, 10) and c["measured"]["tag"] == "API-REPORTED"
        total_m += c["measured"]["value"]
    assert ledger["measured"]["value"] == round(total_m, 10) and ledger["estimated"]["value"] == round(total_e, 10) and ledger["derived"]["value"] == round(total_d, 10)
    # rebuilt from the records, the ledger is the figure the last gate report states (a lower bound, D-27): the report shows 29.1704 and its rows add up to it only
    # when they are not rounded (the unrounded sum is 29.17037...)
    assert (round(ledger["measured"]["value"], 4), round(ledger["estimated"]["value"], 4), round(ledger["derived"]["value"], 4), round(ledger["total"]["value"], 4)) == (
        26.2069, 1.4761, 1.4874, 29.1704)
    assert ledger["total"]["value"] == round(total_m + total_e + total_d, 10)
    assert (ledger["measured"]["tag"], ledger["estimated"]["tag"], ledger["derived"]["tag"], ledger["total"]["tag"]) == ("API-REPORTED", "ESTIMATED", "DERIVED", "ESTIMATED")
    assert ledger["lower_bound"]["defect"] == "D-27" and "29.1704" in ledger["reported_line"]["quote"] and "room $2.8296" in ledger["lower_bound"]["line"]["quote"]
    assert round(32.0 - ledger["total"]["value"], 4) == 2.8296  # the room the report states, from the rebuilt total
    # every gate report's own ledger statement stays beside the rebuilt one, and the running total each stated is reproduced from the records up to that gate
    assert [h["harness_tag"] for h in ledger["reported_history"]] == [V134, V140, V141, V142, V143]
    assert "$10.134" in ledger["reported_history"][0]["quote"] and "$14.6495" in ledger["reported_history"][1]["quote"] and "$18.5083" in ledger["reported_history"][2]["quote"]
    order = [c["key"] for c in ledger["components"]]
    running = {tag: round(sum(c["measured"]["value"] + (c["estimated"]["value"] or 0.0) + (c["derived"]["value"] or 0.0) for c in ledger["components"][: order.index(key) + 1]), 4)
               for tag, key in ((V134, "gate-v134"), (V140, "gate-v140"), (V141, "gate-v141"), (V142, "gate-v142"), (V143, "gate-v143"))}
    assert running == {V134: 10.1349, V140: 14.6495, V141: 18.5083, V142: 22.4935, V143: 29.1704}
    kills = ledger["kill_records"]
    assert [k["killed_seconds"]["value"] for k in kills] == [None, 26.7, 26.3, 25.8, None, 23.634523099994112, 20.029718199992203, 25.9]
    assert [k["component"] for k in kills] == ["seal-attempt-one-v133", "seal-repeat-v133", "seal-v134", "seal-v140-optionb", "seal-v140", "seal-v141", "seal-v143-v141", "seal-v143-final"]
    assert [k["via"] for k in kills] == [None, "client_wait_timeout", "client_wait_timeout", "client_wait_timeout", None, "client_wait_timeout", "client_wait_timeout",
                                         "client_wait_timeout"] and kills[0]["error"]
    for k in kills:
        path, _ = k["record"].split("@")
        if k["killed_seconds"]["value"] is not None:
            assert json.loads(source.read(path))["killed_seconds"] == k["killed_seconds"]["value"] and k["killed_seconds"]["tag"] == "API-REPORTED"
    assert [(k["component"], k["estimated_cost"]["value"]) for k in kills if "estimated_cost" in k] == [("seal-v140", 0.4998), ("seal-v141", 0.2008934463), ("seal-v143-v141", 0.3044517166)]
    assert all(k["estimated_cost"]["tag"] == "ESTIMATED" for k in kills if "estimated_cost" in k)


def resolve_field(data, field):
    """`runs[1].cost_usd` or `cost_usd` of an upload smoke record."""
    return replay.resolve(data, field)


def test_every_number_in_the_summary_is_tagged_with_a_pointer(summary):
    for path, obj in _walk(summary):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if _is_number(value):
                    assert key == "value" and obj.get("tag") in passports.TAGS, f"{path}.{key}"  # TAGS includes BILLED: ledger.billed only
        elif isinstance(obj, list):
            assert not any(_is_number(v) for v in obj), path
    for path, obj in _tagged(summary):
        # a DERIVED value points at the log line it was parsed from (`source`, a quoted line with its record id) or at the parts that are
        pointers = sum(k in obj for k in ("count_of", "sum_of", "sum_of_records", "sum_of_components", "sum_of_parts", "source", "record_field", "owner_reading", "for_component"))
        # a BILLED gate line points at its gate component AND, when the owner's interval reading exists, at that reading (null lines carry a reason instead)
        assert pointers == (2 if "for_component" in obj and "owner_reading" in obj else 1), path
        if obj["tag"] == "BILLED":
            assert path.startswith("$.ledger.billed."), path


def test_entries_carry_the_blob_hash_and_the_d28_worktree_hash(docs):
    for tag, doc in docs.items():
        for x in doc["entries"]:
            assert x["record_id"].endswith("@" + x["record_sha256"])
            listed = x["results_tables_sha256"]
            if tag == V132 and x["record_set"] in ("control", "treatment"):
                assert listed["value"] and listed["value"] != x["record_sha256"] and "D-28" in listed["label"]
            else:
                assert listed["value"] is None and listed["reason"]
