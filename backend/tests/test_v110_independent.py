"""harness-v1.10 pass, task 3: the independent cheat set (reports/v1.10/independent) is the set that was hashed and committed before anything was measured on it."""
from __future__ import annotations

import collections
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SET = ROOT / "reports" / "v1.10" / "independent"


def _hash_module():
    spec = importlib.util.spec_from_file_location("rerun_hash_set", SET / "hash_set.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_committed_set_hash_equals_a_fresh_hash_of_the_files():
    committed = json.loads((SET / "SET_HASH.json").read_text(encoding="utf-8"))
    assert _hash_module().build() == committed, "the independent set was edited after it was hashed: its patches, manifest and SET_HASH.json must not change"


def test_the_set_is_what_the_provenance_says_it_is():
    manifest = json.loads((SET / "manifest.json").read_text(encoding="utf-8"))
    counts = collections.Counter((r["kind"], r["family"]) for r in manifest)
    assert counts == {("cheat", "algo"): 57, ("cheat", "synth"): 37, ("cheat", "open"): 72, ("control", "control"): 42}
    assert {r["repo"] for r in manifest} == {"latent_ode", "SimplE", "FeatureScatter", "M-FAC", "patchSmoothing", "L2D", "MIR"}
    assert {p.stem for p in (SET / "patches").glob("*.patch")} == {r["id"] for r in manifest}
    assert (SET / "AUTHOR_PROMPT.txt").read_text(encoding="utf-8").startswith("You are an independent author of test data")


def test_the_author_was_not_given_the_checks():
    prompt = (SET / "AUTHOR_PROMPT.txt").read_text(encoding="utf-8")
    for word in ("tamper", "gate", "adjudicator", "behaviour.py", "planted", "corpus", "F1", "COMPUTATION_CHANGED"):
        assert word not in prompt.replace("Do not read, list, search or open anything outside that directory (in particular nothing under B:\\Desktop\\RERUN_Nvidia", ""), word
