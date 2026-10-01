"""v1.4.0 Step 0: the budget note is rebuilt from committed record blobs (offline) and matches the committed file."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phase_d import budget_v140, records  # noqa: E402

V133, V134 = "harness-v1.3.3", "harness-v1.3.4"


def _entries() -> dict[tuple[str, str], budget_v140.Entry]:
    return {
        (r.harness_tag, r.entry): budget_v140.Entry(r, budget_v140.parse_ops(r))
        for r in records.load_records()
        if r.harness_tag in budget_v140.GATE_TAGS
    }


def test_committed_note_matches_the_records():
    committed = (ROOT / budget_v140.OUT).read_text(encoding="utf-8").replace("\r\n", "\n")
    assert committed == budget_v140.build()


def test_operation_costs_add_up_to_the_recorded_sandbox_spend():
    for key, entry in _entries().items():
        derived = sum(op.usd for op in entry.ops if op.usd is not None)
        # event lines are printed to 4 decimals, so each operation is within half a unit of the last place
        assert abs(derived - entry.guard["sandbox_spent_usd"]) <= 0.00005 * len(entry.ops) + 1e-9, key


def test_torch_install_counts():
    entries = _entries()
    started = {k: sum(1 for op in e.ops if op.torch) for k, e in entries.items()}
    assert started == {
        (V133, "03"): 4, (V133, "07"): 0, (V133, "08"): 3, (V133, "11"): 2,
        (V134, "03"): 3, (V134, "07"): 0, (V134, "08"): 2, (V134, "11"): 4,
    }
    assert entries[(V134, "08")].ops[1].install == "killed"
    assert entries[(V134, "11")].ops[3].outcome == "killed" and entries[(V134, "11")].ops[3].install == "completed"
    assert entries[(V133, "08")].ops[2].outcome == "void" and entries[(V133, "08")].ops[2].usd is None


def test_every_dollar_figure_in_a_sentence_carries_a_tag():
    text = budget_v140.build()
    for line in text.splitlines():
        if line.startswith("|") or "$" not in line:
            continue  # table cells are tagged by the sentence under the table
        assert re.search(r"API-REPORTED|DERIVED|ESTIMATED", line), line
