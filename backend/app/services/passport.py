"""Reproduction Passport signing (RERUN directive §6.3).

PURE. No network, no model call. On verdict finalization, the orchestrator
builds a canonical bundle (build plan + full log + every applied/rejected
diff + verdict + timestamp) and this module signs it with a SHA-256 hash,
so a judge or reviewer can verify a downloaded certificate wasn't altered
after the fact — independent of trusting RERUN's own UI.

`scripts/verify_passport.py` intentionally re-implements the same
canonicalization/hash logic standalone (stdlib only, no import of this
module or the backend package) so the verification story doesn't itself
require trusting that RERUN's own code is what actually ran.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

# The exact fields the hash is computed over, and their order in the
# canonical bundle. Both this module and scripts/verify_passport.py must
# agree on this list byte-for-byte.
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


class MissingFieldError(ValueError):
    pass


def build_canonical_bundle(certificate: Mapping[str, Any]) -> dict:
    missing = [f for f in CANONICAL_FIELDS if f not in certificate]
    if missing:
        raise MissingFieldError(f"certificate is missing required field(s): {missing}")
    return {field: certificate[field] for field in CANONICAL_FIELDS}


def canonical_json(bundle: Mapping[str, Any]) -> str:
    """Deterministic JSON serialization: sorted keys, no extra whitespace,
    ASCII-only, so the same logical bundle always hashes identically
    regardless of dict insertion order or platform."""
    return json.dumps(bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def compute_passport_hash(certificate: Mapping[str, Any]) -> str:
    bundle = build_canonical_bundle(certificate)
    return hashlib.sha256(canonical_json(bundle).encode("utf-8")).hexdigest()


def sign_certificate(certificate: Mapping[str, Any]) -> dict:
    """Return a new certificate dict with `reproduction_passport_hash` set."""
    passport_hash = compute_passport_hash(certificate)
    return {**certificate, PASSPORT_FIELD: passport_hash}


def verify_certificate(certificate: Mapping[str, Any]) -> bool:
    """True iff the certificate's stored hash matches a fresh recomputation
    over its own canonical fields."""
    claimed = certificate.get(PASSPORT_FIELD)
    if not claimed:
        return False
    try:
        return compute_passport_hash(certificate) == claimed
    except MissingFieldError:
        return False
