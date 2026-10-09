"""The README's result section and the Devpost texts, generated from reports/v1.9/figures.json (owner, 2026-10-09, task 4).

    python reports/texts/render.py           # write README.md (between its markers), docs/submission/description.md, docs/submission/devpost_answers.md
    python reports/texts/render.py --check   # fail if any of them is not what the templates and figures.json give

A template is Markdown with placeholders:

    {{name}}          the figure's value and its tag: `3 [DERIVED]`; a name ending in _pct gives `28% [DERIVED]`, in _usd `$3.73 [API-REPORTED]`
    {{table:name}}    a benchmark table of figures.json "tables" (benchmark/score.py --all), one Markdown row per line, each row tagged

No number is typed into a template: the guard in backend/tests/test_texts_render.py fails on a digit outside a placeholder (code spans, links, defect ids, harness
versions and the judging scales aside). The Batch Lab reads the same figures.json (GET /batch/preregistered)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = Path(__file__).with_name("templates")
FIGURES = ROOT / "reports" / "v1.9" / "figures.json"
START, END = "<!-- generated from reports/v1.9/figures.json by reports/texts/render.py: edit reports/texts/templates/README_result.md, not this section -->", "<!-- end of the generated section -->"
# (template, target, how): "section" replaces README.md between START and END; "file" writes the whole file
OUTPUTS = (("README_result.md", "README.md", "section"),
           ("description.md", "docs/submission/description.md", "file"),
           ("devpost_answers.md", "docs/submission/devpost_answers.md", "file"))
PLACEHOLDER = re.compile(r"\{\{\s*(table:)?([A-Za-z0-9_.\-]+)\s*\}\}")

sys.path.insert(0, str(ROOT))
from benchmark.build import PLANTED_FAMILY_NAMES  # noqa: E402


def _value(name: str, fig: dict) -> str:
    v, tag = fig["value"], fig["tag"]
    if name.endswith("_pct"):
        return f"{v}% [{tag}]"
    if name.endswith("_usd"):
        return f"${v} [{tag}]" if isinstance(v, int) else f"${v:.2f} [{tag}]"
    return f"{v} [{tag}]"


def _table(name: str, tables: dict) -> str:
    t = tables[name]["table"]
    flagged = any(c["flagged"] for c in [*t["families"].values(), t["all_cheats"], t["all_controls"]])
    head = "| | n | refused | adopted" + (" clean | adopted with REVIEW_REQUIRED" if flagged else "") + " | refused by layer |"
    sep = "|---|---|---|---" + ("|---" if flagged else "") + "|---|"

    def row(label: str, c: dict) -> str:
        layers = ", ".join(f"{k} {v}" for k, v in c["refused_by_layer"].items()) or "–"
        cells = [label + " [DERIVED]", str(c["n"]), str(c["refused"]), str(c["adopted"])] + ([str(c["flagged"])] if flagged else []) + [layers]
        return "| " + " | ".join(cells) + " |"

    lines = [head, sep] + [row(f"cheats {fam}" + (f" {PLANTED_FAMILY_NAMES[fam]}" if fam in PLANTED_FAMILY_NAMES else ""), c) for fam, c in t["families"].items()]
    lines += [row("**cheats, all**", t["all_cheats"]), row("cheats aimed at failing repositories", t["cheats_aimed_at_failing_repositories"]),
              row("honest controls (refused = false refusals)", t["all_controls"])]
    return "\n".join(lines)


def render(template: str, doc: dict) -> str:
    figs, tables = doc["figures"], doc.get("tables") or {}

    def sub(m: re.Match) -> str:
        is_table, name = bool(m.group(1)), m.group(2)
        if is_table:
            if name not in tables:
                raise SystemExit(f"unknown table {name!r}")
            return _table(name, tables)
        if name not in figs:
            raise SystemExit(f"unknown figure {name!r}")
        return _value(name, figs[name])

    return PLACEHOLDER.sub(sub, template)


def outputs() -> dict[Path, str]:
    doc = json.loads(FIGURES.read_text(encoding="utf-8"))
    out: dict[Path, str] = {}
    for tpl, target, how in OUTPUTS:
        text = render((TEMPLATES / tpl).read_text(encoding="utf-8"), doc)
        path = ROOT / target
        if how == "file":
            out[path] = text
            continue
        current = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        if START not in current or END not in current:
            raise SystemExit(f"{target}: the generated section's markers are missing")
        before, rest = current.split(START, 1)
        _, after = rest.split(END, 1)
        out[path] = before + START + "\n" + text.rstrip("\n") + "\n" + END + after
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    files = outputs()
    if args.check:
        stale = [p.relative_to(ROOT).as_posix() for p, text in files.items() if p.read_text(encoding="utf-8").replace("\r\n", "\n") != text]
        if stale:
            print(f"not what the templates and figures.json give: {stale}; run python reports/texts/render.py", file=sys.stderr)
            return 1
        print(f"{len(files)} texts match figures.json")
        return 0
    for p, text in files.items():
        p.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {p.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
