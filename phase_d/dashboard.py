"""Phase D dashboard: one static HTML page rendered from the REPLAY JSON only (never from records or report text).

Display rules:
  * every number is `<a class="n" data-tag data-value data-record href="#...">` followed by its visible tag; the link
    goes to the record (or to the list of records) it was read from; nothing else outside `<code>` contains a digit;
  * `<code>` holds verbatim strings from the REPLAY JSON (ids, paths, quoted lines, the D1 badge sentence);
  * dollar values are shown with 4 decimals, the full-precision JSON value is in `data-value` and the tooltip;
  * a cost bar always draws API-REPORTED and ESTIMATED as separate segments;
  * the one BILLED number (the owner's account-balance reading) links to its own source line, not to a record;
  * no script, no animation, no external resource: the page opens from file://.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any

from .replay import REPLAY_DIR, VERSIONS

DASHBOARD = "reports/phase-d/dashboard/index.html"
UP = "../../../"  # from reports/phase-d/dashboard/ to the repository root
INPUTS = [f"{REPLAY_DIR}/{tag}.json" for tag in VERSIONS] + [f"{REPLAY_DIR}/summary.json"]


def esc(text: Any) -> str:
    return html.escape(str(text), quote=True)


def q(text: Any, cls: str = "") -> str:
    """A verbatim string from the REPLAY JSON."""
    text = "null" if text is None else text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
    return f'<code{f" class={chr(34)}{cls}{chr(34)}" if cls else ""}>{esc(text)}</code>'


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


class Page:
    def __init__(self, docs: dict[str, dict], summary: dict) -> None:
        self.docs, self.summary = docs, summary
        self.anchor: dict[str, str] = {}
        for tag in VERSIONS:
            for x in docs[tag]["entries"]:
                self.anchor[x["record_id"]] = "e-" + slug(f"{tag}-{x['record_set']}-{x['entry']['id']}")

    # ---------------------------------------------------------------- values

    def num(self, obj: Any, usd: bool = False, at: str | None = None) -> str:
        """A tagged value with its visible tag and its record link; an absent value with its reason."""
        if not isinstance(obj, dict) or "value" not in obj:
            raise ValueError(f"not a REPLAY value: {obj!r}")
        if obj["value"] is None:
            return f'<span class="absent">not recorded <span class="why">({q(obj.get("reason"))})</span></span>'
        tag, value = obj["tag"], obj["value"]
        record, source = "", ""
        if "ref" in obj:
            record = obj["ref"]["record_id"]
            at = at or self.anchor[record]
        elif "sum_of" in obj and "run_order_through" in obj["sum_of"]:
            record = obj["sum_of"]["run_order_through"]
            at = at or "run-" + slug(record.split("/")[0])
        elif "record_field" in obj:
            record = obj["record_field"]["record"]
        elif "owner_reading" in obj:
            source = "owner-balance-reading"  # BILLED: the owner's reading of the account balance page, not a record
        if at is None:
            raise ValueError(f"no record link for {obj!r}")
        full = json.dumps(value, ensure_ascii=False)
        attrs = (f'href="#{at}" data-tag="{tag}" data-value="{esc(full)}"' + (f' data-record="{esc(record)}"' if record else "")
                 + (f' data-source="{source}"' if source else ""))
        title = esc(f"{full} {tag}" + (f" — record {record}" if record else " — the owner's account-balance reading" if source else " — see the linked record list"))
        if isinstance(value, str):
            return f'<span class="num"><a class="s" {attrs} title="{title}">{q(value)}</a><span class="tag {tag}">{tag}</span></span>'
        shown = f"${value:.4f}" if usd else full
        return f'<span class="num"><a class="n" {attrs} title="{title}">{shown}</a><span class="tag {tag}">{tag}</span></span>'

    def plain(self, value: Any) -> str:
        """A plain value, or an absent one with its reason."""
        if isinstance(value, dict) and "value" in value:
            if value["value"] is None:
                return f'<span class="absent">not recorded <span class="why">({q(value.get("reason"))})</span></span>'
            return q(value["value"])
        if isinstance(value, list):
            return " ".join(q(v) for v in value) if value else '<span class="absent">none</span>'
        return q(value)

    def entry_link(self, record_id: str, label: str | None = None) -> str:
        return f'<a href="#{self.anchor[record_id]}" data-record="{esc(record_id)}">{q(label or record_id)}</a>'

    @staticmethod
    def set_name(rs: dict) -> str:
        return q(rs["arm"]) if rs["arm"] == rs["record_set"] else f'{q(rs["arm"])} arm, set {q(rs["record_set"])}'

    def meter(self, reported: Any, estimated: Any, cap: Any, label: str) -> str:
        m = reported or 0.0
        e = estimated or 0.0
        if not cap or cap <= 0:
            return ""
        scale = max(cap, m + e)
        parts = [f'<span class="seg rep" style="width:{100 * m / scale:.2f}%" title="API-reported part"></span>']
        if e > 0:
            parts.append(f'<span class="seg e" style="width:{100 * e / scale:.2f}%" title="estimated part"></span>')
        over = m + e > cap
        tick = f'<span class="cap" style="left:{100 * cap / scale:.2f}%" title="cap"></span>' if over else ""
        return f'<span class="meter{" over" if over else ""}" role="img" aria-label="{esc(label)}">{"".join(parts)}{tick}</span>'

    # ---------------------------------------------------------------- sections

    def headline(self) -> str:
        h = self.summary["headline"]
        lists = []
        for key, title in (("gate_entry_runs", "Gate entry-runs"), ("apparent_recoveries", "Apparent recoveries (RUNS_CLEAN or RUNS_AFTER_REPAIR)"),
                           ("apparent_recoveries_annotated_as_artefact", "Annotated as a smoke-limit artefact"),
                           ("recoveries_by_time_machine_alone", "Apparent recoveries from the time machine alone"),
                           ("recoveries_with_applied_model_repair", "Apparent recoveries with an applied model repair (smoke criterion)"),
                           ("with_recorded_model_attempt", "With a recorded model repair attempt")):
            ids = h[key]["count_of"]["records"]
            items = "".join(f"<li>{self.entry_link(r)}</li>" for r in ids) or '<li class="absent">no record meets this condition</li>'
            at = f"hl-{slug(key)}" if ids else "hl-gate-entry-runs"
            lists.append(f'<div id="hl-{slug(key)}"><h4>{title}: {self.num(h[key], at=at)}</h4><p class="why">{q(h[key]["count_of"]["where"])}</p><ul class="ids">{items}</ul></div>')
        art, smoke = h["artefact"][0], h["smoke_criterion_recovery"][0]
        art_name = f"{art['harness_tag'].replace('harness-', '')} entry {int(art['entry'])}"
        smoke_name = f"{smoke['harness_tag'].replace('harness-', '')} entry {int(smoke['entry'])}"
        runs = self.num(h["gate_entry_runs"], at="hl-gate-entry-runs")
        apparent = self.num(h["apparent_recoveries"], at="hl-apparent-recoveries")
        rows = ""
        for v in h["per_version"]:
            at = f"entries-{slug(v['harness_tag'])}"
            rows += (f'<tr><th scope="row">{q(v["harness_tag"])}</th><td>{self.num(v["entry_runs"], at=at)}</td><td>{self.num(v["apparent_recoveries"], at=at)}</td>'
                     f'<td>{self.num(v["indeterminate"], at=at)}</td><td>{self.num(v["blocked"], at=at)}</td><td>{q(v["gate_passed"])}</td></tr>')
        return f'''<section class="headline" id="headline" aria-labelledby="headline-h">
<h2 id="headline-h">Headline finding</h2>
<p class="big">{apparent} <span class="of">of</span> {runs}</p>
<p class="statement">Over every gate entry-run of the exploratory versions, {apparent} of {runs} ended RUNS_CLEAN or RUNS_AFTER_REPAIR, and no gate passed.
One of them ({self.entry_link(art["record_id"], art_name)}) was a smoke-limit artefact reached by the time machine alone, with no model attempt in its record.
The other ({self.entry_link(smoke["record_id"], smoke_name)}) is a smoke-criterion pass: the command ran for the smoke limit without failing, after model-proposed environment changes were adopted ({self.num(h["recoveries_with_applied_model_repair"], at="hl-recoveries-with-applied-model-repair")} such record); it did not run to completion and no result was reproduced.
A recorded model repair attempt exists in {self.num(h["with_recorded_model_attempt"], at="hl-with-recorded-model-attempt")} of {runs}.</p>
<p class="note">Annotation beside the first: {q(art["annotation"]["text"])}</p>
<p class="note">Annotation beside the second: {q(smoke["annotation"]["text"])}</p>
<div class="scroll"><table class="byversion"><thead><tr><th scope="col">Version</th><th scope="col">Entry-runs</th><th scope="col">Apparent recoveries</th><th scope="col">INDETERMINATE</th><th scope="col">BLOCKED</th><th scope="col">Gate passed</th></tr></thead><tbody>{rows}</tbody></table></div>
<details><summary>Records behind these counts</summary><div class="cols">{"".join(lists)}</div></details>
</section>'''

    def criterion(self, f: dict) -> str:
        bits = []
        names = {"recovered": "recovered", "entries": "of entries", "denominator": "of denominator", "applied": "applied", "proposed": "of proposed",
                 "citations": "citations", "searches": "searches", "attempts_consulted": "attempts consulted", "references_consulted": "references consulted",
                 "reasons_recorded": "reasons recorded", "cost_cap_endings": "cost-cap endings", "entries_ok": "entries passing"}
        for key, word in names.items():
            if key in f:
                bits.append(f"<span class=\"fig\">{word} {self.num(f[key])}</span>")
        verdict = ""
        if "ok" in f:
            verdict = '<span class="res pass">✓ PASS</span>' if f["ok"] else '<span class="res fail">✕ FAIL</span>'
        line = (f'<p class="gate-line">gate line {q(f["detail"])}</p>' if "detail" in f
                else f'<p class="gate-line">{q(f["label"])} — {q(f["note"])}</p>' if "label" in f else "")
        note = f'<p class="beside">Annotation beside this figure: {q(f["annotation"])}</p>' if "annotation" in f else ""
        if "proposed_note" in f:
            note += f'<p class="gate-line">{q(f["proposed_note"])}</p>'
        if "per_entry" in f:
            note += "<ul class=\"src\">" + "".join(f"<li>entry {q(entry)}: {q(detail)}</li>" for entry, detail in f["per_entry"].items()) + "</ul>"
        sources = ""
        derived = [v for v in f.values() if isinstance(v, dict) and v.get("tag") == "DERIVED"]
        if derived:
            rows = "".join(f"<li>{q(s['line'])} <span class=\"why\">{q(s['field'])} of {self.entry_link(s['record_id'])}</span></li>" for v in derived for s in v["source"])
            sources = f"<details><summary>Quoted source lines</summary><ul class=\"src\">{rows}</ul></details>"
        return f'<li class="crit"><div class="crit-head"><span class="crit-name">Criterion {q(f["criterion"])}</span>{verdict}</div><p class="figs">{" ".join(bits)}</p>{line}{note}{sources}</li>'

    def version_card(self, tag: str) -> str:
        doc = self.docs[tag]
        badge, exploratory = doc["badge"], doc["badge"]["exploratory"]
        band = (f'<div class="band exploratory"><span class="band-label">EXPLORATORY</span>{q(badge["text"], "badge-text")}</div>' if exploratory
                else f'<div class="band anchor"><span class="band-label">PRE-REGISTERED ANCHOR</span>{q(badge["text"], "badge-text")}</div>')
        crits = "".join(self.criterion(f) for f in doc["scorecard"]["criteria"])
        sets = ""
        for rs in doc["scorecard"]["record_sets"]:
            at = "set-" + slug(f"{tag}-{rs['record_set']}")
            counts = " ".join(f'<span class="fig">{q(v["verdict"])} {self.num(v["count"], at=at)}</span>' for v in rs["verdicts"])
            sets += f'<li><span class="set-name">{self.set_name(rs)}</span> {counts}</li>'
        batch = doc["batch"]
        cost = (f'<p class="costline">Batch cost: {self.num(batch["measured"], usd=True)} + {self.num(batch["estimated"], usd=True)} of cap {self.num(batch["cap"], usd=True)}</p>'
                + self.meter(batch["measured"]["value"], batch["estimated"]["value"], batch["cap"]["value"], "batch cost against the batch cap, API-reported and estimated drawn separately"))
        links = ""
        if exploratory:
            lk = badge["links"]
            links = (f'<p class="links">Gate passed: {q(badge["gate_passed"])}. Gate result <a href="{UP}{esc(lk["gate_result"])}">{q(lk["gate_result"])}</a>; '
                     f'report <a href="{UP}{esc(lk["gate_report"])}">{q(lk["gate_report"])}</a>; cost line {q(lk["cost_line"]["quote"])}. '
                     f'</p><details><summary>Run records</summary><ul class="ids">{"".join(f"<li>{self.entry_link(r)}</li>" for r in lk["run_records"])}</ul></details>')
        return f'''<article class="card version{' is-exploratory' if exploratory else ' is-anchor'}" id="v-{slug(tag)}">
{band}
<h3>{q(tag)}</h3>
<ul class="crits">{crits}</ul>
<h4>Verdicts by record set</h4><ul class="sets">{sets}</ul>
{cost}
{links}
</article>'''

    def scorecard(self) -> str:
        return ('<section id="scorecard" aria-labelledby="scorecard-h"><h2 id="scorecard-h">Gate scorecard</h2>'
                '<p class="lede">The pre-registered run is the anchor; control and treatment are separate record sets. The later versions are exploratory and none passed its own pre-registered gate.</p>'
                f'<div class="grid">{"".join(self.version_card(t) for t in VERSIONS)}</div></section>')

    def ledger(self) -> str:
        L = self.summary["ledger"]
        top = max((c["measured"]["value"] + (c["estimated"]["value"] or 0.0)) for c in L["components"])
        rows, lists = "", ""
        for c in L["components"]:
            at = f"led-{c['key']}"
            est = self.num(c["estimated"], usd=True, at=at)
            bar = self.meter(c["measured"]["value"], c["estimated"]["value"], top, "component cost, API-reported and estimated drawn separately")
            rows += (f'<tr><th scope="row">{esc(c["name"])} {q(c["harness_tag"])}</th><td>{self.num(c["measured"], usd=True, at=at)}</td><td>{est}</td>'
                     f'<td class="barcell">{bar}</td><td><a href="#{at}">records</a></td></tr>')
            items = ""
            for r in c["records"]:
                target = self.entry_link(r["record"]) if r["record"] in self.anchor else q(r["record"])
                items += f'<li data-record="{esc(r["record"])}">{target} <span class="why">cost field {q(r["cost_field"])}</span></li>'
            lists += f'<details id="{at}"><summary>{esc(c["name"])} {q(c["harness_tag"])} — records in {q(c["directory"])}</summary><ul class="ids">{items}</ul></details>'
        kills = ""
        for k in L["kill_records"]:
            at = f"led-{k['component']}"
            detail = f'stopped through {q(k["via"])}; {q(k["message"])}' if k["via"] else f'error line {q(k["error"])}'
            estimate = f' · estimate for the killed step {self.num(k["estimated_cost"], usd=True, at=at)}' if "estimated_cost" in k else ""
            kills += (f'<li data-record="{esc(k["record"])}">{q(k["record"])}<br>killed seconds {self.num(k["killed_seconds"], at=at)} · '
                      f'completed cost {self.num(k["completed_cost"], usd=True, at=at)}{estimate} · {detail}</li>')
        bl = L["billed"]
        acct = bl["account"]
        gate_lines = ""
        for g in bl["gates"]:
            if g["value"] is None:
                gate_lines += (f'<li id="billed-{slug(g["for_component"])}"><span class="why">{esc(g["name"])}</span> {q(g["harness_tag"])}: '
                               f'<span class="absent">no balance reading <span class="tag {g["tag"]}">{g["tag"]}</span> <span class="why">({q(g["reason"])})</span></span></li>')
            else:  # the interval between the owner's two readings that holds this gate
                gate_lines += (f'<li id="billed-{slug(g["for_component"])}" data-source="owner-balance-reading"><span class="why">{esc(g["name"])}</span> {q(g["harness_tag"])}: '
                               f'{esc(g["bound"])} {self.num(g, usd=True, at="billed-" + slug(g["for_component"]))} <span class="why">Source: {q(g["owner_reading"]["source"])}</span></li>')
        reading_lines = "".join(
            f'<li id="billed-reading-{i}" data-source="owner-balance-reading">reading {q(r["reading"])}: {esc(r["bound"])} {self.num(r, usd=True, at="billed-reading-" + str(i))} '
            f'<span class="why">Source: {q(r["owner_reading"]["source"])}</span></li>' for i, r in enumerate(bl["readings"]))
        billed = f'''<div class="billed" id="billed">
<h3 id="billed-h">Account balance reading</h3>
<p class="note">{q(bl["rule"])}</p>
<ul class="billed-lines">
<li id="billed-account" data-source="owner-balance-reading">{esc(acct["label"])}: {esc(acct["bound"])} {self.num(acct, usd=True, at="billed-account")}
<span class="why">Source: {q(acct["owner_reading"]["source"])} {esc(acct["note"])}</span></li>
{reading_lines}
{gate_lines}
</ul>
</div>'''
        return f'''<section id="ledger" aria-labelledby="ledger-h">
<h2 id="ledger-h">Cost ledger</h2>
<p class="big money">{self.num(L["measured"], usd=True, at="ledger-components")} <span class="of">+</span> {self.num(L["estimated"], usd=True, at="ledger-components")}</p>
<p class="statement">Lower bound ({q(L["lower_bound"]["defect"])}): the ledger records only completed cost, so the spend of a killed step is absent wherever no estimate was stored.
Sum of both parts: {self.num(L["total"], usd=True, at="ledger-components")} — {q(L["total"]["note"])}.</p>
<p class="statement">These ledger figures are the sandbox API's reported operation cost, not account billing. The account balance reading below is a different figure, and the two are not reconciled ({q("D-36")}, open).</p>
{billed}
<p class="note">Reported ledger line, quoted: {q(L["reported_line"]["quote"])} in {q(L["reported_line"]["path"])}. The sums shown here are over the full-precision record values and agree with it to the fourth decimal. Annotation beside that line: {q(L["lower_bound"]["line"]["quote"])}</p>
<details><summary>The ledger as each gate report stated it</summary><ul class="src">{"".join(f'<li>{q(h["harness_tag"])}: {q(h["quote"])} <span class="why">{q(h["path"])}</span></li>' for h in L["reported_history"])}</ul></details>
<p class="legend"><span class="key"><span class="sw rep"></span>API-REPORTED</span><span class="key"><span class="sw e"></span>ESTIMATED (hatched)</span></p>
<div id="ledger-components"><table class="ledger"><thead><tr><th scope="col">Component</th><th scope="col">API-reported</th><th scope="col">Estimated</th><th scope="col">Share of the largest component</th><th scope="col">Records</th></tr></thead><tbody>{rows}</tbody></table>
<h3>Seal kill records: the killed step's cost is absent or ESTIMATED</h3>
<ul class="kills">{kills}</ul>
{lists}
</div>
</section>'''

    def stack(self) -> str:
        cards = ""
        for v in self.summary["stack"]["versions"]:
            at = "run-" + slug(v["harness_tag"])
            roles = "".join(f"<tr><th scope=\"row\">{esc(r['role'])}</th><td>{q(r['model'])}</td><td>{esc(r['does'])}</td></tr>" for r in v["roles"])
            calls = "".join(
                f"<tr><th scope=\"row\">{q(c['model'])}</th><td>{self.num(c['calls'], at=at)}</td><td>{self.num(c['prompt_tokens'], at=at)}</td>"
                f"<td>{self.num(c['completion_tokens'], at=at)}</td></tr>" for c in v["model_calls"])
            sandbox = v["sandbox"]
            cards += (f'<article class="card"><h3>{q(v["harness_tag"])}</h3>'
                      f'<table><thead><tr><th scope="col">Role</th><th scope="col">Model, as recorded</th><th scope="col">What the call does</th></tr></thead><tbody>{roles}</tbody></table>'
                      f'<table><thead><tr><th scope="col">Model</th><th scope="col">Calls</th><th scope="col">Prompt tokens</th><th scope="col">Completion tokens</th></tr></thead><tbody>{calls}</tbody></table>'
                      f'<p class="links">Sandbox backend {q(sandbox["backend"])}, default image {q(sandbox["default_image"])}; prices from {q(sandbox["prices_source"])}, retrieved {q(sandbox["prices_retrieved"])}. '
                      f'Records with {esc(v["search"]["provider"])} search configured: {self.num(v["search"]["records_with_search_configured"], at=at)}.</p></article>')
        inv = self.summary["inventory"]
        return (f'<section id="stack" aria-labelledby="stack-h"><h2 id="stack-h">How it ran, as recorded</h2>'
                f'<p class="lede">Models, sandbox and search as the run records name them. {esc(self.summary["stack"]["note"])}. '
                f'Run records with a passport: {self.num(inv["records"], at="entries")}; defect register rows: {self.num(inv["defects"], at="defects")}.</p>'
                f'<div class="grid wide">{cards}</div></section>')

    def defects(self) -> str:
        D = self.summary["defects"]
        icon = {"fixed-and-gated": "●", "fixed-unvalidated": "◐", "open": "○"}
        rule = "".join(f'<li><span class="status {s}">{icon[s]} {s}</span> {esc(text)}</li>' for s, text in D["status_rule"].items())
        rows = ""
        for r in D["rows"]:
            basis = "".join(f'<li>{q(b["quote"])} <span class="why">{q(b["path"])}</span></li>' for b in [r["registered"]] + r["basis"])
            links = " ".join(f'<span class="plink">{self.entry_link(p["record_id"], p["harness_tag"].replace("harness-", "") + " " + p["arm"] + " " + p["entry"])}'
                             f' <a class="pfile" href="{UP}{esc(p["passport_path"])}">passport</a></span>' for p in r["passports"])
            if len(r["passports"]) > 6:
                links = f"<details><summary>passports carrying this defect</summary>{links}</details>"
            note = f'<p class="why">{esc(r["note"])}</p>' if r["note"] else ""
            rows += (f'<tr id="defect-{slug(r["id"])}"><th scope="row">{q(r["id"])}</th><td>{esc(r["title"])}{note}</td>'
                     f'<td><span class="status {r["status"]}">{icon[r["status"]]} {r["status"]}</span></td>'
                     f'<td>{links or "<span class=absent>harness-level, no entry passport</span>"}</td>'
                     f'<td><details><summary>quoted basis</summary><ul class="src">{basis}</ul></details></td></tr>')
        return f'''<section id="defects" aria-labelledby="defects-h">
<h2 id="defects-h">Defect register</h2>
<ul class="rule">{rule}</ul>
<div class="scroll"><table class="defects"><thead><tr><th scope="col">Defect</th><th scope="col">What it is</th><th scope="col">Status (rule above)</th><th scope="col">Passports it annotates</th><th scope="col">Basis</th></tr></thead><tbody>{rows}</tbody></table></div>
</section>'''

    def execution(self, ex: dict) -> str:
        out = f'<p class="exec">Execution: mode {self.plain(ex["mode"])} · seconds {self.num(ex["seconds"])} · outcome {self.plain(ex["outcome"])}</p>'
        if ex["killed"]:
            line = ex["cap_line"]
            seen, srcs = set(), ""
            for v in (ex["funded_seconds"], ex["wall_seconds"], ex["killed_by"], ex["killed_step_seconds"]):
                s = v.get("source")
                if s and s["line"] not in seen:
                    seen.add(s["line"])
                    srcs += f'<li>{q(s["line"])} <span class="why">{q(s["field"])} of {self.entry_link(s["record_id"])}</span></li>'
            out += (f'<div class="kill"><p><strong>Killed.</strong> Funded seconds {self.num(ex["funded_seconds"])} · wall seconds {self.num(ex["wall_seconds"])} · '
                    f'killed by {self.num(ex["killed_by"])} · killed step seconds {self.num(ex["killed_step_seconds"])}</p>'
                    f'<p>Cap line at second {self.num(line["limit_second"])}, crossed at second {self.num(line["crossed_at_second"])}: {q(line["crossed"])}</p>'
                    f'<ul class="src">{srcs}</ul></div>')
        return out

    def step(self, s: dict) -> str:
        if s["step"] == "baseline":
            return (f'<li class="step"><h5>Baseline</h5><p>{q(s["result"])} · exit code {self.num(s["exit_code"])} · {q(s["taxonomy_code"])}</p>'
                    f'<p class="ev">evidence {q(s["evidence"])}</p></li>')
        if s["step"] == "verdict":
            notes = ""
            for n in s["annotations"]:
                src = "; ".join(f'{q(x["quote"])} in {q(x["path"])}' for x in n["sources"])
                related = f' Related record: {self.entry_link(n["related_record"])}.' if "related_record" in n else ""
                reg = f' <a href="#defect-{slug(n["id"])}">register row</a>' if n["id"].startswith("D-") else ""
                notes += f'<li class="beside">Annotation {q(n["id"])}{reg}: {q(n["text"])}{related} <span class="why">Source: {src}</span></li>'
            reason = f'<p class="ev">{q(s["indeterminate_reason"])}</p>' if s["indeterminate_reason"] else ""
            return (f'<li class="step verdict"><h5>Verdict</h5><p><span class="verdict-chip">{q(s["verdict"])}</span> taxonomy {q(s["taxonomy_code"])} · reason {q(s["reason_code"])} · '
                    f'recovery {q(s["recovery"])}</p>{reason}<ul class="notes">{notes}</ul></li>')
        if "era_lock" in s:
            lock = s["era_lock"]
            head = f'<h5>Era lock {q(s["attempt"])}</h5><p>era {q(lock["era_date"])} · Python {q(lock["python"])} · lock ok {q(lock["lock_ok"])} · fallback {q(lock["fallback"])}</p>'
        elif s["step"] == "rule":
            head = f'<h5>Rule step {q(s["attempt"])} ({q(s["type"])})</h5><p>{self.rule(s["rule_step"])}</p>'
        else:
            p = s["proposed"]
            delta = " ".join(q(" ".join(str(x[k]) for k in ("op", "package", "version") if x[k])) for x in p["env_delta"]) or '<span class="absent">none</span>'
            head = (f'<h5>Attempt {q(s["attempt"])} ({q(s["type"])})</h5><p>Proposed: diff {self.plain(p["diff_sha256"])} · environment change {delta} · '
                    f'patch notes {self.plain(p["patch_notes"])}</p>')
        cited = s["cited"]
        cited_html = (" ".join(q(c["url"]) for c in cited) or '<span class="absent">none</span>') if isinstance(cited, list) else self.num(cited)
        candidate = ""
        if "candidate" in s:  # harness-v1.4.x
            adj = s["adjudication"]
            adjudication = ""
            if isinstance(adj, dict) and "reasoning" in adj:
                adjudication = (f' Adjudication of the round: chosen {q(adj["chosen"])} of {q(adj["qualifying"])}{(" · " + q(adj["adopted_reason"])) if "adopted_reason" in adj else ""}'
                                f'{(" · re-asked " + q(adj["reasked"])) if "reasked" in adj else ""} — {q(adj["reasoning"])}')
            on_branch = (f' Rule steps on this branch: {self.rule(s["rule_step"])}' if isinstance(s.get("rule_step"), dict) and "rule" in s["rule_step"] and s["step"] == "attempt" else "")
            candidate = (f'<p>Candidate {self.plain(s["candidate"])} · chosen {self.plain(s["chosen"])} · branch {self.plain(s["branch"])}.{adjudication}{on_branch}</p>')
        return (f'<li class="step"><div class="step-head">{head}</div>'
                f'<p>Gate {q(s["gate_decision"])} → <span class="outcome {esc(s["outcome"])}">{q(s["outcome"])}</span> · reject reason {self.plain(s["reject_reason"])}</p>'
                f'<p>Consulted {self.num(s["consulted_count"])} · cited {cited_html} · reason_no_citation {self.plain(s["reason_no_citation"])} · '
                f'silent_exit {self.plain(s["silent_exit"])} · exit code {self.num(s["exit_code"])}</p>{candidate}{self.execution(s["execution"])}</li>')

    def rule(self, rule_step: Any) -> str:
        """One deterministic rule step (harness-v1.4.x): the rule and the fields that say what it did, quoted."""
        if not isinstance(rule_step, dict) or "rule" not in rule_step:
            return self.plain(rule_step)
        bits = [f"rule {q(rule_step['rule'])}"]
        for key in ("matched_error", "hook", "applied", "result", "paths_fired", "kill_evidenced", "limit_quote", "on_candidate", "apt_added", "reason"):
            if key in rule_step:
                bits.append(f"{key.replace('_', ' ')} {q(rule_step[key])}")
        bits += [f"then {self.rule(follow)}" for follow in rule_step.get("then") or []]
        return " · ".join(bits)

    def entry(self, x: dict) -> str:
        c = x["cost"]
        verdict = x["timeline"][-1]["verdict"]
        ops = ""
        for op in c["operations"]:
            extra = f' · stopped at second {self.num(op["stopped_at_second"])} · API-reported part {self.num(op["measured_part"], usd=True)}' if op["killed"] else ""
            src = op["spend"]["source"]
            ops += (f'<li>{q(op["operation"])}: spend {self.num(op["spend"], usd=True)} · remaining {self.num(op["remaining"], usd=True)}{extra}'
                    f'<br><span class="why">{q(src["line"])} — {q(src["field"])} of {q(src["record_id"])}</span></li>')
        stored = ""
        for op in c.get("stored_operations", []):  # harness-v1.4.x: the record's own operation list (a disposal run has no wall or funded seconds)
            fields = " · ".join(f"{name.replace('_', ' ')} {self.num(op[name], usd=name.startswith('cost'))}" for name in
                                ("wall_seconds", "sandbox_seconds", "funded_seconds", "cost_usd", "cost_estimated_usd") if name in op)
            stored += f'<li>stored operation {self.num(op["n"])} {q(op["role"])}: outcome {q(op["outcome"])} · {fields}</li>'
        stored = f'<h4>Operations as the record stores them</h4><ol class="ops">{stored}</ol>' if stored else ""
        cum = c["batch_cumulative"]
        wt = x["results_tables_sha256"]
        worktree = (f'{q(wt["label"])} {q(wt["value"])} <span class="why">{q(wt["note"])}</span>' if wt["value"] else
                    f'<span class="absent">worktree hash not listed <span class="why">({q(wt["reason"])})</span></span>')
        superseded = f'<p class="beside">Superseded by {self.entry_link(x["superseded_by"])}</p>' if x["superseded_by"] else ""
        bar = self.meter(c["measured"]["value"], c["estimated"]["value"], c["per_entry_cap"]["value"], "entry cost against the entry cap, API-reported and estimated drawn separately")
        return f'''<details class="entry" id="{self.anchor[x["record_id"]]}" data-record="{esc(x["record_id"])}">
<summary><span class="eid">{q(x["entry"]["id"])}</span> <span class="ename">{q(x["entry"]["name"])}</span> <span class="verdict-chip">{q(verdict)}</span>
<span class="ecost">{self.num(c["entry_total"], usd=True)}</span>{bar}</summary>
<div class="entry-body">
<dl class="ids">
<dt>Record id</dt><dd>{q(x["record_id"])}</dd>
<dt>Committed blob</dt><dd><a href="{UP}{esc(x["record_path"])}">{q(x["record_path"])}</a> sha {q(x["record_sha256"])}</dd>
<dt>Worktree hash</dt><dd>{worktree}</dd>
<dt>Passport</dt><dd><a href="{UP}{esc(x["passport_path"])}">{q(x["passport_path"])}</a> hash {q(x["passport_hash"])}</dd>
<dt>Image id</dt><dd>{q(x["image_id"])} <span class="why">not an identity: several records can share one</span></dd>
</dl>
{superseded}
<h4>Timeline</h4><ol class="timeline">{"".join(self.step(s) for s in x["timeline"])}</ol>
<h4>Cost</h4>
<p>Total {self.num(c["entry_total"], usd=True)} = API-reported {self.num(c["measured"], usd=True)} + estimated {self.num(c["estimated"], usd=True)} · model {self.num(c["model"], usd=True)} ·
entry cap {self.num(c["per_entry_cap"], usd=True)} · over the entry cap {q(c["over_entry_cap"])}</p>
<ol class="ops">{ops}</ol>
{stored}
<p>Batch so far: API-reported {self.num(cum["measured"], usd=True)} + estimated {self.num(cum["estimated"], usd=True)} of cap {self.num(c["batch_cap"], usd=True)} ·
over the batch cap {q(cum["over_batch_cap"])}</p>
</div></details>'''

    def entries(self) -> str:
        out = ""
        for tag in VERSIONS:
            doc = self.docs[tag]
            by_id = {x["record_id"]: x for x in doc["entries"]}
            sets = ""
            for rs in doc["scorecard"]["record_sets"]:
                at = "set-" + slug(f"{tag}-{rs['record_set']}")
                sets += f'<div class="set" id="{at}"><h4>{self.set_name(rs)}</h4>{"".join(self.entry(by_id[r]) for r in rs["records"])}</div>'
            order = "".join(f"<li>{self.entry_link(r)}</li>" for r in doc["batch"]["run_order"])
            badge = (f'<div class="band exploratory small"><span class="band-label">EXPLORATORY</span>{q(doc["badge"]["text"])}</div>' if doc["badge"]["exploratory"] else
                     '<div class="band anchor small"><span class="band-label">PRE-REGISTERED ANCHOR</span></div>')
            out += (f'<section class="version-entries" id="entries-{slug(tag)}">{badge}<h3>{q(tag)}</h3>{sets}'
                    f'<details class="runorder"><summary>Run order (the order cost accumulates in)</summary><ol id="run-{slug(tag)}" class="ids">{order}</ol></details></section>')
        return ('<section id="entries" aria-labelledby="entries-h"><h2 id="entries-h">Entries</h2>'
                '<p class="lede">Open an entry for its timeline, each derived value with its quoted source line, and its cost against the entry cap and the batch cap.</p>'
                f'{out}</section>')

    def render(self, input_paths: list[str]) -> str:
        inputs = "".join(f'<li><a href="{UP}{esc(p)}">{q(p)}</a></li>' for p in input_paths)
        return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RERUN evidence dashboard</title>
<style>{CSS}</style>
</head>
<body>
<header class="top">
<p class="kicker">RERUN, reproducibility harness</p>
<h1>Evidence dashboard</h1>
<p class="lede">A negative result, laid out so it can be checked. Every number below carries its tag and links to the record it was read from (the one BILLED number links to the owner's balance reading it came from); quoted text is verbatim from a committed record.</p>
<ul class="taglegend">
<li><span class="tag API-REPORTED">API-REPORTED</span> (formerly MEASURED) a stored field of a committed record, or a count or sum of such fields; a dollar figure with this tag is the sandbox API's reported operation cost, not account billing ({q("D-36")}, open)</li>
<li><span class="tag ESTIMATED">ESTIMATED</span> flagged as an estimate by the cost guard itself</li>
<li><span class="tag DERIVED">DERIVED</span> parsed from a record line, which is quoted with its record id</li>
<li><span class="tag BILLED">BILLED</span> an account-balance reading taken by the owner; used only in the explicit BILLED lines of the ledger, never on an API cost</li>
</ul>
<nav aria-label="Sections"><a href="#headline">Headline</a><a href="#scorecard">Scorecard</a><a href="#ledger">Ledger</a><a href="#stack">Stack</a><a href="#defects">Defects</a><a href="#entries">Entries</a></nav>
</header>
<main>
{self.headline()}
{self.scorecard()}
{self.ledger()}
{self.stack()}
{self.defects()}
{self.entries()}
</main>
<footer>
<p>Built offline by {q("python -m phase_d.build_dashboard")} from the REPLAY JSON only. Input files (their hashes are listed in the REPLAY index):</p>
<ul class="ids">{inputs}</ul>
</footer>
</body>
</html>
'''


def build_html(files: dict[str, bytes]) -> bytes:
    """The dashboard page from the REPLAY JSON files ({repository path: bytes})."""
    docs = {tag: json.loads(files[f"{REPLAY_DIR}/{tag}.json"].decode("utf-8")) for tag in VERSIONS}
    summary = json.loads(files[f"{REPLAY_DIR}/summary.json"].decode("utf-8"))
    return Page(docs, summary).render(INPUTS).encode("utf-8")


CSS = """
:root{color-scheme:light;--bg:#eef1ef;--surface:#ffffff;--ink:#101815;--ink2:#46544f;--rule:#c9d1cd;--quote:#f4f6f5;
--rep:#2a78d6;--e:#eb6834;--d:#4a3aa7;--b:#0b7a75;--warn:#fab219;--warn-ink:#1c1400;--fail:#b3261e;--pass:#0b6b0b;--link:#0b4fa8}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--bg:#121614;--surface:#1b211e;--ink:#f2f5f3;--ink2:#b4c0bb;--rule:#38423e;--quote:#232a27;
--rep:#3987e5;--e:#d95926;--d:#9085e9;--b:#4fd1c5;--warn:#fab219;--warn-ink:#1c1400;--fail:#ff8a80;--pass:#6fd66f;--link:#8ab8ff}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header.top,main,footer{max-width:76rem;margin:0 auto;padding:1.25rem 1rem}
h1,h2,h3,.big{font-family:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;line-height:1.1;margin:0}
h1{font-size:clamp(2.2rem,6vw,3.6rem);letter-spacing:-.01em}
h2{font-size:1.9rem;margin:0 0 .6rem;padding-top:.4rem;border-top:3px solid var(--ink)}
h3{font-size:1.3rem;margin:.6rem 0}
h4{font-size:1rem;margin:1rem 0 .3rem}
h5{font-size:.95rem;margin:0 0 .2rem}
.kicker{margin:0 0 .3rem;color:var(--ink2);font-weight:600}
.lede{max-width:62ch;color:var(--ink2);margin:.5rem 0 1rem}
a{color:var(--link)}
a:focus-visible,summary:focus-visible{outline:3px solid var(--warn);outline-offset:2px}
nav{display:flex;flex-wrap:wrap;gap:.4rem 1.1rem;margin-top:.8rem}
nav a{font-weight:600;padding:.5rem 0}
code{font:0.86em/1.45 ui-monospace,"Cascadia Mono",Consolas,Menlo,monospace;background:var(--quote);padding:.05em .3em;border-radius:3px;overflow-wrap:anywhere}
code.badge-text{display:block;font:600 1rem/1.4 system-ui,-apple-system,"Segoe UI",sans-serif;background:transparent;padding:0;color:inherit}
section{margin:0 0 2.6rem}
.num{white-space:nowrap}
.n,.s{font-variant-numeric:tabular-nums;font-weight:700;color:var(--ink);text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:2px}
.tag{font:700 .62rem/1 system-ui,sans-serif;letter-spacing:.04em;margin-left:.3em;padding:.2em .4em;border-radius:3px;border:1px solid currentColor;vertical-align:.2em;white-space:nowrap}
.tag.API-REPORTED{color:var(--rep)}.tag.ESTIMATED{color:var(--e);border-style:dashed}.tag.DERIVED{color:var(--d);border-style:dotted}
.tag.BILLED{color:var(--b);border-style:double;border-width:3px}
.taglegend{list-style:none;padding:0;margin:0;display:grid;gap:.3rem;color:var(--ink2);font-size:.92rem}
.absent{color:var(--ink2);font-style:italic}
.why{color:var(--ink2);font-size:.86rem}
.headline{background:var(--surface);border:1px solid var(--rule);border-left:10px solid var(--ink);padding:1.2rem 1.4rem;border-radius:4px}
.headline h2{border:0;font:700 .95rem/1.2 system-ui,sans-serif;color:var(--ink2);padding:0}
.big{font-size:clamp(3.4rem,13vw,7.5rem);font-weight:700;margin:.2rem 0 .4rem}
.big .n{text-decoration:none}
.big .tag{font-size:.7rem;vertical-align:2.6em}
.big .of{font-size:.38em;font-weight:400;color:var(--ink2);margin:0 .2em}
.big.money{font-size:clamp(2rem,7vw,3.6rem)}
.big.money .tag{vertical-align:1.6em}
.statement{font-size:1.15rem;max-width:68ch;margin:.4rem 0}
.note{color:var(--ink2);max-width:80ch}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(17rem,1fr));gap:.6rem 1.4rem}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(19rem,1fr));gap:1rem;align-items:start}
.grid.wide{grid-template-columns:repeat(auto-fit,minmax(26rem,1fr))}
.card table{margin:.4rem 0;border:0}
.card{background:var(--surface);border:1px solid var(--rule);border-radius:4px;padding:0 1rem 1rem;overflow:hidden}
.band{margin:0 -1rem .6rem;padding:.7rem 1rem;border-bottom:1px solid var(--rule)}
.band-label{display:inline-block;font:800 .8rem/1 system-ui,sans-serif;letter-spacing:.08em;padding:.3em .5em;margin-bottom:.45rem;border:2px solid currentColor}
.band.exploratory{background:var(--warn);color:var(--warn-ink);border-bottom:6px solid var(--warn-ink);
background-image:repeating-linear-gradient(135deg,transparent 0 14px,rgba(28,20,0,.13) 14px 18px)}
.band.exploratory code{color:var(--warn-ink);background:transparent}
.band.anchor{background:var(--quote);border-bottom:6px solid var(--rep)}
.band.small{margin:0 0 .5rem;border-radius:4px}
.crits,.sets,.rule,.kills,.notes,.src,ul.ids,ol.ids{list-style:none;padding:0;margin:0}
.crit{padding:.55rem 0;border-top:1px solid var(--rule)}
.crit-head{display:flex;justify-content:space-between;gap:.5rem;align-items:baseline}
.crit-name{font-weight:700}
.res{font:800 .8rem/1 system-ui,sans-serif;padding:.25em .5em;border-radius:3px;border:2px solid currentColor}
.res.fail{color:var(--fail)}.res.pass{color:var(--pass)}
.figs{margin:.3rem 0;display:flex;flex-wrap:wrap;gap:.2rem .9rem}
.gate-line,.ev{margin:.2rem 0;color:var(--ink2);font-size:.9rem}
.beside{margin:.3rem 0;padding:.4rem .6rem;border-left:4px solid var(--warn);background:var(--quote);font-size:.92rem}
.sets li{padding:.3rem 0;border-top:1px solid var(--rule);display:flex;flex-wrap:wrap;gap:.2rem .8rem}
.set-name{font-weight:700}
.costline{margin:.7rem 0 .3rem}
.links{font-size:.86rem;color:var(--ink2)}
.meter{display:flex;position:relative;height:12px;width:100%;min-width:6rem;background:var(--quote);border:1px solid var(--rule);border-radius:2px;gap:2px;overflow:hidden}
.seg{display:block;height:100%}
.seg.rep{background:var(--rep)}
.seg.e{background:var(--e);background-image:repeating-linear-gradient(45deg,transparent 0 3px,rgba(255,255,255,.75) 3px 5px)}
.meter .cap{position:absolute;top:-2px;bottom:-2px;width:3px;background:var(--ink)}
.meter.over{border-color:var(--fail)}
.billed{background:var(--surface);border:1px solid var(--rule);border-left:6px solid var(--b);border-radius:4px;padding:.4rem 1rem .7rem;margin:.8rem 0}
.billed h3{margin:.2rem 0}
.billed-lines{list-style:none;padding:0;margin:.3rem 0 0}
.billed-lines li{padding:.3rem 0;border-top:1px solid var(--rule)}
.legend{display:flex;gap:1.2rem;font-size:.86rem;color:var(--ink2);margin:.4rem 0}
.key{display:inline-flex;align-items:center;gap:.35rem}
.sw{display:inline-block;width:1.4rem;height:.7rem;border-radius:2px}
.sw.rep{background:var(--rep)}.sw.e{background:var(--e);background-image:repeating-linear-gradient(45deg,transparent 0 3px,rgba(255,255,255,.75) 3px 5px)}
table{border-collapse:collapse;width:100%;background:var(--surface);border:1px solid var(--rule)}
th,td{text-align:left;vertical-align:top;padding:.5rem .6rem;border-top:1px solid var(--rule);font-size:.93rem}
thead th{border-top:0;font-size:.8rem;color:var(--ink2)}
.barcell{min-width:9rem;vertical-align:middle}
.scroll{overflow-x:auto}
.kills li{background:var(--surface);border:1px solid var(--rule);border-left:6px solid var(--e);padding:.5rem .7rem;margin:.4rem 0}
.rule li{margin:.3rem 0;color:var(--ink2);font-size:.92rem}
.status{font:700 .78rem/1 system-ui,sans-serif;padding:.3em .5em;border-radius:3px;border:2px solid currentColor;white-space:nowrap;margin-right:.4em}
.status.open{color:var(--fail)}.status.fixed-unvalidated{color:var(--ink2);border-style:dashed}.status.fixed-and-gated{color:var(--pass)}
.plink{display:inline-block;margin:0 .6rem .2rem 0}
.pfile{font-size:.82rem}
details{margin:.35rem 0}
summary{cursor:pointer;padding:.45rem .2rem;min-height:2.75rem}
details.entry{background:var(--surface);border:1px solid var(--rule);border-radius:4px}
details.entry>summary{display:grid;grid-template-columns:auto minmax(8rem,1fr) auto auto minmax(6rem,10rem);gap:.3rem .8rem;align-items:center;padding:.5rem .7rem}
details.entry[open]>summary{border-bottom:1px solid var(--rule)}
.entry-body{padding:.6rem .9rem 1rem}
.verdict-chip code{font-weight:700;border:1px solid var(--rule)}
dl.ids{display:grid;grid-template-columns:max-content 1fr;gap:.2rem .9rem;margin:0}
dl.ids dt{color:var(--ink2);font-size:.86rem}
dl.ids dd{margin:0}
ul.ids li,ol.ids li{padding:.12rem 0}
ol.ids{list-style:none;padding-left:0}
.timeline{list-style:none;margin:0;padding:0 0 0 1rem;border-left:3px solid var(--rule)}
.step{position:relative;padding:.1rem 0 .7rem .9rem}
.step::before{content:"";position:absolute;left:-1.42rem;top:.35rem;width:.7rem;height:.7rem;border-radius:50%;background:var(--surface);border:3px solid var(--ink)}
.step.verdict::before{background:var(--ink)}
.step p{margin:.15rem 0}
.outcome.applied code{border:1px solid var(--pass)}
.outcome.rejected code,.outcome.gate_passed_not_executed code{border:1px solid var(--fail)}
.kill{border:2px solid var(--fail);border-radius:4px;padding:.4rem .7rem;margin:.4rem 0;background:var(--quote)}
.ops{list-style:none;padding-left:0}
.ops li{margin:.25rem 0}
.src li{margin:.2rem 0;font-size:.88rem}
footer{color:var(--ink2);font-size:.88rem;border-top:1px solid var(--rule)}
@media (max-width:640px){details.entry>summary{grid-template-columns:auto 1fr}dl.ids{grid-template-columns:1fr}.big .tag{vertical-align:1.2em}}
@media print{details{break-inside:avoid}.meter{border-color:#000}}
"""
