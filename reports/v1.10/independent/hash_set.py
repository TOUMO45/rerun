"""harness-v1.10 pass, task 3: the hash of the independent cheat set.

    backend/.venv/Scripts/python.exe reports/v1.10/independent/hash_set.py [--write]

SET_HASH.txt holds the sha-256 of every patch file, of the manifest, and one set hash = sha-256 of the sorted "<id> <sha256 of the patch bytes>" lines followed by the manifest's hash.
The set is committed and pushed before anything is measured on it; the test in backend/tests/test_v110_independent.py recomputes this and fails on any difference.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def build() -> dict:
    manifest_bytes = (HERE / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    patches = {}
    for row in sorted(manifest, key=lambda r: r["id"]):
        patches[row["id"]] = hashlib.sha256((HERE / "patches" / f"{row['id']}.patch").read_bytes()).hexdigest()
    lines = [f"{pid} {digest}" for pid, digest in sorted(patches.items())]
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    set_hash = hashlib.sha256(("\n".join(lines) + "\n" + manifest_hash + "\n").encode("utf-8")).hexdigest()
    return {"patches": len(patches), "manifest_sha256": manifest_hash, "set_sha256": set_hash, "per_patch_sha256": patches}


def main() -> int:
    doc = build()
    target = HERE / "SET_HASH.json"
    if "--write" in sys.argv:
        target.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
        print("wrote", target)
    print(f"{doc['patches']} patches; manifest {doc['manifest_sha256']}; set {doc['set_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
