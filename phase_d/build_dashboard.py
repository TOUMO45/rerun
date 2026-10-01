"""Build (or check) the static dashboard from the REPLAY JSON. One command, from a clean checkout:

    python -m phase_d.build_dashboard            # writes reports/phase-d/dashboard/index.html
    python -m phase_d.build_dashboard --check    # rebuild and diff against the stored page; exit 1 on any difference
    python -m phase_d.build_dashboard --out DIR  # write index.html into DIR instead

The build stops if `python -m phase_d.build_replay --check` fails, and if the rendered page fails
`phase_d.check_dashboard` (an untagged or unlinked number, or an external resource).
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import build_replay, check_dashboard
from .dashboard import DASHBOARD, INPUTS, build_html
from .records import ROOT


def _lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def render(root: Path = ROOT) -> tuple[bytes, list[str]]:
    """(page, problems). The page is built only from the stored REPLAY JSON, after that JSON is verified."""
    problems = [f"replay: {p}" for p in build_replay.check(root)]
    if problems:
        return b"", problems
    page = build_html({rel: _lf((root / rel).read_bytes()) for rel in INPUTS})
    return page, [f"page: {p}" for p in check_dashboard.problems(page.decode("utf-8"))]


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    argv = sys.argv[1:] if argv is None else argv
    page, problems = render(root)
    target = (Path(argv[argv.index("--out") + 1]) / "index.html") if "--out" in argv else root / DASHBOARD
    if not problems and "--check" in argv:
        stored = root / DASHBOARD
        if not stored.is_file() or _lf(stored.read_bytes()) != page:
            problems.append(f"differs from the rebuild: {DASHBOARD}")
    for p in problems[:50]:
        print(f"FAIL {p}")
    if problems:
        print(f"dashboard not built: {len(problems)} problem(s)")
        return 1
    if "--check" in argv:
        print("dashboard verified: the stored page is identical to a rebuild")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(page)
    print(f"wrote {target.relative_to(root).as_posix() if target.is_relative_to(root) else target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
