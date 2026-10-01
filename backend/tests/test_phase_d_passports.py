"""Phase D1: passports rebuilt from committed record blobs (offline; harness-v1.3.2 / v1.3.3 / v1.3.4 records)."""

from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phase_d import check_tags, passports, records, verify_passports  # noqa: E402
from phase_d.build_passports import INDEX, expected_files  # noqa: E402

V132, V133, V134, V140, V141, V142 = "harness-v1.3.2", "harness-v1.3.3", "harness-v1.3.4", "harness-v1.4.0", "harness-v1.4.1", "harness-v1.4.2"
V14 = (V140, V141, V142)


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


class TamperedSource:
    def __init__(self, base: CachedSource, path: str, blob: bytes) -> None:
        self.base, self.path, self.blob = base, path, blob

    def list_dir(self, directory: str) -> list[str]:
        return self.base.list_dir(directory)

    def read(self, path: str) -> bytes:
        return self.blob if path == self.path else self.base.read(path)


def _flip_one_byte(blob: bytes) -> bytes:
    marker = b'"run_kind": "'
    at = blob.index(marker) + len(marker)
    changed = blob[:at] + bytes([blob[at] ^ 0x20]) + blob[at + 1:]  # one letter changes case; the JSON stays valid
    assert len(changed) == len(blob) and sum(a != b for a, b in zip(changed, blob)) == 1
    return changed


@pytest.fixture(scope="module")
def source() -> CachedSource:
    return CachedSource()


@pytest.fixture(scope="module")
def built(source):
    return passports.build_all(source)


def _passport(built, tag: str, record_set: str, entry: str) -> dict:
    return next(p for r, p in built if (r.harness_tag, r.record_set.name, r.entry) == (tag, record_set, entry))


# ---------------------------------------------------------------- inventory and record ids

def test_there_are_61_records_with_unique_ids(built):
    assert len(built) == records.EXPECTED_TOTAL == 61
    per_set = {}
    for record, _ in built:
        per_set[(record.harness_tag, record.record_set.name)] = per_set.get((record.harness_tag, record.record_set.name), 0) + 1
    assert per_set == {(V132, "control"): 20, (V132, "control/infra_retries"): 1, (V132, "treatment"): 20, (V133, "smoke"): 4, (V134, "smoke"): 4,
                       (V140, "gate"): 4, (V141, "gate"): 4, (V142, "gate"): 4}
    assert len({p["record_id"] for _, p in built}) == 61


def test_record_id_is_tag_arm_entry_and_the_blob_sha256(built):
    for record, passport in built:
        sha = hashlib.sha256(record.blob).hexdigest()
        assert passport["record_id"] == f"{record.harness_tag}/{record.arm}/{record.entry}@{sha}"
        assert passport["record"]["sha256"] == sha and passport["image_id"].get("value") != passport["record_id"]


def test_control_and_treatment_arms_are_never_merged(built):
    arms = {(r.arm, r.entry) for r, _ in built if r.harness_tag == V132 and r.record_set.name in ("control", "treatment")}
    assert len(arms) == 40


def test_the_hash_is_taken_over_the_committed_blob_not_the_worktree_file(tmp_path):
    """Fails if a record is ever hashed from the worktree: the checkout below is CRLF, the blob is LF."""
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "T")
    git("config", "core.autocrlf", "false")
    lf = b'{\n  "batch": {"harness_tag": "harness-v9", "arm": "treatment", "entry_id": 3}\n}\n'
    file = tmp_path / "runs" / "03_x.json"
    file.parent.mkdir()
    file.write_bytes(lf)
    git("add", ".")
    git("commit", "-m", "record")
    file.write_bytes(lf.replace(b"\n", b"\r\n"))  # what core.autocrlf=true leaves in a Windows worktree

    src = records.GitBlobSource(tmp_path)
    assert src.list_dir("runs") == ["runs/03_x.json"]
    blob = src.read("runs/03_x.json")
    record = records.Record("runs/03_x.json", records.RecordSet("harness-v9", "smoke", "runs", 1), blob, json.loads(blob))
    assert blob == lf
    assert record.record_id == f"harness-v9/treatment/03@{hashlib.sha256(lf).hexdigest()}"
    assert record.record_id != f"harness-v9/treatment/03@{hashlib.sha256(file.read_bytes()).hexdigest()}"


def test_the_build_never_opens_a_record_in_the_worktree(source, monkeypatch):
    import builtins
    import io

    real = io.open

    def guarded(file, *args, **kwargs):
        if "corpus_v2_batch" in str(file).replace("\\", "/"):
            raise AssertionError(f"worktree record opened: {file}")
        return real(file, *args, **kwargs)

    monkeypatch.setattr(io, "open", guarded)
    monkeypatch.setattr(builtins, "open", guarded)
    assert len(passports.build_all(source)) == 61


def test_the_build_makes_no_network_connection(source, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("network access during the passport build")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    assert len(expected_files(source)) == 62


# ---------------------------------------------------------------- verifier and tamper detection

def test_the_verifier_rebuilds_every_passport_with_zero_diff(source):
    assert verify_passports.verify(ROOT, source) == []


def test_the_real_verifier_reads_git_and_passes():
    assert verify_passports.verify() == []


def test_the_build_is_deterministic(source):
    assert expected_files(source) == expected_files(source)


def test_the_record_index_lists_all_49_record_ids(built):
    index = (ROOT / INDEX).read_text(encoding="utf-8")
    assert all(f"`{p['record_id']}`" in index for _, p in built)
    assert index == passports.record_index(built)


def test_one_changed_byte_in_any_record_changes_its_id_and_hash_and_fails_verification(source, built):
    for record, passport in built:
        tampered = TamperedSource(source, record.path, _flip_one_byte(record.blob))
        rebuilt = next(p for r, p in passports.build_all(tampered) if r.path == record.path)
        assert rebuilt["record_id"] != passport["record_id"], record.path
        assert rebuilt["passport_hash"] != passport["passport_hash"], record.path
        problems = verify_passports.verify(ROOT, tampered)
        assert f"differs from the rebuild: {passports.passport_path(record)}" in problems, record.path
        assert f"differs from the rebuild: {INDEX}" in problems, record.path


def test_an_edited_passport_file_fails_verification(source, tmp_path):
    for rel, content in expected_files(source).items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(content)
    for doc in {s["path"] for _, p in passports.build_all(source) for n in p["annotations"] for s in n["sources"]} | {
            f["report"] for f in passports.GATE_FILES.values()}:
        (tmp_path / doc).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / doc).write_bytes((ROOT / doc).read_bytes())
    assert verify_passports.verify(tmp_path, source) == []

    target = tmp_path / passports.PASSPORT_DIR / V133 / "smoke" / "11_JindongGu__VoteAttack.json"
    edited = json.loads(target.read_text(encoding="utf-8"))
    edited["annotations"] = []  # drop the artefact annotation
    target.write_bytes(passports.serialize(edited))
    problems = verify_passports.verify(tmp_path, source)
    assert any("differs from the rebuild" in p for p in problems) and any("passport_hash does not recompute" in p for p in problems)

    (tmp_path / passports.PASSPORT_DIR / V133 / "smoke" / "99_extra.json").write_text("{}", encoding="utf-8")
    assert any("passport without a record" in p for p in verify_passports.verify(tmp_path, source))


def test_crlf_checkout_of_a_passport_still_verifies(source, tmp_path):
    files = expected_files(source)
    rel = next(r for r in files if r.endswith("08_edenton__svg.json") and V134 in r)
    assert verify_passports._lf(files[rel].replace(b"\n", b"\r\n")) == files[rel]


# ---------------------------------------------------------------- tags

def test_every_number_in_every_passport_is_tagged(built):
    for record, passport in built:
        assert check_tags.violations(passport) == [], record.path
    assert check_tags.check_files(ROOT) == {}


def test_the_tag_check_fails_on_an_untagged_number(tmp_path):
    assert check_tags.violations({"cost": 0.28})
    assert check_tags.violations({"cost": {"value": 0.28}})
    assert check_tags.violations({"cost": {"value": 0.28, "tag": "GUESSED"}})
    assert check_tags.violations({"list": [{"value": 1, "tag": "API-REPORTED"}, 2]})
    assert check_tags.violations({"x": {"value": 1, "tag": "MEASURED"}})  # the old tag name is no longer a tag (D-36)
    assert check_tags.violations({"x": {"value": 0.39, "tag": "BILLED"}})  # BILLED is for the owner's balance reading, never a passport value
    assert check_tags.violations({"x": {"value": 1, "tag": "API-REPORTED"}}) == []
    assert check_tags.violations({"x": {"value": 55, "tag": "DERIVED"}})  # no quoted source
    assert check_tags.violations({"x": {"value": 55, "tag": "DERIVED", "source": {"record_id": "r"}}})
    assert check_tags.violations({"x": {"value": None}})  # null without a reason
    assert check_tags.violations({"x": {"value": 0.28, "tag": "ESTIMATED"}, "flag": True, "s": "55s",
                                  "d": {"value": 55, "tag": "DERIVED", "source": {"record_id": "r", "line": "limit of 55s"}}}) == []

    bad = tmp_path / passports.PASSPORT_DIR / "x.json"
    bad.parent.mkdir(parents=True)
    bad.write_text(json.dumps({"cost": {"value": 0.28}}), encoding="utf-8")
    assert list(check_tags.check_files(tmp_path)) == [f"{passports.PASSPORT_DIR}/x.json"]
    assert check_tags.check_files(tmp_path / "empty") != {}


def test_measured_values_are_copied_from_the_record_unchanged(built):
    for record, passport in built:
        d = record.data
        assert passport["verdict"]["verdict"] == d["result"]["verdict"]
        assert passport["cost"]["value"] == d["cost_guard"]["spent_usd"]
        assert passport["cost"]["model"]["value"] == d["cost_guard"]["model_spent_usd"]
        assert len(passport["attempts"]) == len(d["result"]["attempts"])
        for a, pa in zip(d["result"]["attempts"], passport["attempts"]):
            assert (pa["type"], pa["gate_decision"]) == (a["origin"], a["gate_decision"])
            assert pa["exit_code"].get("value") == a.get("exit_code")


def test_entry_8_v134_cost_is_estimated_and_split(built):
    cost = _passport(built, V134, "smoke", "08")["cost"]
    assert cost["tag"] == "ESTIMATED"
    assert (cost["measured"]["tag"], round(cost["measured"]["value"], 4)) == ("API-REPORTED", 0.3939)
    assert (cost["estimated"]["tag"], round(cost["estimated"]["value"], 4)) == ("ESTIMATED", 0.2842)
    assert cost["measured"]["value"] + cost["estimated"]["value"] == pytest.approx(cost["value"], abs=1e-9)
    assert cost["cost_events"][0]["usd"]["tag"] == "ESTIMATED"


def test_only_entry_8_v134_carries_an_estimated_cost(built):
    estimated = [(r.harness_tag, r.entry) for r, p in built if p["cost"]["tag"] == "ESTIMATED"]
    assert estimated == [(V134, "08"), (V140, "08")]  # the two gate entries whose operation was stopped (v1.4.1 and v1.4.2 stopped none)
    for record, passport in built:
        if record.harness_tag == V132:
            assert passport["cost"]["estimated"] == {"value": None, "reason": "not recorded by harness-v1.3.2"}


def test_the_v134_gate_cost_is_shown_as_measured_plus_estimated(built):
    gate = _passport(built, V134, "smoke", "03")["badge"]["gate_cost"]
    assert gate["tag"] == "ESTIMATED"
    assert (round(gate["value"], 3), round(gate["measured"]["value"], 3), round(gate["estimated"]["value"], 3)) == (3.396, 3.112, 0.284)
    gate133 = _passport(built, V133, "smoke", "03")["badge"]["gate_cost"]
    assert gate133["tag"] == "API-REPORTED" and round(gate133["value"], 4) == 2.9298 and "estimated" not in gate133


# ---------------------------------------------------------------- derived values

def test_kill_values_are_derived_and_quote_their_source_line(built):
    for entry, attempt, funded, wall in (("08", 0, 55, 55), ("11", 2, 119, 119)):
        record = next(r for r, _ in built if (r.harness_tag, r.entry) == (V134, entry))
        execution = _passport(built, V134, "smoke", entry)["attempts"][attempt]["execution"]
        lines = [e["line"] for e in record.data["events"]]
        for name, value in (("funded_seconds", funded), ("wall_seconds", wall), ("killed_by", "cost_guard")):
            field = execution[name]
            assert (field["value"], field["tag"]) == (value, "DERIVED")
            assert field["source"]["record_id"] == record.record_id and field["source"]["line"] in lines
    step = _passport(built, V134, "smoke", "08")["attempts"][0]["execution"]["killed_step_seconds"]
    assert (step["value"], step["tag"], step["source"]["field"]) == (33, "DERIVED", "cost_guard.cost_events[0].note")


def test_no_kill_is_invented_where_none_is_recorded(built):
    killed = [(r.harness_tag, r.entry, a["attempt"]) for r, p in built for a in p["attempts"] if a["execution"]["killed_by"].get("tag")]
    assert killed == [(V134, "08", "attempt-0"), (V134, "11", "attempt-2"),
                      (V140, "08", "attempt-0-missing_compiler_build_essential"), (V140, "11", "attempt-0")]
    # harness-v1.4.0 #8 attempt 0 holds an era lock (exit 1) and a stopped rule step (no exit code): only the stopped step carries the kill
    era = _passport(built, V140, "gate", "08")["attempts"][0]
    assert era["exit_code"]["value"] == 1 and era["execution"]["killed_by"].get("tag") is None


# ---------------------------------------------------------------- absent fields

def test_fields_a_harness_version_did_not_store_are_null_with_the_version(built):
    for record, passport in built:
        for a in passport["attempts"]:
            if record.harness_tag in V14:
                continue  # harness-v1.4.x stores the citations: `cited` is the list (see test_v14x_passports_...)
            assert a["cited"] == {"value": None, "reason": "tavily_sources empty on all attempts — consistent with D-21 open"}
            if record.harness_tag in (V132, V133):
                expected = {"value": None, "reason": f"not recorded by {record.harness_tag}"}
                assert a["consulted"] == a["reason_no_citation"] == a["silent_exit"] == expected
            if record.harness_tag == V132:
                assert a["execution"]["seconds"] == {"value": None, "reason": "not recorded by harness-v1.3.2"}


def test_v134_declined_attempt_has_consulted_but_no_reason_d26(built):
    passport = _passport(built, V134, "smoke", "03")
    declined = passport["attempts"][1]
    assert declined["outcome"] == "declined" and len(declined["consulted"]) == 3
    assert declined["reason_no_citation"] == {"value": None, "reason": "not present on this attempt in the record"}
    assert "D-26" in [n["id"] for n in passport["annotations"]]
    assert "content" not in declined["consulted"][0] and declined["consulted"][0]["ref"] == "[1]"


def test_outcome_uses_the_gate_rule_applied_means_a_re_execution_was_reached(built):
    attempts = _passport(built, V134, "smoke", "11")["attempts"]
    assert [a["outcome"] for a in attempts] == ["applied", "applied", "gate_passed_not_executed"]
    assert _passport(built, V134, "smoke", "03")["attempts"][3]["outcome"] == "rejected"
    assert _passport(built, V134, "smoke", "03")["attempts"][3]["reject_reason"]


def test_the_infra_retry_passport_is_superseded_and_has_no_image(built):
    retry = _passport(built, V132, "control/infra_retries", "07")
    assert retry["superseded_by"] == _passport(built, V132, "control", "07")["record_id"]
    assert retry["image_id"] == {"value": None, "reason": "no baseline sandbox recorded"}
    assert retry["verdict"]["verdict"] == "INFRA_ERROR"
    others = [p for r, p in built if r.record_set.name != "control/infra_retries"]
    assert all(p["superseded_by"] == {"value": None, "reason": "not superseded"} and p["image_id"]["value"] for p in others)


# ---------------------------------------------------------------- badges and annotations

def test_badges_are_per_version_and_use_that_versions_measured_line(built):
    b133 = _passport(built, V133, "smoke", "11")["badge"]
    b134 = _passport(built, V134, "smoke", "11")["badge"]
    assert b133["text"] == "EXPLORATORY — did not pass its pre-registered gate. a: 1/4 (measured), c: 0 citations in 7 searches."
    assert b133["figures"][0]["annotation"] == ("the one recovery (entry 11) was later identified as a smoke-limit artefact; "
                                                "measured line unchanged.")
    assert b134["text"] == ("EXPLORATORY — did not pass its pre-registered gate. a: 0/4, "
                            "c: 0 citations (7 attempts consulted, 21 refs, 6 reasons recorded).")
    c = b134["figures"][2]
    assert [c[k]["value"] for k in ("citations", "attempts_consulted", "references_consulted", "reasons_recorded")] == [0, 7, 21, 6]
    assert b133["figures"][2]["searches"]["tag"] == "DERIVED" and len(b133["figures"][2]["searches"]["source"]) == 7
    for record, passport in built:
        badge = passport["badge"]
        assert badge["exploratory"] is (record.harness_tag in (V133, V134, V140, V141, V142))
        assert ("EXPLORATORY" in badge["text"]) is badge["exploratory"]
        if badge["exploratory"]:
            assert badge["links"]["run_records"] and badge["links"]["cost_line"]["quote"] and badge["links"]["gate_result"]


def test_entry_11_v133_keeps_its_measured_verdict_and_carries_the_artefact_annotation(built):
    passport = _passport(built, V133, "smoke", "11")
    assert passport["verdict"]["verdict"] == "RUNS_AFTER_REPAIR" and passport["verdict"]["recovery"] is True
    note = next(n for n in passport["annotations"] if n["id"] == "ENTRY-11-SMOKE-LIMIT-ARTEFACT")
    assert "smoke-limit artefact" in note["text"] and note["related_record"] == _passport(built, V134, "smoke", "11")["record_id"]
    assert [a["type"] for a in passport["attempts"]] == ["time_machine"]  # no model repair attempt in the record


def test_every_annotation_quotes_a_source_that_exists(built):
    for _, passport in built:
        assert verify_passports._quote_problems(passport, ROOT) == []
        for note in passport["annotations"]:
            assert note["sources"]


def test_the_model_produced_a_recorded_repair_attempt_in_5_of_the_8_gate_runs(built):
    gate = [p for r, p in built if r.harness_tag in (V133, V134)]
    assert len(gate) == 8
    assert sum(1 for p in gate if any(a["type"] == "model" for a in p["attempts"])) == 5
    recovered = [(p["harness_tag"], p["entry"]["id"]) for p in gate if p["verdict"]["verdict"] in passports.RECOVERED]
    assert recovered == [(V133, "11")]  # the smoke-limit artefact; produced by the time machine alone


def test_d28_the_results_tables_hash_is_the_crlf_worktree_hash_and_is_reconciled_with_the_blob(built):
    listed = [(r, p["record"]["results_tables_sha256"]) for r, p in built if p["record"]["results_tables_sha256"].get("value")]
    assert len(listed) == 40 and {(r.harness_tag, r.record_set.name) for r, _ in listed} == {(V132, "control"), (V132, "treatment")}
    index = (ROOT / INDEX).read_text(encoding="utf-8")
    for record, field in listed:
        assert field["value"] != record.sha256 and field["equals_sha256_of_blob_with_crlf"] is True and "D-28" in field["label"]
        assert field["value"] == hashlib.sha256(record.blob.replace(b"\n", b"\r\n")).hexdigest()
        assert f"| `{record.record_id}` | `{record.sha256}` | `{field['value']}` |" in index
    others = [p["record"]["results_tables_sha256"] for r, p in built if (r, p["record"]["results_tables_sha256"]) not in listed]
    assert len(others) == 21 and all(o == {"value": None, "reason": "not listed in reports/corpus-v2.1/results_tables.json"} for o in others)
