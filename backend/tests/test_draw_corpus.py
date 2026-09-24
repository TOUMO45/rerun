"""The corpus-v1 draw's deterministic helpers (scripts/draw_corpus.py)."""

from __future__ import annotations

import importlib.util
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("draw_corpus", ROOT / "scripts" / "draw_corpus.py")
draw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(draw)

README = """# Paper code
Install with `pip install -r requirements.txt`.

```bash
$ python train.py --config <your_config>.yaml
CUDA_VISIBLE_DEVICES=0 python3 main.py --epochs 10 \\
    --lr 0.1
python -m tools.evaluate --ckpt ckpt.pt
bash scripts/run.sh
```
Run `python demo.py`.
"""


def test_commands_are_found_in_reading_order_with_continuations_joined():
    found = draw._commands_in(README)
    assert [c for _, c in found] == [
        "python train.py --config <your_config>.yaml",
        "CUDA_VISIBLE_DEVICES=0 python3 main.py --epochs 10 --lr 0.1",
        "python -m tools.evaluate --ckpt ckpt.pt",
        "bash scripts/run.sh",
    ]


def test_placeholders_are_detected():
    assert draw._PLACEHOLDER_RE.search("python train.py --config <your_config>.yaml")
    assert draw._PLACEHOLDER_RE.search("python run.py --data /path/to/data")
    assert draw._PLACEHOLDER_RE.search("python run.py --key YOUR_KEY")
    assert not draw._PLACEHOLDER_RE.search("CUDA_VISIBLE_DEVICES=0 python3 main.py --epochs 10 --lr 0.1")


def test_target_paths():
    assert draw._target_path(draw._CMD_RE.match("python3 ./src/main.py --x 1")) == "src/main.py"
    assert draw._target_path(draw._CMD_RE.match("python -m tools.evaluate --ckpt a")) == "tools/evaluate"
    assert draw._CMD_RE.match("pip install -r requirements.txt") is None
    assert draw._CMD_RE.match("python setup.py install")  # a real script; E5 accepts it only if it exists


def test_prereg_matches_the_script_and_the_population():
    pre = json.loads((ROOT / "backend/app/batch/corpus_v1/prereg.json").read_text(encoding="utf-8"))
    assert pre["eligibility"]["command_regex"] == draw._CMD_RE.pattern
    assert pre["eligibility"]["placeholder_regex"] == draw._PLACEHOLDER_RE.pattern
    assert draw.sha256_file(ROOT / "backend/app/batch/corpus_v1/population.csv") == pre["population_sha256"]
    assert pre["seed"] == 20260924 and pre["target_eligible"] == 20


def test_draw_order_is_reproducible_from_the_seed():
    order_a = list(range(5485)); random.Random(20260924).shuffle(order_a)
    order_b = list(range(5485)); random.Random(20260924).shuffle(order_b)
    assert order_a == order_b and order_a[:3] != [0, 1, 2]
