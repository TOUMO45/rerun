"""corpus-v1 amendment 1: the command-classification rules reproduce the
manual post-draw review entry by entry, and the committed amendment file is
exactly what the rules produce (sha256 pinned)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.batch.command_rules import COMMAND_NOT_A_RUN, PRIMARY, classify_command, matched_rules
from app.batch.corpus import load_corpus

CORPUS_DIR = Path(__file__).resolve().parents[1] / "app" / "batch" / "corpus_v1"

# METHODOLOGY.md, "corpus-v1 — draw result": the manual reading of the 20
# recorded commands, by entry id (position in corpus.yaml).
MANUAL = {
    1: PRIMARY, 2: PRIMARY, 3: COMMAND_NOT_A_RUN, 4: PRIMARY, 5: PRIMARY,
    6: COMMAND_NOT_A_RUN, 7: PRIMARY, 8: PRIMARY, 9: PRIMARY, 10: COMMAND_NOT_A_RUN,
    11: PRIMARY, 12: PRIMARY, 13: COMMAND_NOT_A_RUN, 14: COMMAND_NOT_A_RUN, 15: PRIMARY,
    16: PRIMARY, 17: COMMAND_NOT_A_RUN, 18: COMMAND_NOT_A_RUN, 19: COMMAND_NOT_A_RUN, 20: PRIMARY,
}
ENTRIES = load_corpus(CORPUS_DIR / "corpus.yaml")


def test_manual_split_is_12_primary_and_8_not_a_run():
    assert len(ENTRIES) == 20
    assert sum(v == PRIMARY for v in MANUAL.values()) == 12


@pytest.mark.parametrize("entry_id", sorted(MANUAL))
def test_rules_reproduce_the_manual_classification_entry_by_entry(entry_id):
    entry = ENTRIES[entry_id - 1]
    assert classify_command(entry.command) == MANUAL[entry_id], (entry_id, entry.name, entry.command, matched_rules(entry.command))


@pytest.mark.parametrize(
    "command, expected_rules",
    [
        ("python setup.py install", ["R1_INSTALL"]),
        ("bash download.sh", ["R2_DOWNLOAD"]),
        ("python process.py", ["R3_PREPROCESS"]),
        ("python preprocess.py --only-source", ["R3_PREPROCESS"]),
        ("bash ./tools/pre_run.sh", ["R4_SETUP_SCRIPT"]),
        ("python train.py --data $DATA", ["R5_PLACEHOLDER"]),
        ("python train.py --data ${DATA_DIR}/x", ["R5_PLACEHOLDER"]),
        ("python -m nfe.train --model [ode|flow]", ["R5_PLACEHOLDER"]),
        ("python -m alf.bin.train --conf=CONF_FILE", ["R5_PLACEHOLDER"]),
        ("python train.py --out LOG_DIR", ["R5_PLACEHOLDER"]),
    ],
)
def test_each_rule_fires_on_its_own_case(command, expected_rules):
    assert matched_rules(command) == expected_rules


@pytest.mark.parametrize(
    "command",
    [
        # TTL2-style values: ALL-CAPS tokens without an underscore are real values.
        "python run_experiment.py --syntax=TTL2 --network=PrediNet",
        "python ib_vgg_train.py --cfg D4 --gpu 0",
        "python main.py --dataset CIFAR10 --arch ResNet",
        "python train.py --mode RGB --norm L2",
        # A leading environment assignment is not an argument.
        "CUDA_VISIBLE_DEVICES=0 python run.py doom tmaze --num_steps=500000",
        # Stems that merely contain rule words elsewhere.
        "python train_downstream.py",
        "python main_process_free.py",
    ],
)
def test_ttl2_style_tokens_and_ordinary_runs_are_not_classified_away(command):
    assert matched_rules(command) == [], matched_rules(command)


def test_committed_amendment_matches_the_rules_and_its_pinned_sha256():
    amendment_path = CORPUS_DIR / "amendment-1.json"
    raw = amendment_path.read_bytes()
    digest, name = (CORPUS_DIR / "amendment-1.sha256").read_text(encoding="utf-8").split()
    assert name == "amendment-1.json"
    assert hashlib.sha256(raw).hexdigest() == digest
    assert b"\r\n" not in raw
    amendment = json.loads(raw)
    assert amendment["corpus_hash"] == (CORPUS_DIR / "corpus_hash.txt").read_text(encoding="utf-8").strip()
    assert amendment["primary_endpoint"]["ids"] == [i for i, c in sorted(MANUAL.items()) if c == PRIMARY]
    assert amendment["command_not_a_run"]["ids"] == [i for i, c in sorted(MANUAL.items()) if c == COMMAND_NOT_A_RUN]
    for row in amendment["entries"]:
        entry = ENTRIES[row["id"] - 1]
        assert (row["name"], row["command"]) == (entry.name, entry.command)
        assert row["rules_matched"] == matched_rules(entry.command)
