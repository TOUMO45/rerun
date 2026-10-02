"""Phase D6: the scan for claims that still rest on a truncated stream (D-41), and the annotations that follow from it."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phase_d import passports, records as rec, truncation_scan as ts  # noqa: E402

# The records the scan flags, by committed path: eleven of the sixty-five (the entry-3 records of every version before harness-v1.4.3, the pre-registered entry 6,
# two cost-cap entries whose build log is cut, and the two entry-11 records that look cut or carry a progress line as their error).
SUSPECTS = {
    "harness-v1.3.2/treatment/03", "harness-v1.3.2/treatment/06", "harness-v1.3.3/treatment/03", "harness-v1.3.3/treatment/11", "harness-v1.3.4/treatment/03",
    "harness-v1.4.0/treatment/03", "harness-v1.4.0/treatment/08", "harness-v1.4.1/treatment/03", "harness-v1.4.1/treatment/11", "harness-v1.4.2/treatment/03",
    "harness-v1.4.2/treatment/08",
}


class _Source:
    def __init__(self) -> None:
        self.git = rec.GitBlobSource()
        self.cache: dict[str, bytes] = {}
        self.dirs: dict[str, list[str]] = {}

    def list_dir(self, directory: str) -> list[str]:
        if directory not in self.dirs:
            self.dirs[directory] = self.git.list_dir(directory)
        return list(self.dirs[directory])

    def read(self, path: str) -> bytes:
        if path not in self.cache:
            self.cache[path] = self.git.read(path)
        return self.cache[path]


@pytest.fixture(scope="module")
def source() -> _Source:
    return _Source()


@pytest.fixture(scope="module")
def data(source) -> dict:
    return ts.scan(source)


def _short(record_id: str) -> str:
    return record_id.split("@")[0]


def _fake(result: dict) -> rec.Record:
    data = {"batch": {"harness_tag": "harness-v9", "arm": "treatment", "entry_id": 1}, "result": result}
    return rec.Record("runs/x/01_x.json", rec.RecordSet("harness-v9", "gate", "runs/x", 1), json.dumps(data).encode("utf-8"), data)


def test_the_stored_scan_is_identical_to_a_rebuild(source):
    files = ts.expected_files(source)
    for path, content in files.items():
        assert (ROOT / path).read_bytes().replace(b"\r\n", b"\n") == content, path


def test_the_scan_flags_these_eleven_records_and_no_other(data):
    assert data["records_scanned"] == 65 == rec.EXPECTED_TOTAL
    assert {_short(r["record_id"]) for r in data["records"] if r["suspect"]} == SUSPECTS and data["suspects"] == 11
    # the headline does not depend on it: of the eleven, the one with a RUNS_* verdict rests on liveness at the smoke limit, not on its output
    runs = [_short(r["record_id"]) for r in data["records"] if r["suspect"] and not r["verdict_rests_on_stream_content"]]
    assert runs == ["harness-v1.3.3/treatment/11"] and data["suspect_runs_verdicts"] == 1


def test_a_cut_looking_tail_a_clean_tail_a_short_tail_and_a_junk_error_are_told_apart():
    full = "x" * 1990
    tail = "  gcc -shared -Wl,--no"
    cut = ts.scan_record(_fake({"verdict": "BLOCKED", "taxonomy_code": "RUNTIME_ERROR_OTHER", "attempts": [{"stderr_tail": full + tail}]}))
    assert cut["suspect"] and cut["cut_looking"][0]["length"] == len(full + tail)
    error_end = ts.scan_record(_fake({"verdict": "BLOCKED", "attempts": [{"stderr_tail": full + "\nValueError: bad input\n"}]}))
    assert not error_end["suspect"] and error_end["full_length_tails_ending_at_an_error"] == 1
    line_end = ts.scan_record(_fake({"verdict": "BLOCKED", "attempts": [{"stderr_tail": full + "\n[notice] To update, run: pip install --upgrade pip\n"}]}))
    assert not line_end["suspect"]
    short = ts.scan_record(_fake({"verdict": "BLOCKED", "attempts": [{"stderr_tail": "x" * 1000}]}))  # the whole stream fit: it cannot have been cut at the SDK limit
    assert not short["suspect"]
    junk = ts.scan_record(_fake({"verdict": "BLOCKED", "last_error": "17.6", "error_chain": [{"error": "ModuleNotFoundError: No module named 'x'"}, {"error": "1"}], "attempts": []}))
    assert junk["suspect"] and [j["field"] for j in junk["junk_error"]] == ["last_error", "error_chain[1]"]
    clean_run = ts.scan_record(_fake({"verdict": "RUNS_AFTER_REPAIR", "attempts": [{"stderr_tail": full + "  73%|"}]}))
    assert clean_run["suspect"] and clean_run["verdict_rests_on_stream_content"] is False  # looks cut, but a RUNS_* verdict does not rest on the stream


def test_the_scan_reads_blobs_not_the_worktree(source, monkeypatch):
    real = Path.read_bytes

    def guarded(self):
        if "corpus_v2_batch" in str(self).replace("\\", "/"):
            raise AssertionError(f"worktree record opened: {self}")
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", guarded)
    assert ts.scan(source)["records_scanned"] == 65


def test_every_suspect_has_a_d41_annotation_in_its_passport_and_no_other_record_but_the_fixed_one_has_one(source, data):
    built = passports.build_all(source)
    annotated = {_short(p["record_id"]) for _, p in built if any(a["id"] == "D-41" for a in p["annotations"])}
    # the eleven suspects, and the harness-v1.4.3 entry 3 where the fix was seen working
    assert annotated == SUSPECTS | {"harness-v1.4.3/treatment/03"}
    assert {_short(r["record_id"]) for r in data["records"] if r["suspect"]} <= annotated


def test_the_annotations_say_what_was_probed_what_is_inferred_and_what_is_only_suspected(source):
    built = {_short(p["record_id"]): p for _, p in passports.build_all(source)}

    def d41(record: str) -> str:
        return next(a for a in built[record]["annotations"] if a["id"] == "D-41")["text"]

    probed = d41("harness-v1.4.2/treatment/03")
    assert "stderr truncated at 65,535 bytes, D-41" in probed and "re-ran this record's operation 5" in probed and "CUDA error" in probed
    for record in ("harness-v1.3.2/treatment/03", "harness-v1.3.3/treatment/03", "harness-v1.3.4/treatment/03", "harness-v1.4.0/treatment/03", "harness-v1.4.1/treatment/03"):
        text = d41(record)
        assert "stderr truncated at 65,535 bytes, D-41" in text and "inference" in text and "not a measurement of this run" in text, record  # never "the same CUDA error" as fact
    for record in ("harness-v1.3.2/treatment/06", "harness-v1.4.0/treatment/08", "harness-v1.4.2/treatment/08"):
        text = d41(record)
        assert "possibly truncated" in text and "suspected, not probed" in text and "truncation_scan.md" in text, record
    assert "rests on the process being alive" in d41("harness-v1.3.3/treatment/11") and "was not cut" not in d41("harness-v1.3.3/treatment/11")
    assert "ends at the shell's `Killed` line" in d41("harness-v1.4.1/treatment/11")


def test_no_verdict_changed_because_of_the_annotations(source):
    for record, passport in ((r, p) for r, p in passports.build_all(source)):
        assert passport["verdict"]["verdict"] == (record.data["result"] or {}).get("verdict"), record.path
        assert passport["verdict"]["taxonomy_code"] == (record.data["result"] or {}).get("taxonomy_code"), record.path


def test_no_stream_of_the_four_final_gate_records_was_cut_and_the_api_said_so(source):
    """The one version that stores the API's own flag: every stream of every stored operation says `truncated` false, and no attempt lists a cut stream."""
    records = [r for r in rec.load_records(source) if r.harness_tag == "harness-v1.4.3"]
    assert len(records) == 4
    streams = 0
    for record in records:
        for op in record.data["operations"]:
            if "streams" not in op:  # an operation that ran no command (an upload, a release) has no streams
                continue
            for name in ("stdout", "stderr"):
                flag = op["streams"][name]["truncated"]
                assert flag is False, (record.path, op.get("role"), name)
                streams += 1
        for attempt in record.data["result"]["attempts"]:
            assert not (attempt.get("execution") or {}).get("output_cut"), record.path
    assert streams == 68  # thirty-four operations that ran a command, two streams each: a real number of streams was checked, not an empty list
    assert max(op["streams"]["stderr"]["bytes"] for r in records for op in r.data["operations"] if "streams" in op) == 400941  # entry 3's stream, whole
