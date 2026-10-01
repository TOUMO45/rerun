"""Check the rendered dashboard HTML (the parsed page, not its source template).

Fails if:
  * a digit appears in visible text outside a quoted `<code>` string and outside a tagged number;
  * a tagged number lacks its tag, its visible tag chip, its full-precision value, or a link to a record
    (the link target must exist on the page and carry, or contain, a record id);
  * a displayed number is not its `data-value` (dollars: 4 decimals; everything else: the JSON value);
  * the page references any external resource, or contains a script or an animation.

    python -m phase_d.check_dashboard            # checks reports/phase-d/dashboard/index.html
"""

from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

from .dashboard import DASHBOARD
from .passports import TAGS
from .records import ROOT

VOID = {"meta", "br", "hr", "img", "input", "link", "source", "wbr", "area", "base", "col", "embed", "track"}
URL_ATTRS = ("href", "src", "action", "poster", "data", "srcset", "xlink:href", "formaction", "cite", "background")
EXTERNAL = re.compile(r"^\s*(?:[a-z][a-z0-9+.-]*:)?//|^\s*(?:https?|ftp|data|javascript):", re.I)
FORBIDDEN_TAGS = {"script", "iframe", "object", "embed", "link", "img", "video", "audio", "base", "form"}
MOTION = re.compile(r"@keyframes|animation\s*:|animation-|transition\s*:|transition-|@import|url\(", re.I)


class Node:
    def __init__(self, tag: str, attrs: dict[str, str], parent: "Node | None") -> None:
        self.tag, self.attrs, self.parent = tag, attrs, parent
        self.children: list["Node | str"] = []

    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def text(self) -> str:
        return "".join(c if isinstance(c, str) else c.text() for c in self.children)

    def walk(self):
        yield self
        for c in self.children:
            if isinstance(c, Node):
                yield from c.walk()

    def inside(self, tag: str) -> bool:
        node = self
        while node is not None:
            if node.tag == tag:
                return True
            node = node.parent
        return False


class _Tree(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {}, None)
        self.current = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: (v or "") for k, v in attrs}, self.current)
        self.current.children.append(node)
        if tag not in VOID:
            self.current = node

    def handle_endtag(self, tag):
        node = self.current
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self.current = node.parent

    def handle_data(self, data):
        self.current.children.append(data)


def parse(page: str) -> Node:
    tree = _Tree()
    tree.feed(page)
    tree.close()
    return tree.root


def shown_form(value, usd: bool) -> str:
    return f"${value:.4f}" if usd else json.dumps(value, ensure_ascii=False)


def numbers(root: Node) -> list[Node]:
    return [n for n in root.walk() if n.tag == "a" and n.classes() & {"n", "s"}]


def problems(page: str) -> list[str]:
    root = parse(page)
    found: list[str] = []
    ids = {n.attrs["id"]: n for n in root.walk() if "id" in n.attrs}

    # 1. no external resource, no script, no motion
    for n in root.walk():
        if n.tag in FORBIDDEN_TAGS:
            found.append(f"forbidden element <{n.tag}>")
        for attr in URL_ATTRS:
            if attr in n.attrs and EXTERNAL.search(n.attrs[attr]):
                found.append(f"external resource in {attr}: {n.attrs[attr][:80]!r}")
        if any(a.startswith("on") for a in n.attrs):
            found.append(f"event handler attribute on <{n.tag}>")
        if "style" in n.attrs and MOTION.search(n.attrs["style"]):
            found.append(f"motion or url() in a style attribute: {n.attrs['style'][:60]!r}")
        if n.tag == "style" and MOTION.search(n.text()):
            found.append("the stylesheet contains an animation, a transition, an @import or a url()")

    # 2. every tagged value: tag, visible chip, full value, record link
    for n in numbers(root):
        where = f"number {n.text()!r}"
        tag = n.attrs.get("data-tag")
        if tag not in TAGS:
            found.append(f"{where}: no tag")
            continue
        siblings = [c for c in n.parent.children if isinstance(c, Node)]
        after = siblings[siblings.index(n) + 1] if siblings.index(n) + 1 < len(siblings) else None
        if after is None or "tag" not in after.classes() or after.text() != tag:
            found.append(f"{where}: the tag {tag} is not visible beside it")
        href = n.attrs.get("href", "")
        target = ids.get(href[1:]) if href.startswith("#") else None
        if target is None:
            found.append(f"{where}: no link to a record on the page ({href!r})")
        elif not (n.attrs.get("data-record") or any("data-record" in t.attrs for t in target.walk())):
            found.append(f"{where}: its link target {href} carries no record id")
        if "data-value" not in n.attrs:
            found.append(f"{where}: no full-precision data-value")
            continue
        try:
            value = json.loads(n.attrs["data-value"])
        except ValueError:
            found.append(f"{where}: data-value is not JSON")
            continue
        if "n" in n.classes():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                found.append(f"{where}: data-value is not a number")
            elif n.text() not in (shown_form(value, False), shown_form(value, True)):
                found.append(f"{where}: the displayed text is not its data-value {n.attrs['data-value']}")
            if n.attrs.get("title", "").split(" ")[0] != n.attrs["data-value"]:
                found.append(f"{where}: the tooltip does not start with the full-precision value")
        elif n.text() != value:
            found.append(f"{where}: the displayed text is not its data-value")

    # 3. no digit in visible text outside <code> and outside a tagged number
    def visible(node: Node):
        for c in node.children:
            if isinstance(c, str):
                yield node, c
            elif c.tag not in ("style", "title", "code") and not (c.tag == "a" and "n" in c.classes()):
                yield from visible(c)

    for node, text in visible(root):
        if re.search(r"\d", text):
            found.append(f"digit in text outside a quote and outside a tagged number: {text.strip()[:60]!r} (in <{node.tag}>)")
    return found


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    file = Path(argv[0]) if argv else ROOT / DASHBOARD
    found = problems(file.read_text(encoding="utf-8"))
    for p in found[:50]:
        print(f"FAIL {p}")
    print(f"dashboard check FAILED: {len(found)} problem(s)" if found else "dashboard check passed: every number is tagged and linked; no external resource")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
