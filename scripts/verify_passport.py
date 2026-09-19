#!/usr/bin/env python3
"""Standalone Reproduction Passport verifier (RERUN directive §6.3).

Recomputes a certificate's SHA-256 passport hash from its own contents and
confirms it matches the hash the certificate claims for itself — so a judge
or reviewer can check a downloaded certificate JSON wasn't altered after
the fact, without running RERUN itself and without trusting RERUN's own UI
to tell the truth about its own output.

Deliberately standalone: stdlib only (`hashlib`, `json`, `argparse`, `sys`),
no import of the backend package. The canonicalization algorithm below is a
direct, intentional duplicate of `backend/app/services/passport.py` — if
you change one, change both, and re-run
`pytest backend/tests/test_passport.py` to confirm they still agree.

Usage:
    python scripts/verify_passport.py path/to/certificate.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from typing import Any, Mapping

CANONICAL_FIELDS: tuple[str, ...] = (
    "repo_url",
    "commit_sha",
    "build_plan",
    "full_log",
    "diffs",
    "verdict",
    "timestamp",
)

PASSPORT_FIELD = "reproduction_passport_hash"


def build_canonical_bundle(certificate: Mapping[str, Any]) -> dict:
    missing = [f for f in CANONICAL_FIELDS if f not in certificate]
    if missing:
        raise ValueError(f"certificate is missing required field(s): {missing}")
    return {field: certificate[field] for field in CANONICAL_FIELDS}


def canonical_json(bundle: Mapping[str, Any]) -> str:
    return json.dumps(bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def compute_passport_hash(certificate: Mapping[str, Any]) -> str:
    bundle = build_canonical_bundle(certificate)
    return hashlib.sha256(canonical_json(bundle).encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("certificate_path", help="Path to a downloaded RERUN certificate JSON file")
    args = parser.parse_args(argv)

    try:
        with open(args.certificate_path, "r", encoding="utf-8") as f:
            certificate = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: could not read/parse '{args.certificate_path}': {exc}", file=sys.stderr)
        return 2

    claimed = certificate.get(PASSPORT_FIELD)
    if not claimed:
        print(f"ERROR: certificate has no '{PASSPORT_FIELD}' field to verify", file=sys.stderr)
        return 2

    try:
        recomputed = compute_passport_hash(certificate)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if recomputed == claimed:
        print("PASSPORT VERIFIED")
        print(f"  hash: {recomputed}")
        return 0

    print("PASSPORT MISMATCH — certificate does not match its claimed hash")
    print(f"  claimed:    {claimed}")
    print(f"  recomputed: {recomputed}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
