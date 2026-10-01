"""Tag check: fail if any number in a passport lacks exactly one of MEASURED | ESTIMATED | DERIVED.

A JSON number is allowed only as the `value` of an object whose `tag` is one of the three. A DERIVED value must
quote its source line with a record id; a null value must give a reason. Numbers inside quoted text (error
messages, event lines, annotation sentences) are strings and are not checked here.

    python -m phase_d.check_tags            # every file under reports/phase-d/passports
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .passports import DERIVED, PASSPORT_DIR, TAGS
from .records import ROOT


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _derived_sources(source: Any) -> list:
    return source if isinstance(source, list) else [source]


def violations(obj: Any, path: str = "$") -> list[str]:
    found: list[str] = []
    if _is_number(obj):
        found.append(f"{path}: bare number {obj!r} without a tag")
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            found += violations(item, f"{path}[{i}]")
    elif isinstance(obj, dict):
        if "tag" in obj:
            if obj["tag"] not in TAGS:
                found.append(f"{path}: unknown tag {obj['tag']!r}")
            if "value" not in obj:
                found.append(f"{path}: a tag without a value")
            if obj["tag"] == DERIVED:
                sources = _derived_sources(obj.get("source"))
                if not sources or not all(isinstance(s, dict) and s.get("record_id") and s.get("line") for s in sources):
                    found.append(f"{path}: DERIVED without a quoted source line and record id")
        elif "value" in obj:
            if _is_number(obj["value"]):
                found.append(f"{path}.value: number {obj['value']!r} without a tag")
            elif obj["value"] is None and not obj.get("reason"):
                found.append(f"{path}: null value without a reason")
        for key, item in obj.items():
            if key == "value" and "tag" in obj and (_is_number(item) or item is None or isinstance(item, (str, bool))):
                continue
            found += violations(item, f"{path}.{key}")
    return found


def check_files(root: Path = ROOT) -> dict[str, list[str]]:
    bad: dict[str, list[str]] = {}
    files = sorted((root / PASSPORT_DIR).rglob("*.json"))
    if not files:
        bad[PASSPORT_DIR] = ["no passport files found"]
    for file in files:
        found = violations(json.loads(file.read_text(encoding="utf-8")))
        if found:
            bad[file.relative_to(root).as_posix()] = found
    return bad


def main() -> int:
    bad = check_files()
    for file, found in bad.items():
        for line in found:
            print(f"UNTAGGED {file} {line}")
    if bad:
        print(f"tag check FAILED: {sum(len(v) for v in bad.values())} violation(s) in {len(bad)} file(s)")
        return 1
    print("tag check passed: every number carries MEASURED, ESTIMATED or DERIVED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
