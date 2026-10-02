"""D6 red-team scan: which committed records still rest on a stream that the SDK may have cut (D-41).

Every record stores a run's output only as a tail of at most 2000 characters per attempt (`stdout_tail`, `stderr_tail`), and before harness-v1.4.3 no record stored the
API's `truncated` flag. The SDK cut each stream at its default limit and kept the START of it, and the harness kept the tail of what it received, so a cut stream's stored tail
ends where the cut fell, usually in the middle of a line. This module reads the committed blobs (never the worktree) and lists, per record:

  * `cut_looking`: an attempt whose stored tail has the full stored length (the stream received was at least that long, so it could have been cut) and does not end at a line
    terminator or an error line (it ends mid-line, mid-progress-bar or mid-build-log);
  * `junk_error`: a recorded error text (`last_error`, `first_repo_error`, `error_chain[]`) with no word in it (`17.6`, `1`, a progress line): a label taken from text that is not an error.

It is a heuristic, not a measurement: a tail cannot prove a cut (the one proof is the live probe of 2026-10-02 on harness-v1.4.2 entry 3), a stream cut exactly at a line end
would pass it, and a record whose tail is shorter than the stored length cannot have been cut at all (the whole stream fit). Verdicts RUNS_CLEAN and RUNS_AFTER_REPAIR rest on the
exit code and on the process being alive at the smoke limit, not on stream content; the BLOCKED / INDETERMINATE labels and the recorded errors do rest on it.

    python -m phase_d.truncation_scan            # write reports/phase-d/d6/truncation_scan.{json,md}
    python -m phase_d.truncation_scan --check    # rebuild and diff to zero
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from . import records as rec

OUT_DIR = "reports/phase-d/d6"
JSON_PATH = f"{OUT_DIR}/truncation_scan.json"
MD_PATH = f"{OUT_DIR}/truncation_scan.md"
SCHEMA = "rerun/phase-d/truncation-scan/v1"
TAIL_CAP = 2000  # the harness stores the last 2000 characters of each stream per attempt
TAIL_FULL = TAIL_CAP - 5  # a tail this long means the stream received was at least as long: it could have been cut
SDK_DEFAULT_LIMIT_BYTES = 65535
RUNS = ("RUNS_CLEAN", "RUNS_AFTER_REPAIR")
# a last line that is an error, an exit or a kill: the end of the program's output is visible, so the tail does not look cut
TERMINAL = re.compile(r"(Error|Exception|Interrupt|Killed|SystemExit|Aborted|Segmentation|core dumped|exit status|error:|ERROR|FAILED|failed)", re.I)
WORD = re.compile(r"[A-Za-z]{3}")


def _last_line(text: str) -> str:
    lines = [line for line in re.split(r"[\r\n]", text) if line.strip()]
    return lines[-1] if lines else ""


def _tail_kind(text: str) -> str:
    """`error_end` (the last line is an error / exit / kill), `line_end` (ends at a newline), `mid_line` (ends inside a line: the cut-looking case)."""
    if TERMINAL.search(_last_line(text)):
        return "error_end"
    return "line_end" if text.endswith("\n") else "mid_line"


def _junk_errors(result: dict) -> list[dict]:
    found = []
    for field in ("last_error", "first_repo_error"):
        value = result.get(field)
        if isinstance(value, str) and value and not WORD.search(value):
            found.append({"field": field, "value": value})
    for i, entry in enumerate(result.get("error_chain") or []):
        text = entry.get("error", "") if isinstance(entry, dict) else entry
        if isinstance(text, str) and text and not WORD.search(text):
            found.append({"field": f"error_chain[{i}]", "value": text})
    return found


def scan_record(record: rec.Record) -> dict:
    result = record.data.get("result") or {}
    cut_looking, at_length, error_end = [], 0, 0
    for i, attempt in enumerate(result.get("attempts") or []):
        for stream in ("stdout_tail", "stderr_tail"):
            text = attempt.get(stream)
            if not isinstance(text, str) or len(text) < TAIL_FULL:
                continue
            at_length += 1
            kind = _tail_kind(text)
            if kind == "mid_line":
                cut_looking.append({"attempt": i, "stream": stream, "length": len(text), "last_line": _last_line(text)[-90:]})
            elif kind == "error_end":
                error_end += 1
    junk = _junk_errors(result)
    verdict = result.get("verdict")
    return {
        "record_id": record.record_id, "verdict": verdict, "taxonomy_code": result.get("taxonomy_code"), "reason_code": result.get("reason_code"),
        "verdict_rests_on_stream_content": verdict not in RUNS,
        "full_length_tails": at_length, "full_length_tails_ending_at_an_error": error_end,
        "cut_looking": cut_looking, "junk_error": junk,
        "suspect": bool(cut_looking or junk),
    }


def scan(source: rec.BlobSource | None = None) -> dict:
    rows = [scan_record(r) for r in rec.load_records(source)]
    suspects = [r for r in rows if r["suspect"]]
    return {
        "schema": SCHEMA,
        "rule": {"stored_tail_cap_chars": TAIL_CAP, "full_length_from_chars": TAIL_FULL, "sdk_default_limit_bytes": SDK_DEFAULT_LIMIT_BYTES,
                 "cut_looking": "a stored tail of full length that ends inside a line (not at a newline, not at an error / exit / kill line)",
                 "junk_error": "a recorded error text with no word in it",
                 "limits": "a heuristic: a tail cannot prove a cut; the one proof is the live probe of 2026-10-02 (harness-v1.4.2 entry 3)"},
        "records_scanned": len(rows),
        "suspects": len(suspects),
        "suspect_runs_verdicts": sum(1 for r in suspects if not r["verdict_rests_on_stream_content"]),
        "records": rows,
    }


def render_md(data: dict) -> str:
    lines = ["# D6: records that still rest on a stream the SDK may have cut (D-41)", "",
             "Generated by `python -m phase_d.truncation_scan` from the committed blobs; a heuristic, not a measurement (see below). No live call was made.", "",
             f"- Records scanned: {data['records_scanned']} (DERIVED: a count over the committed records).",
             f"- Suspect records: {data['suspects']} (DERIVED), of which with a RUNS_CLEAN or RUNS_AFTER_REPAIR verdict: {data['suspect_runs_verdicts']} (DERIVED).", "",
             "## Rule", "",
             f"The harness stores the last {data['rule']['stored_tail_cap_chars']} characters of each stream per attempt. The SDK cut each stream at {data['rule']['sdk_default_limit_bytes']} bytes "
             "and kept its start, so a cut stream's stored tail ends where the cut fell.",
             f"- **cut_looking**: {data['rule']['cut_looking']}.",
             f"- **junk_error**: {data['rule']['junk_error']}.",
             f"- Limit: {data['rule']['limits']}. A tail shorter than the stored length cannot have been cut. RUNS_* verdicts rest on the exit code and on liveness at the smoke limit, not on stream content.", "",
             "## Suspect records", "",
             "| Record | Verdict | What looks cut or wrong | Verdict rests on stream content |", "|---|---|---|---|"]
    for r in data["records"]:
        if not r["suspect"]:
            continue
        what = []
        for c in r["cut_looking"]:
            what.append(f"attempt {c['attempt']} `{c['stream']}` ends mid-line: `{c['last_line'].replace('|', '/')}`")
        for j in r["junk_error"]:
            what.append(f"`{j['field']}` is `{j['value']}`")
        verdict = f"{r['verdict']} {r['taxonomy_code']}" + (f" ({r['reason_code']})" if r["reason_code"] else "")
        lines.append(f"| `{r['record_id']}` | {verdict} | {'; '.join(what)} | {'yes' if r['verdict_rests_on_stream_content'] else 'no (exit code and liveness)'} |")
    return "\n".join(lines) + "\n"


def expected_files(source: rec.BlobSource | None = None) -> dict[str, bytes]:
    data = scan(source)
    return {JSON_PATH: (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8"), MD_PATH: render_md(data).encode("utf-8")}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    files = expected_files()
    if "--check" in argv:
        bad = [p for p, content in files.items() if not (rec.ROOT / p).is_file() or (rec.ROOT / p).read_bytes().replace(b"\r\n", b"\n") != content]
        for p in bad:
            print(f"DIFFERS {p}")
        print("truncation scan is identical to a rebuild" if not bad else f"truncation scan differs in {len(bad)} file(s)")
        return 1 if bad else 0
    for path, content in files.items():
        out = Path(rec.ROOT) / path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(content)
    print(f"wrote {len(files)} files under {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
