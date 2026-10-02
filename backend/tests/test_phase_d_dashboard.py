"""Phase D3: the static dashboard, built from the REPLAY JSON only (checks parse the rendered HTML, not its source)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phase_d import build_dashboard, check_dashboard, dashboard, replay  # noqa: E402
from phase_d.check_dashboard import Node, numbers, parse, problems  # noqa: E402

V132, V133, V134, V140, V141, V142, V143 = replay.VERSIONS
NUMBER = re.compile(r"\d+(?:\.\d+)?(?:e-?\d+)?")
# the owner's confirmed wording (METHODOLOGY, "Owner's answers to the v1.4.2 report"), recomputed over every gate entry-run: the counts come from the records
HEADLINE_OWNER = ("2 of 24 gate entry-runs reached a RUNS_* verdict and no gate passed; one is a measurement artefact (v1.3.3 entry 11, smoke limit), "
                  "the other a 60 s smoke-criterion pass after model-proposed environment changes were adopted (v1.4.2 entry 7).")
HEADLINE = ("Over every gate entry-run of the exploratory versions, 2 of 24 ended RUNS_CLEAN or RUNS_AFTER_REPAIR, and no gate passed. "
            "One of them (v1.3.3 entry 11) was a smoke-limit artefact reached by the time machine alone, with no model attempt in its record. "
            "The other (v1.4.2 entry 7) is a smoke-criterion pass: the command ran for the smoke limit without failing, after model-proposed "
            "environment changes were adopted (1 such record); it did not run to completion and no result was reproduced. "
            "A recorded model repair attempt exists in 17 of 24.")
BROWSERS = (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe", "/usr/bin/chromium", "/usr/bin/google-chrome")


def _lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


@pytest.fixture(scope="module")
def inputs() -> dict[str, bytes]:
    return {rel: _lf((ROOT / rel).read_bytes()) for rel in dashboard.INPUTS}


@pytest.fixture(scope="module")
def page(inputs) -> str:
    return dashboard.build_html(inputs).decode("utf-8")


@pytest.fixture(scope="module")
def root(page) -> Node:
    return parse(page)


def _all(node: Node, tag: str | None = None, cls: str | None = None) -> list[Node]:
    return [n for n in node.walk() if (tag is None or n.tag == tag) and (cls is None or cls in n.classes())]


def _by_id(root: Node, ident: str) -> Node:
    return next(n for n in root.walk() if n.attrs.get("id") == ident)


def _text_without_tags(node: Node) -> str:
    parts = []
    for c in node.children:
        if isinstance(c, str):
            parts.append(c)
        elif "tag" not in c.classes():
            parts.append(_text_without_tags(c))
    return "".join(parts)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).replace("( ", "(").replace(" )", ")").replace(" ;", ";").strip()


def _tagged(obj, out=None) -> set[tuple[str, str]]:
    out = set() if out is None else out
    if isinstance(obj, dict):
        if "tag" in obj and "value" in obj:
            out.add((json.dumps(obj["value"], ensure_ascii=False), obj["tag"]))
        for v in obj.values():
            _tagged(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _tagged(v, out)
    return out


# ---------------------------------------------------------------- build

def test_the_build_is_byte_identical_across_two_builds_and_equals_the_stored_page(inputs, page):
    assert dashboard.build_html(inputs) == dashboard.build_html(inputs) == page.encode("utf-8")
    assert _lf((ROOT / dashboard.DASHBOARD).read_bytes()) == page.encode("utf-8")


def test_one_command_builds_the_page_with_the_standard_library_only(tmp_path, page):
    """`python -S` has no site-packages: the build needs nothing but Python and git."""
    for out in (tmp_path / "a", tmp_path / "b"):
        run = subprocess.run([sys.executable, "-S", "-m", "phase_d.build_dashboard", "--out", str(out)], cwd=ROOT, capture_output=True, text=True)
        assert run.returncode == 0, run.stdout + run.stderr
    assert (tmp_path / "a" / "index.html").read_bytes() == (tmp_path / "b" / "index.html").read_bytes() == page.encode("utf-8")


def test_the_page_builds_from_a_clean_checkout(tmp_path):
    def git(*args, cwd=ROOT):
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)

    if git("cat-file", "-e", "HEAD:phase_d/build_dashboard.py").returncode or git("status", "--porcelain", "--", "phase_d", "reports/phase-d").stdout.strip():
        pytest.skip("the dashboard builder is not committed yet, or the worktree differs from HEAD: a clone would not test this tree")
    clone = tmp_path / "clone"
    assert git("clone", "-q", "--no-hardlinks", str(ROOT), str(clone)).returncode == 0
    check = subprocess.run([sys.executable, "-S", "-m", "phase_d.build_dashboard", "--check"], cwd=clone, capture_output=True, text=True)
    assert check.returncode == 0, check.stdout + check.stderr
    build = subprocess.run([sys.executable, "-S", "-m", "phase_d.build_dashboard"], cwd=clone, capture_output=True, text=True)
    assert build.returncode == 0, build.stdout + build.stderr
    assert _lf((clone / dashboard.DASHBOARD).read_bytes()) == _lf((ROOT / dashboard.DASHBOARD).read_bytes())


def test_the_build_fails_if_the_replay_check_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(build_dashboard.build_replay, "check", lambda root=ROOT, source=None: ["differs from the rebuild: x"])
    assert build_dashboard.main(["--out", str(tmp_path)]) == 1 and not (tmp_path / "index.html").exists()


def test_the_build_fails_if_the_rendered_page_fails_its_check(tmp_path, monkeypatch):
    monkeypatch.setattr(build_dashboard.build_replay, "check", lambda root=ROOT, source=None: [])
    monkeypatch.setattr(build_dashboard.check_dashboard, "problems", lambda page: ["number '0.28': no tag"])
    assert build_dashboard.main(["--out", str(tmp_path)]) == 1 and not (tmp_path / "index.html").exists()


def test_the_page_is_built_from_the_replay_json_only():
    """The renderer imports nothing that reads records, passports or report text: its only input is the REPLAY JSON it is handed."""
    import ast

    tree = ast.parse((ROOT / "phase_d" / "dashboard.py").read_text(encoding="utf-8"))
    imported = {(n.module, n.level) for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {(a.name, 0) for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert imported == {("__future__", 0), ("html", 0), ("json", 0), ("re", 0), ("typing", 0), ("replay", 1)}
    calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "open" not in calls
    assert set(dashboard.INPUTS) == {f"{replay.REPLAY_DIR}/{t}.json" for t in replay.VERSIONS} | {f"{replay.REPLAY_DIR}/summary.json"}


# ---------------------------------------------------------------- the check script (on the parsed HTML)

def test_the_stored_page_passes_the_check(page):
    assert problems(page) == []
    assert check_dashboard.main([str(ROOT / dashboard.DASHBOARD)]) == 0


def test_the_check_fails_on_an_untagged_or_unlinked_number_and_on_external_resources():
    ok = ('<div id="rec" data-record="r"><span class="num"><a class="n" href="#rec" data-tag="API-REPORTED" data-value="0.28421" '
          'title="0.28421 API-REPORTED">$0.2842</a><span class="tag API-REPORTED">API-REPORTED</span></span> <code>entry 8</code></div>')
    assert problems(ok) == []
    assert problems("<p>cost 0.28</p>")  # a bare number in text
    assert problems(ok.replace('<span class="tag API-REPORTED">API-REPORTED</span>', ""))  # no visible tag
    assert problems(ok.replace('data-tag="API-REPORTED"', ""))  # no tag at all
    assert problems(ok.replace('data-tag="API-REPORTED"', 'data-tag="MEASURED"'))  # the old tag name is no longer a tag (D-36)
    assert problems(ok.replace('href="#rec"', 'href="#missing"'))  # no record link
    assert problems(ok.replace(' data-record="r"', ""))  # the link target carries no record id
    assert problems(ok.replace("$0.2842", "$0.2850"))  # displayed text is not the value
    assert problems(ok.replace(">$0.2842<", ">0.28<"))
    assert problems(ok.replace(' data-value="0.28421"', ""))
    assert problems(ok.replace('<span class="tag API-REPORTED">API-REPORTED</span>', '<span class="tag ESTIMATED">ESTIMATED</span>'))
    # BILLED: the owner's balance reading links to a source (data-source), not to a record
    billed = ('<li id="b" data-source="owner-balance-reading"><span class="num"><a class="n" href="#b" data-tag="BILLED" data-value="0.39" data-source="owner-balance-reading" '
              'title="0.39 BILLED">$0.3900</a><span class="tag BILLED">BILLED</span></span></li>')
    assert problems(billed) == []
    no_source = billed.replace(' data-source="owner-balance-reading"', "")
    assert problems(no_source)  # neither the number nor its link target carries a source
    assert problems(no_source.replace('<li id="b">', '<li id="b" data-record="r">'))  # a record id is not a source for BILLED
    assert problems(ok.replace('data-record="r"', 'data-source="owner-balance-reading"'))  # nor is a source a record id for an API-REPORTED value
    for bad in ('<a href="https://example.com">x</a>', '<a href="//example.com/x">x</a>', '<img src="x.png">', "<script>x</script>",
                '<link rel="stylesheet" href="x.css">', "<style>p{animation:spin 1s}</style>", "<style>p{transition:all}</style>",
                '<style>@import "x.css";</style>', '<p style="background:url(x.png)">x</p>', '<p onclick="x()">x</p>', '<iframe src="x.html"></iframe>'):
        assert problems(bad), bad


def test_every_number_on_the_page_carries_its_tag_and_links_to_a_record(root):
    nums = numbers(root)
    assert len(nums) > 500
    ids = {n.attrs["id"]: n for n in root.walk() if "id" in n.attrs}
    for n in nums:
        assert n.attrs["data-tag"] in ("API-REPORTED", "ESTIMATED", "DERIVED", "BILLED")
        target = ids[n.attrs["href"][1:]]
        carried = "data-source" if n.attrs["data-tag"] == "BILLED" else "data-record"  # BILLED: the owner's reading, not a record
        assert n.attrs.get(carried) or any(carried in t.attrs for t in target.walk())
    assert {n.attrs["data-tag"] for n in nums} == {"API-REPORTED", "ESTIMATED", "DERIVED", "BILLED"}
    # BILLED: the owner's latest account reading, both readings, and the difference of the two on the gate whose interval holds them
    assert [(n.text(), n.attrs["data-value"]) for n in nums if n.attrs["data-tag"] == "BILLED"] == [
        ("$0.4300", "0.43"), ("$0.3900", "0.39"), ("$0.4300", "0.43"), ("$0.0400", "0.04")]


# ---------------------------------------------------------------- numbers: all from the REPLAY JSON

def test_every_number_in_the_html_exists_in_the_replay_json(root, inputs):
    tagged = set()
    for content in inputs.values():
        _tagged(json.loads(content.decode("utf-8")), tagged)
    json_tokens = set(NUMBER.findall("\n".join(c.decode("utf-8") for c in inputs.values())))
    for n in numbers(root):
        assert (n.attrs["data-value"], n.attrs["data-tag"]) in tagged, n.text()
        if "n" in n.classes():
            value = json.loads(n.attrs["data-value"])
            assert n.text() in (json.dumps(value), f"${value:.4f}")
    for code in _all(root, "code"):
        missing = set(NUMBER.findall(code.text())) - json_tokens
        assert not missing, f"{code.text()[:80]!r}: {sorted(missing)}"


def test_dollar_values_show_four_decimals_with_the_full_value_in_the_data_attribute_and_tooltip(root):
    dollars = [n for n in _all(root, "a", "n") if n.text().startswith("$")]
    assert len(dollars) > 500
    for n in dollars:
        assert re.fullmatch(r"\$\d+\.\d{4}", n.text())
        assert n.attrs["title"].startswith(n.attrs["data-value"] + " ") and float(n.attrs["data-value"]) == pytest.approx(float(n.text()[1:]), abs=5e-5)


# ---------------------------------------------------------------- views

def test_the_badge_sentence_in_the_html_equals_the_d1_text(root):
    stored = replay.load_passports(ROOT)
    shown = [n.text() for n in _all(root, "code", "badge-text")]
    expected = [next(p["badge"]["text"] for p in stored.values() if p["harness_tag"] == tag) for tag in replay.VERSIONS]
    assert shown == expected
    assert shown[1] == "EXPLORATORY — did not pass its pre-registered gate. a: 1/4 (measured), c: 0 citations in 7 searches."
    assert shown[2] == "EXPLORATORY — did not pass its pre-registered gate. a: 0/4, c: 0 citations (7 attempts consulted, 21 refs, 6 reasons recorded)."


def test_the_exploratory_badge_sits_above_the_numbers_and_is_absent_on_the_anchor(root):
    cards = {tag: _by_id(root, "v-" + dashboard.slug(tag)) for tag in replay.VERSIONS}
    for tag in (V133, V134):
        order = list(cards[tag].walk())
        band = next(n for n in order if n.tag == "div" and {"band", "exploratory"} <= n.classes())
        first_number = next(n for n in order if n.tag == "a" and "n" in n.classes())
        assert order.index(band) < order.index(first_number) and band.parent is cards[tag]
        assert "EXPLORATORY" in band.text() and "is-exploratory" in cards[tag].classes()
        assert [c for c in cards[tag].children if isinstance(c, Node)][0] is band  # the first thing in the card, not a footnote
    assert "EXPLORATORY" not in cards[V132].text() and not _all(cards[V132], "div", "exploratory")
    for tag in (V133, V134):
        assert _all(_by_id(root, "entries-" + dashboard.slug(tag)), "div", "exploratory")


def test_the_scorecard_shows_the_anchor_and_each_gate_criterion(root):
    anchor = _by_id(root, "v-" + dashboard.slug(V132))
    assert [n.text() for n in _all(anchor, "a", "n")][:2] == ["0", "16"]
    sets = [_clean(n.text()) for n in _all(anchor, "span", "set-name")]
    assert sets == ["control", "control arm, set control/infra_retries", "treatment"]
    for tag, results in ((V133, ["✕ FAIL", "✓ PASS", "✕ FAIL", "✓ PASS"]), (V134, ["✕ FAIL", "✓ PASS", "✕ FAIL", "✓ PASS"]),
                         (V140, ["✕ FAIL", "✓ PASS", "✓ PASS", "✓ PASS", "✓ PASS"]), (V141, ["✕ FAIL", "✓ PASS", "✓ PASS", "✓ PASS", "✓ PASS"]),
                         (V142, ["✕ FAIL", "✓ PASS", "✕ FAIL", "✓ PASS", "✓ PASS"]), (V143, ["✕ FAIL", "✓ PASS", "✓ PASS", "✓ PASS", "✓ PASS"])):
        card = _by_id(root, "v-" + dashboard.slug(tag))
        assert [n.text() for n in _all(card, "span", "res")] == results
        assert [n.text() for n in _all(card, "span", "crit-name")] == [f"Criterion {c}" for c in ("abcd" if tag in (V133, V134) else "abcde")]
    # the one RUNS_AFTER_REPAIR of the last gate is said to be a smoke-criterion verdict, beside the figure
    assert "smoke-criterion verdict" in _by_id(root, "v-" + dashboard.slug(V142)).text()
    assert "smoke-criterion verdict" not in _by_id(root, "v-" + dashboard.slug(V141)).text()
    assert "smoke-criterion verdict" not in _by_id(root, "v-" + dashboard.slug(V143)).text()  # the last gate had no RUNS_* verdict to annotate
    assert "smoke-limit artefact; measured line unchanged" in _by_id(root, "v-" + dashboard.slug(V133)).text()


def test_the_headline_card_states_the_finding_with_tagged_counts(root):
    card = _by_id(root, "headline")
    owner, statement = _all(card, "p", "statement")[:2]
    assert "owner" in owner.classes() and _clean(_text_without_tags(owner)) == HEADLINE_OWNER  # the first thing said, in the owner's own words
    assert _clean(_text_without_tags(statement)) == HEADLINE
    assert [n.text() for n in _all(next(iter(_all(card, "p", "big"))), "a", "n")] == ["2", "24"]
    assert all(n.attrs["data-tag"] == "API-REPORTED" for n in _all(card, "a", "n"))
    assert len(_all(_by_id(root, "hl-gate-entry-runs"), "li")) == 24 and len(_all(_by_id(root, "hl-with-recorded-model-attempt"), "li")) == 17
    # the 60 s in the owner's sentence is the record's own smoke seconds, a tagged number linking to that record
    seconds = [n for n in _all(owner, "a", "n")][2]
    assert seconds.text() == "60" and seconds.attrs["data-tag"] == "API-REPORTED" and "harness-v1.4.2/treatment/07@" in seconds.attrs["data-record"]
    assert "recovered" not in _clean(card.text()).lower().replace("recoveries", "")  # the word never stands without its criterion
    assert len(_all(_by_id(root, "hl-apparent-recoveries"), "li")) == 2 and len(_all(_by_id(root, "hl-recoveries-with-applied-model-repair"), "li")) == 1
    # the per-version table: every version's own count, never merged
    table = next(iter(_all(card, "table", "byversion")))
    rows = [[_clean(c.text()) for c in _all(r, "th") + _all(r, "td")] for r in _all(table, "tr")[1:]]
    assert [(r[0], r[1].split("API")[0], r[2].split("API")[0], r[5]) for r in rows] == [
        ("harness-v1.3.3", "4", "1", "false"), ("harness-v1.3.4", "4", "0", "false"), ("harness-v1.4.0", "4", "0", "false"),
        ("harness-v1.4.1", "4", "0", "false"), ("harness-v1.4.2", "4", "1", "false"), ("harness-v1.4.3", "4", "0", "false")]


def test_the_defect_register_lists_d1_to_d43_with_a_status_and_passport_links(root):
    rows = [n for n in _all(_by_id(root, "defects"), "tr") if n.attrs.get("id", "").startswith("defect-")]
    assert [next(iter(_all(r, "code"))).text() for r in rows] == [f"D-{i}" for i in range(1, 44)]
    ids = {n.attrs["id"] for n in root.walk() if "id" in n.attrs}
    status = {}
    for r in rows:
        chip = next(n for n in _all(r, "span", "status"))
        status[next(iter(_all(r, "code"))).text()] = chip.text().split(" ", 1)[1]
        for link in _all(r, "a"):
            href = link.attrs["href"]
            assert (href[1:] in ids) if href.startswith("#") else (ROOT / "reports/phase-d/dashboard" / href).resolve().is_file()
    assert set(status.values()) == {"fixed-and-gated", "fixed-unvalidated", "open"}
    assert status["D-24"] == "fixed-and-gated" and status["D-23"] == "fixed-and-gated"  # both re-read against the root-cause gate reports
    assert all(status[f"D-{i}"] == "open" for i in (1, 7, 21, 25, 26, 27, 28, 36, 43))
    # the last gate observed the D-39, D-40 and D-41 fixes live; the sustained-run line (D-42) made no live run
    assert status["D-37"] == "fixed-and-gated" and all(status[f"D-{i}"] == "fixed-and-gated" for i in (39, 40, 41)) and status["D-42"] == "fixed-unvalidated"
    d24 = next(r for r in rows if r.attrs["id"] == "defect-d-24")
    assert "def test_at_repair_time_the_recorded_gcc_error_adds_build_essential_with_no_model_call" in [c.text() for c in _all(d24, "code")]
    assert "harness-level, no entry passport" in next(r for r in rows if r.attrs["id"] == "defect-d-27").text()
    assert "Status (rule above)" in [n.text() for n in _all(_by_id(root, "defects"), "th")]
    d28 = next(r for r in rows if r.attrs["id"] == "defect-d-28")
    assert len(_all(d28, "span", "plink")) == 40
    d41 = next(r for r in rows if r.attrs["id"] == "defect-d-41")
    # the entry-3 record of every version (annotated beside its verdict), the one record checked and found not cut, and the last gate's entry 3 where the fix was seen
    assert len(_all(d41, "span", "plink")) == 12 and "Confirmed by a probe" in d41.text()


def test_the_ledger_shows_its_three_parts_as_a_lower_bound_with_the_eight_kill_records(root):
    ledger = _by_id(root, "ledger")
    big = next(n for n in _all(ledger, "p", "big"))
    assert [(n.text(), n.attrs["data-tag"]) for n in _all(big, "a", "n")] == [("$26.2069", "API-REPORTED"), ("$1.4761", "ESTIMATED"), ("$1.4874", "DERIVED")]
    text = _clean(ledger.text())
    assert "Lower bound (D-27)" in text and "Ceiling $32.00: **room $2.8296**." in text and "Sum of the three parts" in text
    total = next(n for n in _all(ledger, "a", "n") if n.attrs["data-tag"] == "ESTIMATED" and n.text() == "$29.1704")  # never one API-REPORTED figure
    assert total.attrs["data-value"].startswith("29.17037")
    assert "agree with it to the fourth decimal" in text and "The ledger as each gate report stated it" in text
    kills = _all(next(n for n in _all(ledger, "ul", "kills")), "li")
    assert len(kills) == 8
    seconds = [[n.text() for n in _all(k, "a", "n")][:1] for k in kills]
    # the v1.4.0 seal's first run-2 attempt stored no seconds and no completed cost, only an ESTIMATED upper bound: it is the first number shown
    assert seconds == [[], ["26.7"], ["26.3"], ["25.8"], ["$0.4998"], ["23.634523099994112"], ["20.029718199992203"], ["25.9"]] and "not recorded" in kills[0].text()
    # a kill whose step has an ESTIMATE shows it beside the API-reported completed cost, tagged separately
    assert [("estimate for the killed step" in k.text()) for k in kills] == [False, False, False, False, True, True, True, False]
    assert len(_all(_by_id(root, "ledger-components"), "tr")) == 25  # header + twenty-four components


def test_no_bar_merges_api_reported_and_estimated(root):
    meters = _all(root, "span", "meter")
    assert len(meters) > 50
    with_estimate = [m for m in meters if _all(m, "span", "e")]
    assert with_estimate
    for m in meters:
        segs = _all(m, "span", "seg")
        assert all(len(s.classes() & {"rep", "e"}) == 1 for s in segs)
    for m in with_estimate:
        assert _all(m, "span", "rep") and "separately" in m.attrs["aria-label"] and "API-reported" in m.attrs["aria-label"]
    entry = _by_id(root, "e-harness-v1-3-4-smoke-08")
    assert _all(next(n for n in _all(entry, "span", "meter")), "span", "e")
    assert len(_all(_by_id(root, "ledger"), "span", "sw")) == 2  # the legend names both parts


def test_the_entry_drill_down_shows_derived_values_with_their_source_line_and_record_id(root):
    entries = _all(root, "details", "entry")
    assert len(entries) == 65 and len({e.attrs["data-record"] for e in entries}) == 65
    entry = _by_id(root, "e-harness-v1-3-4-smoke-08")
    kill = next(n for n in _all(entry, "div", "kill"))
    derived = [n for n in _all(kill, "a") if n.attrs.get("data-tag") == "DERIVED"]
    assert [n.text() for n in derived] == ["55", "55", "cost_guard", "33", "55", "55"]
    assert all(n.attrs["data-record"] == entry.attrs["data-record"] for n in derived)
    lines = [c.text() for c in _all(kill, "code")]
    assert "[cost_guard] operation stopped at 55s; recorded $0.3582 (0.0740 measured + estimate for the killed step), $0.1063 left" in lines
    assert entry.attrs["data-record"] in lines
    assert "gate_passed_not_executed" in [c.text() for c in _all(entry, "code")]
    assert "gate_passed_not_executed" in _by_id(root, "e-harness-v1-3-4-smoke-11").text()
    artefact = _by_id(root, "e-harness-v1-3-3-smoke-11")
    assert "RUNS_AFTER_REPAIR" in artefact.text() and "ENTRY-11-SMOKE-LIMIT-ARTEFACT" in artefact.text()


def test_record_ids_link_to_the_blob_and_the_passport_and_show_the_d28_hash(root):
    for entry in _all(root, "details", "entry"):
        links = [a.attrs["href"] for a in _all(entry, "a") if not a.attrs["href"].startswith("#")]
        assert len(links) == 2 and links[0].startswith("../../../runs/") and links[1].startswith("../../../reports/phase-d/passports/")
        assert all((ROOT / "reports/phase-d/dashboard" / href).resolve().is_file() for href in links)
        record_id = entry.attrs["data-record"]
        assert record_id.split("@")[1] in [c.text() for c in _all(entry, "code")]
        listed = "worktree hash (D-28)" in [c.text() for c in _all(entry, "code")]
        assert listed is (record_id.startswith("harness-v1.3.2/") and "infra" not in entry.attrs["id"])


# ---------------------------------------------------------------- offline

def test_the_page_has_no_external_resource_script_or_animation(page, root):
    assert not _all(root, "script") and not _all(root, "link") and not _all(root, "img") and not _all(root, "iframe")
    for n in root.walk():
        for attr in ("href", "src"):
            value = n.attrs.get(attr)
            if value is not None:
                assert value.startswith("#") or value.startswith("../../../"), value
    css = next(iter(_all(root, "style"))).text()
    assert not re.search(r"animation|transition|@keyframes|@import|url\(|https?:", css)
    assert "<script" not in page.lower()


def test_the_page_renders_fully_with_the_network_blocked(tmp_path, page):
    browser = next((b for b in BROWSERS if Path(b).is_file()), None) or shutil.which("chromium") or shutil.which("google-chrome")
    if not browser:
        pytest.skip("no headless browser on this machine; the page has no external reference (asserted in the test above)")
    run = subprocess.run([browser, "--headless=new", "--disable-gpu", "--host-resolver-rules=MAP * ~NOTFOUND", f"--user-data-dir={tmp_path / 'profile'}",
                          "--virtual-time-budget=4000", "--dump-dom", (ROOT / dashboard.DASHBOARD).as_uri()], capture_output=True, timeout=120)
    dom = run.stdout.decode("utf-8", "replace")
    if "Evidence dashboard" not in dom:
        pytest.skip("the headless browser did not return a DOM on this machine")
    rendered = parse(dom)
    assert len(_all(rendered, "details", "entry")) == 65 and len(numbers(rendered)) == len(numbers(parse(page)))
    assert _clean(_text_without_tags(_all(rendered, "p", "statement")[1])) == HEADLINE
