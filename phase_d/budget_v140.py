"""v1.4.0 budget note (Step 0 of the v1.4.0 directive): offline, from committed records only. No network, no model call.

Reads the 8 gate records of harness-v1.3.3 and harness-v1.3.4 (git blobs) and the harness-v1.3.4 seal-verification
records, splits each entry's spend into sandbox and model, counts the torch installs, and estimates a v1.4.0 gate
under "install once, branch per attempt". Every number in the output carries API-REPORTED, DERIVED or ESTIMATED and the
line it comes from.

    python -m phase_d.budget_v140            # writes docs/design/v1.4.0-budget.md
    python -m phase_d.budget_v140 --check    # fails if the committed file differs from what the records give
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field

from .records import ROOT, Record, load_records

OUT = "docs/design/v1.4.0-budget.md"
SEAL_DIR = "runs/sandbox_verification/final-v1.3.4"
GATE_TAGS = ("harness-v1.3.3", "harness-v1.3.4")
LEDGER = "$10.1349 [ESTIMATED: $9.8507 API-REPORTED + $0.2842 ESTIMATED], lower bound (D-27)"

ENTRY_CAP_USD = 2.00  # gate criterion (d)
CANDIDATES_PER_ROUND = 3  # directive, step 1.2
ROUNDS_PER_ENTRY = 3
# 9 candidate branches (disposable) + 3 non-disposable runs of the adjudicated winner, one per round.
BRANCH_RUNS_AT_CAP = CANDIDATES_PER_ROUND * ROUNDS_PER_ENTRY + ROUNDS_PER_ENTRY
SEAL_RUNS = 3
REPAIR_CALL_MIN_PROMPT_TOKENS = 1000  # separates the repairer's calls from the planner's (266-274 prompt tokens)

START = re.compile(r"^\[sandbox\] starting build\+execute \(wall_clock_seconds=(\d+)\)")
DONE = re.compile(r"^\[cost_guard\] recorded \$([\d.]+) sandbox spend")
KILLED = re.compile(r"^\[cost_guard\] operation stopped at (\d+)s; recorded \$([\d.]+) \(([\d.]+) measured")
VOID = re.compile(r"^\[integrity\] FAILED")
TORCH = re.compile(r"^\[runner\] torch: (.*)")
GATE_PASS = re.compile(r"^\[repair (\d+)\] tamper gate PASS")
KILL_NOTE = re.compile(r"^killed after (\d+)s: (.*)")

# The seal record that measured the same torch install chain (one install step + an import check), per entry.
SEAL_TORCH = {
    "03": "torch_py36_pin1.10.2.json",
    "08": "torch_py310_imports_torchvision.json",
    "11": "torch_py39_pin1.8.1_numpy_cap.json",
}
# Torch installs an entry needs when an environment is built once: the as-published environment and the era
# environment. Entry 8 has no era lock (fallback on the same base image, same "newest matched" rule): one.
ENVIRONMENTS_WITH_TORCH = {"03": 2, "07": 0, "08": 1, "11": 2}


@dataclass
class Op:
    n: int
    role: str
    funded_s: int
    start_i: int
    start_t: float
    torch: str | None = None
    torch_i: int | None = None
    outcome: str = "open"
    end_i: int | None = None
    end_t: float | None = None
    usd: float | None = None
    measured_usd: float | None = None
    install: str = "none"  # none | completed | killed | not reached

    @property
    def wall_s(self) -> float:
        return round(self.end_t - self.start_t, 1)


@dataclass
class Entry:
    record: Record
    ops: list[Op] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.record.harness_tag[len('harness-'):]} #{self.record.entry}"

    @property
    def guard(self) -> dict:
        return self.record.data["cost_guard"]

    def installs(self, state: str) -> int:
        return sum(1 for op in self.ops if op.install == state)


def parse_ops(record: Record) -> list[Op]:
    events = record.data["events"]
    notes = [KILL_NOTE.match(e["note"]) for e in record.data["cost_guard"]["cost_events"]]
    ops: list[Op] = []
    current: Op | None = None
    last_gate: str | None = None
    for i, event in enumerate(events):
        line = event["line"]
        if m := GATE_PASS.match(line):
            last_gate = f"repair {m.group(1)}"
        if m := START.match(line):
            if current is not None:
                raise ValueError(f"{record.path}: operation {current.n} never closed")
            role = "baseline" if not ops else (last_gate or "time machine")
            current = Op(len(ops) + 1, role, int(m.group(1)), i, event["t_s"])
            last_gate = None
            continue
        if current is None:
            continue
        if m := TORCH.match(line):
            current.torch, current.torch_i = m.group(1), i
            continue
        if m := DONE.match(line):
            current.outcome, current.usd = "completed", float(m.group(1))
            current.measured_usd = current.usd
        elif m := KILLED.match(line):
            current.outcome, current.usd, current.measured_usd = "killed", float(m.group(2)), float(m.group(3))
        elif VOID.match(line):
            current.outcome = "void"
        else:
            continue
        current.end_i, current.end_t = i, event["t_s"]
        if current.torch:
            if current.outcome == "completed":
                current.install = "completed"
            elif current.outcome == "void":
                current.install = "not reached"
            else:
                note = next(n for n in notes if n)
                current.install = "killed" if "pip install torch" in note.group(2) else "completed"
        ops.append(current)
        current = None
    if current is not None:
        raise ValueError(f"{record.path}: operation {current.n} never closed")
    return ops


def seal(name: str) -> dict:
    return json.loads((ROOT / SEAL_DIR / name).read_text(encoding="utf-8"))


def usd(v: float) -> str:
    return f"${v:.4f}"


def build() -> str:
    entries = [Entry(r, parse_ops(r)) for r in load_records() if r.harness_tag in GATE_TAGS]
    assert len(entries) == 8, len(entries)
    by = {(e.record.harness_tag, e.record.entry): e for e in entries}
    v134 = {k[1]: e for k, e in by.items() if k[0] == "harness-v1.3.4"}
    v133 = {k[1]: e for k, e in by.items() if k[0] == "harness-v1.3.3"}

    out: list[str] = []
    w = out.append
    w("# v1.4.0 budget note — Step 0, measured from records before any code")
    w("")
    w("Status: **estimate only**. Nothing here was run live; no Nebius call, no model call. Generated by")
    w("`python -m phase_d.budget_v140` from the committed records (`--check` fails if this file and the records disagree).")
    w("Tags: API-REPORTED (formerly MEASURED) = a stored record field; a dollar figure with this tag is the sandbox API's reported operation cost, not account billing (D-36, open);")
    w("DERIVED = parsed from a quoted record line or computed from API-REPORTED/DERIVED values (formula shown);")
    w("ESTIMATED = a cost-guard estimate, or a planning estimate made in this note.")
    w(f"Ledger: {LEDGER}. Nothing in Step 2 starts until the owner writes the new ceiling in chat.")
    w("")
    w("## Sources")
    w("")
    w("| Label | Record id |")
    w("|---|---|")
    for e in entries:
        w(f"| {e.label} | `{e.record.record_id}` |")
    w("")
    w(f"Seal records (worktree files, harness-v1.3.4 seal): `{SEAL_DIR}/`. `events[i]` below is `events[i].line` of the labelled record.")
    w("")
    w("What the records do and do not store:")
    w("- `cost_guard.cost_events` holds only killed-step estimates (2 [DERIVED: count] entries in the 8 records); it does not hold")
    w("  per-operation spend. Per-operation spend is DERIVED from the `[cost_guard] recorded $...` event lines.")
    w("- No record stores sandbox seconds or a per-step install duration. Operation wall seconds below are DERIVED as the")
    w("  difference of `events[].t_s` between the operation's start line and its cost line: client-side, including upload and polling.")
    w("- The directive's \"~90 s torch install\" is not a stored field and does not reproduce as an install duration. What the records give:")
    w("  whole baseline operations of the torch entries took "
      + ", ".join(f"{e.ops[0].wall_s} s" for e in entries if e.ops[0].torch)
      + " [each DERIVED, start/cost `t_s` of operation 1], and the one timed install step was killed after 33 s [DERIVED] without finishing")
    w("  (`cost_guard.cost_events[0].note` of v1.3.4 #08: `killed after 33s: pip install torch torchvision torchaudio --index-url https://download.pytorch.or`).")
    w("- Sandbox cost is not proportional to wall seconds: v1.3.4 #07 operation 1 cost "
      f"{usd(v134['07'].ops[0].usd)} [DERIVED] in {v134['07'].ops[0].wall_s} s [DERIVED]; v1.3.4 #11 operation 1 cost "
      f"{usd(v134['11'].ops[0].usd)} [DERIVED] in {v134['11'].ops[0].wall_s} s [DERIVED]. A seconds-based estimate would be wrong; this note estimates in dollars per operation.")
    w("")

    # ---- 1. split
    w("## 1. Spend split per entry: sandbox vs model")
    w("")
    w("Sandbox and model dollars are API-REPORTED fields (`cost_guard.sandbox_spent_usd`, `cost_guard.model_spent_usd`); the part of the sandbox figure that is a")
    w("killed-step estimate is `cost_guard.estimated_sandbox_spent_usd`. Tokens are DERIVED (sum of `cost_guard.model_usage[]`); model seconds are DERIVED (sum of `model_calls[].latency_s`).")
    w("")
    w("| Entry | Sandbox $ | of which estimate | Sandbox ops | Sandbox wall s | Model $ | Model share | Model calls | Prompt tokens | Completion tokens | Model s |")
    w("|---|---|---|---|---|---|---|---|---|---|---|")
    totals = {}
    for tag in GATE_TAGS:
        t = dict(sb=0.0, est=0.0, ops=0, wall=0.0, model=0.0, calls=0, pt=0, ct=0, lat=0.0)
        for e in entries:
            if e.record.harness_tag != tag:
                continue
            g = e.guard
            pt = sum(u["prompt_tokens"] for u in g["model_usage"])
            ct = sum(u["completion_tokens"] for u in g["model_usage"])
            lat = sum(c["latency_s"] or 0.0 for c in e.record.data["model_calls"])
            wall = sum(op.wall_s for op in e.ops)
            share = g["model_spent_usd"] / g["spent_usd"]
            w(f"| {e.label} | {usd(g['sandbox_spent_usd'])} | {usd(g['estimated_sandbox_spent_usd'])} | {len(e.ops)} | {wall:.1f} | "
              f"{usd(g['model_spent_usd'])} | {share:.1%} | {len(g['model_usage'])} | {pt} | {ct} | {lat:.1f} |")
            for k, v in (("sb", g["sandbox_spent_usd"]), ("est", g["estimated_sandbox_spent_usd"]), ("ops", len(e.ops)), ("wall", wall),
                         ("model", g["model_spent_usd"]), ("calls", len(g["model_usage"])), ("pt", pt), ("ct", ct), ("lat", lat)):
                t[k] += v
        totals[tag] = t
        w(f"| **{tag[len('harness-'):]} gate** | {usd(t['sb'])} | {usd(t['est'])} | {t['ops']} | {t['wall']:.1f} | {usd(t['model'])} | "
          f"{t['model'] / (t['model'] + t['sb']):.1%} | {t['calls']} | {t['pt']} | {t['ct']} | {t['lat']:.1f} |")
    both_sb = sum(t["sb"] for t in totals.values())
    both_model = sum(t["model"] for t in totals.values())
    w("")
    w(f"Both gates [DERIVED: sums of the rows above]: sandbox {usd(both_sb)}, model {usd(both_model)}, total {usd(both_sb + both_model)}; "
      f"the model is {both_model / (both_sb + both_model):.1%} of the spend. The gates were sandbox-bound, not token-bound.")
    w("One operation has no recorded cost at all: v1.3.3 #08 operation 3 was voided at the post-extraction check (D-20) and the record holds no spend line for it (D-27: the ledger is a lower bound).")
    w("")

    # ---- 2. operations
    w("## 2. Every sandbox operation, as recorded")
    w("")
    w("All values DERIVED from the quoted event indexes. \"Funded s\" is the wall clock the operation was started with.")
    w("")
    w("| Entry | Op | Role | Funded s | Wall s | Recorded $ | Torch install step | Outcome | Source |")
    w("|---|---|---|---|---|---|---|---|---|")
    for e in entries:
        for op in e.ops:
            cost = usd(op.usd) if op.usd is not None else "none recorded"
            if op.outcome == "killed" and op.usd != op.measured_usd:
                cost += f" ({usd(op.measured_usd)} API-reported + estimate)"
            src = f"`events[{op.start_i}]`" + (f", `[{op.torch_i}]`" if op.torch_i is not None else "") + f", `[{op.end_i}]`"
            w(f"| {e.label} | {op.n} | {op.role} | {op.funded_s} | {op.wall_s} | {cost} | {op.install} | {op.outcome} | {src} |")
    w("")

    # ---- 3. torch installs
    w("## 3. Torch installs per entry")
    w("")
    w("An install is counted when the operation's plan carries the runner's torch step (`[runner] torch: ...` line). \"Needed\" is the number of distinct")
    w("environments with torch the entry builds (as-published environment, era environment), i.e. what \"install once per environment\" would pay.")
    w("The reinstall dollar figure is ESTIMATED: repeated completed installs x the seal-reported cost of the same install chain; a killed install counts at its recorded estimate.")
    w("")
    w("| Entry | Started | Completed | Killed mid-install | Not reached | Needed | Repeats | Seal cost of one install chain | Reinstall spend |")
    w("|---|---|---|---|---|---|---|---|---|")
    reinstall_total = {}
    for tag in GATE_TAGS:
        reinstall_total[tag] = 0.0
        for e in entries:
            if e.record.harness_tag != tag:
                continue
            started = sum(1 for op in e.ops if op.torch)
            comp, killed, nr = e.installs("completed"), e.installs("killed"), e.installs("not reached")
            needed = ENVIRONMENTS_WITH_TORCH[e.record.entry]
            repeats = max(comp - needed, 0)
            if started:
                chain = seal(SEAL_TORCH[e.record.entry])["cost_usd"]
                re_usd = repeats * chain + (e.guard["estimated_sandbox_spent_usd"] if killed else 0.0)
                chain_s = f"{usd(chain)} [API-REPORTED, `{SEAL_TORCH[e.record.entry]}`.cost_usd]"
            else:
                re_usd, chain_s = 0.0, "n/a (no torch)"
            reinstall_total[tag] += re_usd
            w(f"| {e.label} | {started} | {comp} | {killed} | {nr} | {needed} | {repeats + killed} | {chain_s} | {usd(re_usd)} [ESTIMATED] |")
    n_started = sum(1 for e in entries for op in e.ops if op.torch)
    n_comp = sum(e.installs("completed") for e in entries)
    w("")
    w(f"Totals [DERIVED: counts over section 2]: {n_started} torch install steps started, {n_comp} completed, "
      f"{sum(e.installs('killed') for e in entries)} killed mid-install, {sum(e.installs('not reached') for e in entries)} not reached. "
      f"Reinstall spend: v1.3.3 {usd(reinstall_total[GATE_TAGS[0]])}, v1.3.4 {usd(reinstall_total[GATE_TAGS[1]])} [ESTIMATED], "
      f"i.e. {reinstall_total[GATE_TAGS[1]] / (totals[GATE_TAGS[1]]['sb'] + totals[GATE_TAGS[1]]['model']):.0%} [ESTIMATED] of the v1.3.4 gate spend.")
    w("")
    w("Findings the owner should see before pre-registering the gate:")
    w("1. **Which losses the records attribute to rebuilding.** Two of the four v1.3.4 losses ended `COST_CAP` in or after a repeated install: #08 (operation 2 killed 33 s into the torch install) and")
    w("   #11 (operation 4, a gate-approved patch, stopped at 119 s). #03 ended `BLOCKED` on a silent exit 1 (D-25) with $0.7911 [DERIVED, `events[42]` of v1.3.4 #03] unspent, and #07 ended `BLOCKED`")
    w("   `DEP_NOT_ON_PYPI` with no torch at all. The directive's \"three of the four\" does not reproduce from the records; two does.")
    w("2. **#08 was also starved by the gate cap, not only by the reinstall.** Its entry cap was "
      f"${v134['08'].record.data['batch']['per_entry_cap_usd']} [API-REPORTED, `batch.per_entry_cap_usd`] because it ran last and inherited what was left of the "
      f"${v134['08'].record.data['batch']['total_cap_usd']} [API-REPORTED] gate cap. In v1.3.3 the same two operations cost "
      f"{usd(v133['08'].ops[0].usd)} + {usd(v133['08'].ops[1].usd)} [DERIVED]. A gate cap below 4 x the expected entry spend reproduces this whatever the harness does.")
    w("3. **Criterion (e) as written cannot pass for #03 and #11.** The baseline runs the as-published environment (planner image, newest matched torch) and the time machine builds a different one")
    w("   (era Python, pinned torch): `events[7]` vs `events[19]` of v1.3.4 #03, `events[7]` vs `events[17]` of v1.3.4 #11. That is two torch installs per entry by design. Either (e) reads")
    w("   \"at most once per environment image\", or the baseline is excluded from the count. Decision needed before sealing.")
    w("4. **The CPU wheel index is already the behaviour.** Every recorded torch install uses `--index-url https://download.pytorch.org/whl/cpu` (`install_command` of the seal torch records). In step 1.3 only \"measure install seconds and record them\" is new.")
    w("5. **The harness already retains images inside one operation** (`backend/app/services/sandbox.py`, `_run_once`: each non-final step runs `disposable=False`, and every retained image is disposed in `finally`).")
    w("   The defect is that nothing survives from one operation to the next. The installed SDK can reopen an image by UUID (`contree_sdk/sdk/managers/images/_base.py`, `pull(url_or_tag_or_uuid)`); whether a retained image is billed while it is kept is in no record and must be measured in the seal.")
    w("")

    # ---- 4. estimate
    smoke = {p.name: json.loads(p.read_text(encoding="utf-8"))["cost_usd"] for p in sorted((ROOT / SEAL_DIR).glob("smoke_*.json"))}
    r_low = max(smoke.values())
    r_low_src = max(smoke, key=smoke.get)
    repair_calls = [u["cost_usd"] for e in entries for u in e.guard["model_usage"]
                    if "super" in u["model"] and u["prompt_tokens"] >= REPAIR_CALL_MIN_PROMPT_TOKENS]
    ultra_calls = [u["cost_usd"] for e in entries for u in e.guard["model_usage"] if "Ultra" in u["model"]]
    c_mean, c_max, u_max = sum(repair_calls) / len(repair_calls), max(repair_calls), max(ultra_calls)

    w("## 4. Estimated cost of a v1.4.0 gate under \"install once, branch per attempt\"")
    w("")
    w("Everything in this section is ESTIMATED; the inputs are API-REPORTED or DERIVED and named. Per entry:")
    w("")
    w("`entry = A + B + n x R + model`")
    w("- **A**, the as-published baseline operation: its recorded cost in v1.3.4 (operation 1).")
    w("- **B**, the checkpoint build (era lock + dependency install + first re-execution, run non-disposable, giving `env_image_id`): the recorded cost of operation 2 in v1.3.4; for #08, whose operation 2 was killed, the completed operation 2 of v1.3.3.")
    w("- **R**, one branch run from `env_image_id` (apply one candidate, smoke run of at most 60 s). **No record measures this**; it is the number the seal has to produce. Two bounds:")
    w(f"  - R-low = {usd(r_low)} [API-REPORTED, `{r_low_src}`.cost_usd]: the dearest smoke run on a ready image in the v1.3.4 seal (commands that do almost no work).")
    w("  - R-high, per entry = the entry's dearest re-execution minus the seal-reported torch chain. It still contains the non-torch installs and the repository download, which a branch does not repeat, so it is an upper bound. For #07 (no torch; its repairs were environment changes) no saving is assumed: R-high is its dearest repair operation.")
    w(f"- **n**: \"same sequence\" = the re-executions v1.3.4 actually made after operation 2; \"at cap\" = {BRANCH_RUNS_AT_CAP} [DERIVED: {CANDIDATES_PER_ROUND} candidates x {ROUNDS_PER_ENTRY} rounds + {ROUNDS_PER_ENTRY} non-disposable runs of the adjudicated winner].")
    w(f"- **model**: \"same sequence\" = the entry's recorded model spend; \"at cap\" = the entry's non-repair calls as recorded + {CANDIDATES_PER_ROUND * ROUNDS_PER_ENTRY} candidates + {ROUNDS_PER_ENTRY} Ultra adjudications, "
      f"a candidate priced at the mean {usd(c_mean)} (low) or the maximum {usd(c_max)} (high) of the {len(repair_calls)} recorded repairer calls, an adjudication at {usd(3 * u_max)} "
      f"[ESTIMATED: 3 x the dearest recorded Ultra call {usd(u_max)}, for three diffs in the prompt].")
    w(f"- Every entry is clipped at the ${ENTRY_CAP_USD:.2f} entry cap of criterion (d) [API-REPORTED as `batch.per_entry_cap_usd` of v1.3.4 #11].")
    w("")
    w("| Entry | A | B | R-high | n same | Same sequence low | Same sequence high | At cap low | At cap high | v1.3.4 actual |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    tot = dict(sl=0.0, sh=0.0, cl=0.0, ch=0.0, actual=0.0)
    for entry_id in ("03", "07", "08", "11"):
        e = v134[entry_id]
        a = e.ops[0].usd
        b_op = e.ops[1] if e.ops[1].outcome == "completed" else v133[entry_id].ops[1]
        b = b_op.usd
        b_src = "v1.3.4 op 2" if b_op is e.ops[1] else "v1.3.3 op 2"
        later = [op for src in (e, v133[entry_id]) for op in src.ops[1:] if op.outcome == "completed"]
        dearest = max(op.usd for op in later)
        if entry_id in SEAL_TORCH:
            chain = seal(SEAL_TORCH[entry_id])["cost_usd"]
            r_high = dearest - chain
            r_src = f"{usd(dearest)} - {usd(chain)}"
        else:
            r_high, r_src = dearest, "dearest repair op"
        n_same = max(len(e.ops) - 2, 0)
        g = e.guard
        fixed_model = sum(u["cost_usd"] for u in g["model_usage"]
                          if not ("super" in u["model"] and u["prompt_tokens"] >= REPAIR_CALL_MIN_PROMPT_TOKENS))
        cap_n = CANDIDATES_PER_ROUND * ROUNDS_PER_ENTRY
        model_low = fixed_model + cap_n * c_mean + ROUNDS_PER_ENTRY * 3 * u_max
        model_high = fixed_model + cap_n * c_max + ROUNDS_PER_ENTRY * 3 * u_max
        sl = min(a + b + n_same * r_low + g["model_spent_usd"], ENTRY_CAP_USD)
        sh = min(a + b + n_same * r_high + g["model_spent_usd"], ENTRY_CAP_USD)
        cl = min(a + b + BRANCH_RUNS_AT_CAP * r_low + model_low, ENTRY_CAP_USD)
        ch = min(a + b + BRANCH_RUNS_AT_CAP * r_high + model_high, ENTRY_CAP_USD)
        actual = g["spent_usd"]
        for k, v in (("sl", sl), ("sh", sh), ("cl", cl), ("ch", ch), ("actual", actual)):
            tot[k] += v
        w(f"| #{entry_id} | {usd(a)} | {usd(b)} ({b_src}) | {usd(r_high)} ({r_src}) | {n_same} | {usd(sl)} | {usd(sh)} | {usd(cl)} | {usd(ch)}"
          f"{' (clipped)' if ch == ENTRY_CAP_USD else ''} | {usd(actual)} |")
    w(f"| **Gate** | | | | | {usd(tot['sl'])} | {usd(tot['sh'])} | {usd(tot['cl'])} | {usd(tot['ch'])} | {usd(tot['actual'])} |")
    w("")
    w("A and B are DERIVED from section 2; \"v1.3.4 actual\" is API-REPORTED (`cost_guard.spent_usd`, #08 including its $0.2842 estimate); every other cell is ESTIMATED.")
    w("")
    seal_torch_11 = seal(SEAL_TORCH["11"])["cost_usd"]
    dearest_any = max(op.usd for e in entries for op in e.ops if op.usd is not None)
    seal_low = seal_torch_11 + (SEAL_RUNS - 1) * r_low
    seal_high = SEAL_RUNS * dearest_any
    w(f"**Seal** (at most {SEAL_RUNS} live runs: one checkpoint build kept as an image, one disposable branch from it, one non-disposable branch): "
      f"low {usd(seal_low)} [ESTIMATED: one torch chain {usd(seal_torch_11)} + {SEAL_RUNS - 1} x R-low], "
      f"high {usd(seal_high)} [ESTIMATED: {SEAL_RUNS} x the dearest operation on record, {usd(dearest_any)}].")
    w("")
    w("**Seal + gate** [ESTIMATED: sums of the rows above]:")
    w("")
    w("| Scenario | Seal | Gate | Total | Ledger after |")
    w("|---|---|---|---|---|")
    ledger = 10.1349
    hard = SEAL_RUNS * dearest_any + 4 * ENTRY_CAP_USD
    for name, s, gt in (("Same sequence, low", seal_low, tot["sl"]), ("Same sequence, high", seal_high, tot["sh"]),
                        ("At cap, low", seal_low, tot["cl"]), ("At cap, high", seal_high, tot["ch"])):
        w(f"| {name} | {usd(s)} | {usd(gt)} | {usd(s + gt)} | {usd(ledger + s + gt)} |")
    w(f"| Hard worst case (every entry at ${ENTRY_CAP_USD:.2f}) | {usd(seal_high)} | {usd(4 * ENTRY_CAP_USD)} | {usd(hard)} | {usd(ledger + hard)} |")
    w("")
    w("Reading:")
    w(f"- The spread between low and high is almost entirely R. If a branch run costs what a smoke run on a ready image cost in the seal, a full 3 x 3 gate ({BRANCH_RUNS_AT_CAP} branch runs per entry) costs {usd(tot['cl'])} [ESTIMATED], below the {usd(tot['actual'])} [ESTIMATED: $3.1120 API-REPORTED + $0.2842 ESTIMATED] v1.3.4 spent. If R is near its upper bound, #07, #08 and #11 reach the entry cap.")
    w("- A and B are not reduced by branching: they are paid once per entry in every scenario (" + usd(sum(v134[k].ops[0].usd for k in v134) + sum((v134[k].ops[1] if v134[k].ops[1].outcome == 'completed' else v133[k].ops[1]).usd for k in v134))
      + " [DERIVED: sum of the A and B columns] for the four entries). That is the floor of the gate.")
    w("- The first seal run should measure R and the cost (if any) of keeping an image; the gate cap can then be set from a measured R instead of this range.")
    w("- The gate cap must cover 4 x the entry cap, or the entries run last inherit a smaller cap (finding 2).")
    w("")
    w("## 5. Owner decisions on this note (2026-10-01), recorded as annotations")
    w("")
    w("Accepted corrections (the records win; the directive's wording is kept beside them, never edited in place):")
    w("- \"Three of the four v1.3.4 gate losses\" reads **two of four** were install-bound (#08, #11); #03 is the silent exit (D-25), #07 had no torch (finding 1).")
    w("- The \"~90 s torch install\" figure is in no record and is **withdrawn** (also annotated in `docs/design/D-23.md`).")
    w("- The CPU wheel index is **already in use** for every recorded torch install (finding 4); v1.4.0 only adds the install seconds as a stored field.")
    w("- Images **already persist within an operation**; the defect is that none survives to the next operation (finding 5).")
    w("")
    w("Decisions:")
    w("1. The ceiling is a **seal + gate cap**, not a ledger ceiling. Proposed shape: seal at most $1.50 [ESTIMATED: owner's proposal], gate at most $5.00 with an entry cap of")
    w("   $1.25 each [ESTIMATED: owner's proposal], so gate >= 4 x entry and no entry inherits a starved cap. The figure is the owner's to write in chat; nothing live starts before it.")
    w("2. Criterion (e) reads: **torch installed at most once per environment image**, checkable from the records; the planner-image baseline install is counted separately and is outside (e).")
    w("3. Step 1 (offline, `harness-v1.4.0-rc`) starts now, ordered by entry: #11 CPU shim + checkpoint persistence; #08 checkpoint persistence + a fixed entry cap; #07 D-24 (already in);")
    w("   #03 the D-25 exit-site hook; then the parallel-candidate repair (3 x 3 cap).")
    w("")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    text = build()
    path = ROOT / OUT
    if "--check" in argv:
        current = path.read_text(encoding="utf-8").replace("\r\n", "\n") if path.exists() else ""
        if current != text:
            print(f"{OUT} does not match the records; run python -m phase_d.budget_v140")
            return 1
        print(f"{OUT} matches the records")
        return 0
    path.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
