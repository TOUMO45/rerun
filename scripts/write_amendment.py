"""Write corpus-v1 amendment 1 (pre-results analysis amendment) and its sha256.

Applies backend/app/batch/command_rules.py to every corpus-v1 command, checks
the result entry by entry against the manual post-draw review recorded in
METHODOLOGY.md (it refuses to write if they differ), and writes:

    backend/app/batch/corpus_v1/amendment-1.json    (LF, sorted keys)
    backend/app/batch/corpus_v1/amendment-1.sha256

Only command strings are read — no run record, no batch result.

Usage (repo root):  backend/.venv/Scripts/python.exe scripts/write_amendment.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.batch import command_rules  # noqa: E402
from app.batch.corpus import load_corpus  # noqa: E402

CORPUS_DIR = ROOT / "backend" / "app" / "batch" / "corpus_v1"
AMENDMENT = CORPUS_DIR / "amendment-1.json"
AMENDMENT_SHA = CORPUS_DIR / "amendment-1.sha256"

# The manual post-draw review (METHODOLOGY.md, "corpus-v1 — draw result"),
# by corpus-v1 entry id (position in corpus.yaml, 1-based).
MANUAL_PRIMARY_IDS = (1, 2, 4, 5, 7, 8, 9, 11, 12, 15, 16, 20)
MANUAL_NOT_A_RUN = {
    3: "preprocessing (preprocess.py) with an unfilled $TEXT",
    6: "an install step (python setup.py install)",
    10: "unfilled placeholders CONF_FILE / LOG_DIR",
    13: "a data download (download.sh)",
    14: "preprocessing (process.py)",
    17: "an unfilled [ellipse|sawtooth|…] choice list",
    18: "preprocessing (data/basketball/read_raw.py) with an unfilled $RAW_DATA_DIR",
    19: "a setup script (tools/pre_run.sh)",
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> dict:
    corpus_yaml = CORPUS_DIR / "corpus.yaml"
    entries = load_corpus(corpus_yaml)
    corpus_hash = (CORPUS_DIR / "corpus_hash.txt").read_text(encoding="utf-8").strip()
    rows = []
    for entry_id, entry in enumerate(entries, start=1):
        rules = command_rules.matched_rules(entry.command)
        category = command_rules.COMMAND_NOT_A_RUN if rules else command_rules.PRIMARY
        manual = command_rules.PRIMARY if entry_id in MANUAL_PRIMARY_IDS else command_rules.COMMAND_NOT_A_RUN
        if category != manual:
            raise SystemExit(f"entry #{entry_id} {entry.name}: rules say {category}, manual review says {manual} — not writing")
        rows.append({"id": entry_id, "name": entry.name, "command": entry.command, "category": category, "rules_matched": rules})
    return {
        "amendment": "corpus-v1/amendment-1",
        "kind": "pre-results analysis amendment",
        "registered": "2026-09-28",
        "corpus_version": "corpus-v1",
        "corpus_hash": corpus_hash,
        "corpus_yaml_sha256": sha256_file(corpus_yaml),
        "prereg_sha256": sha256_file(CORPUS_DIR / "prereg.json"),
        "sampling_unchanged": "The corpus is run exactly as drawn: all 20 entries, their pinned commits and recorded commands, "
        "unchanged. This amendment changes only how results are analysed and reported.",
        "no_outcomes_observed": "At classification time no corpus-v1 entry had been executed by RERUN (no baseline, no repair, "
        "no verdict for any of the 20). The classification reads only the command strings in corpus.yaml. The only live runs "
        "since the draw are development runs of TTPT (dev_run: true), which is not a corpus-v1 entry.",
        "primary_endpoint": {
            "definition": "The entries whose recorded command is a genuine run of the paper's code (no rule below matches). "
            "The recovery rate and every headline number are computed over these entries only.",
            "ids": [r["id"] for r in rows if r["category"] == command_rules.PRIMARY],
        },
        "command_not_a_run": {
            "definition": "Entries whose recorded command matches at least one rule below. They are executed exactly like the "
            "primary entries (same harness, same caps) and reported separately as category COMMAND_NOT_A_RUN; they are never "
            "counted in the recovery rate or any headline number.",
            "ids": [r["id"] for r in rows if r["category"] == command_rules.COMMAND_NOT_A_RUN],
            "manual_review_reason": {str(k): v for k, v in MANUAL_NOT_A_RUN.items()},
            "note": "#18 is preprocessing in the manual review; the rules catch it through R5 ($RAW_DATA_DIR) only — "
            "R3 matches stems starting with 'process'/'preprocess', not 'read_raw'.",
        },
        "classification_rules": {
            "applied_by": "backend/app/batch/command_rules.py (matched_rules / classify_command), identically to every entry",
            "decision": "COMMAND_NOT_A_RUN if ANY rule matches, else PRIMARY",
            "target": "the first `python|python3|bash|sh <path>.py|.sh` or `python -m <module>` after optional leading "
            "VAR=value assignments; stem = script file name without extension, or the module's last dotted component; "
            "args = the shell-split words after the target",
            "stem_regex_flags": "IGNORECASE",
            "arg_regex_flags": "none (case-sensitive)",
            "rules": command_rules.RULES,
        },
        "reporting": {
            "failed_as_published": "primary entries whose baseline (declared install + recorded command, before RERUN changes "
            "anything) FAILS",
            "recovered": "primary entries with baseline FAILS and final verdict RUNS_AFTER_REPAIR (RUNS_AFTER_REPAIR)",
            "blocked": "primary entries with final verdict BLOCKED, broken down by taxonomy code (reason)",
            "invalid_harness": "primary entries ending INVALID_HARNESS (RERUN's fault) — reported, excluded from the rate",
            "repair_mode_split": "deterministic vs model_assisted, over recovered primary entries",
            "headline": "PRIMARY: <recovered>/<failed-as-published> of 12",
        },
        "entries": rows,
    }


def main() -> int:
    amendment = build()
    AMENDMENT.write_text(json.dumps(amendment, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    digest = sha256_file(AMENDMENT)
    AMENDMENT_SHA.write_text(f"{digest}  amendment-1.json\n", encoding="utf-8", newline="\n")
    print(f"wrote {AMENDMENT.relative_to(ROOT)}; sha256 {digest}")
    print(f"primary ids: {amendment['primary_endpoint']['ids']}")
    print(f"COMMAND_NOT_A_RUN ids: {amendment['command_not_a_run']['ids']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
