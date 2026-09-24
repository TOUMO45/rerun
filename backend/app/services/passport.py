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

# Bundle versions. A certificate without `bundle_version` is v1 and keeps
# verifying exactly as before; newer versions add fields to the hash.
#   v2 (2026-09-24): + bundle_version, baseline (the naive install's own
#       result), recovery (baseline failed -> final run completed).
CANONICAL_FIELDS_BY_VERSION: dict[int, tuple[str, ...]] = {
    1: CANONICAL_FIELDS,
    2: CANONICAL_FIELDS + ("bundle_version", "baseline", "recovery"),
    # v3 (2026-09-24): + tree_integrity (the uploaded tree was verified to be
    #     the committed tree, with its git tree sha) and corpus_hash (the frozen
    #     corpus the run belongs to; null for ad-hoc runs).
    3: CANONICAL_FIELDS + ("bundle_version", "baseline", "recovery", "tree_integrity", "corpus_hash"),
}
CURRENT_BUNDLE_VERSION = 3

PASSPORT_FIELD = "reproduction_passport_hash"


class MissingFieldError(ValueError):
    pass


def canonical_fields_for(certificate: Mapping[str, Any]) -> tuple[str, ...]:
    version = certificate.get("bundle_version", 1)
    if version not in CANONICAL_FIELDS_BY_VERSION:
        raise MissingFieldError(f"unknown certificate bundle_version {version!r}")
    return CANONICAL_FIELDS_BY_VERSION[version]


def build_canonical_bundle(certificate: Mapping[str, Any]) -> dict:
    fields = canonical_fields_for(certificate)
    missing = [f for f in fields if f not in certificate]
    if missing:
        raise MissingFieldError(f"certificate is missing required field(s): {missing}")
    return {field: certificate[field] for field in fields}


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
