# RERUN — MASTER BUILD DIRECTIVE (Full-Autonomy Edition)
### For: Claude Code (or any coding agent) — Nebius x NVIDIA Global AI Hackathon
### Deadline: submit by **Oct 28, 2026** (hard internal deadline; official cutoff Oct 30, 10:00am PDT)
### Track: Coding and Agentic Engineering + Best Use of Tavily ($3,000)

---

## 0. OPERATING MODE — READ THIS FIRST

You are not a coding assistant waiting for instructions. You are the **lead engineer**
executing a fully-specified mission. Operate accordingly:

- **You have full authority to decide and act.** Do not pause to ask the human questions
  about anything reversible — library choices, file layout, wording, minor scope
  trade-offs inside a phase, test design, refactors. Decide, act, log the decision, move on.
- **Never ask permission for a new dependency.** Add what you need. Log it (name, version,
  one-line justification) in `DECISIONS.md`. Prefer boring, maintained, widely-used
  libraries over cleverness.
- **Only stop and surface a question to the human if one of these is true:**
  1. A choice is destructive/irreversible (deleting committed work, force-pushing,
     rewriting git history).
  2. Real money would be spent beyond the cost guard defined in §9.
  3. The tamper gate or the batch corpus (the two "never cut" items in §3) cannot be
     built as specified and you believe the entire differentiator is at risk — this is
     the one category of scope problem worth interrupting for, because it changes
     whether this project is worth submitting at all.
  4. You discover the hackathon rules, deadline, or eligibility have materially changed
     from what is stated here (verify by fetching the devpost page directly before
     concluding this).
  Everything else: your call. Make it, write it down, keep moving.
- **Never report "done" without a command the human can run themselves to verify it.**
  Every phase gate below ends in an exact command and its expected output. If you find
  yourself writing "this should work" — it means you haven't run it. Run it.
- **Never make a test pass by weakening the test, the ground truth, or the tamper gate.**
  If a check fails, the code is wrong, not the check. This applies with zero exceptions
  to `tamper_gate.py` and the batch corpus (`corpus.yaml` / `batch_results.json`).
- **Never fake a result.** No hardcoded "success" outputs, no placeholder metrics
  presented as real, no silently-skipped repos hidden from the batch count. If something
  doesn't work, the taxonomy/verdict system exists precisely to say so honestly — use it.
- **Commit after every green gate.** Small, real commits with messages that state what
  was verified, not just what was written.
- **Log every non-trivial decision** in `DECISIONS.md` at repo root: what you chose, what
  you rejected, why. This file is how the human audits your judgment after the fact
  instead of during the build — that is the whole point of full autonomy.

---

## 1. PRODUCT DEFINITION

**One sentence:** RERUN takes a published paper's code repository, rebuilds its
environment from scratch inside an isolated Nebius Token Factory Sandbox, actually runs
it, issues an evidence-backed reproducibility verdict, and — when it can — proposes a
minimal patch that is verified by a deterministic **tamper gate** before it is ever
accepted, so the reported result is never a repair the model faked by making the code do
less.

**Why it matters (say this, it's real):** in one ecology-journal audit, only 28% of
papers released code and data at all, and only 7% shipped code that ran without errors.
When AI agents were benchmarked reproducing paper code from a clean machine, the best
system reached 54.1% in the friendliest domain and 24.4% on the harder PaperBench
benchmark — and the documented failure wall was **environments and dependencies, not
coding ability**. That is exactly the shape of problem a sandbox-native agent should own.

**The differentiator (this is what you are building, not decoration around it):**
several academic systems attempt automated repro repair. None of them ship a
deterministic gate that refuses to accept a "fix" that passes by deleting the
experiment, stubbing the model call, shrinking the dataset, or swallowing the error.
RERUN's entire credibility rests on `tamper_gate.py`. Treat it as the spine of the
project, not a feature.

**Scope boundary (state this honestly everywhere — README, UI, video):** RERUN verifies
that the artifact **executes** (`SMOKE` level: exit code 0 + non-trivial output/stdout).
It does **not** verify that the paper's numerical results are reproduced. Never let the
UI or the pitch imply otherwise.

---

## 2. NON-NEGOTIABLE ENGINEERING RULES

1. `tamper_gate.py` and `classifier.py` are **pure, deterministic, no network, no model
   call**. If you ever find yourself wanting an LLM call inside either, stop — that is a
   design violation, not a shortcut.
2. `tamper_gate.py` ships with a pytest suite containing at least one **negative
   control** per rejection rule (see §5.3) — a patch that *should* be rejected, asserted
   to actually be rejected. A gate whose tests only check acceptance is not tested.
3. The Batch Lab corpus (`corpus.yaml`, §7) and its results (`batch_results.json`) are
   the project's ground truth / decisive gate. **Never shrink silently.** If time forces
   a cut, shrink the corpus count explicitly and report the real N everywhere it's shown
   — an honest N=10 beats a fabricated N=20.
4. Read the actual installed library source/docs when unsure of an API. Never invent a
   method signature and hope.
5. Read-only on every external target: cloning public repos is fine; never push to,
   authenticate against, or modify anything outside your own sandbox/repo.
6. Every sandbox session must be destroyed after use, success or failure — no leaked
   Token Factory resources. Enforce this with a `finally`/context-manager, not
   discipline.
7. Fixed stack (§6) — do not renegotiate mid-build. If a library in §6 turns out to be
   wrong, log why in `DECISIONS.md` and pick the closest boring alternative; don't drift
   into a framework rewrite.
8. Anti-goals — RERUN explicitly does **not**: train or fine-tune a model, support
   non-Python repos in v1, verify numerical correctness against the paper, require GPU
   in the sandbox, or use any agent framework (LangChain, etc.) — the repair loop must
   be explicit code the judges can read, not hidden inside a framework abstraction.

---

## 3. SCOPE LADDER

**Must-have (the project is not RERUN without these — never cut):**
1. Repo intake + recon (clone, parse README/`requirements.txt`/`setup.py`/
   `environment.yml`/notebooks; Nemotron Nano extracts entrypoint, Python version, deps,
   data requirements)
2. Environment synthesis — an explicit, inspectable **build plan** produced before
   anything executes
3. Sandboxed execution in a Nebius Token Factory Sandbox with hard limits (wall clock,
   no interactive input, streamed logs)
4. Deterministic failure taxonomy (§5.2) — classification from exit code + stderr, zero
   model calls
5. Bounded repair loop — max 3 attempts, Nemotron Super proposes a **minimal diff**
6. **Tamper gate** (§5.3) — the differentiator, never cut
7. Verdict + certificate (§8, S3) — every claim traceable to a real log line
8. Batch Lab — 20 real published repos run in parallel via Nebius Serverless Jobs,
   producing a measured reproducibility rate (§7)

**Should-have (build if the must-haves are green with time to spare):**
- Patch export (`.patch` file that applies cleanly with `git apply` on a fresh clone)
- Tavily-sourced context injected into the repair prompt, cited in the certificate
- Adjudicator prose polish (Nemotron Ultra)
- The three enhancements in §6 (Recovery Rate headline metric, Reproduction Passport,
  Indeterminate verdict state) — these are should-have in priority but **treat them as
  must-have for competitiveness**: they are cheap to build (mostly presentation +
  hashing, no new infra) and they directly answer the "is this just a wrapper" and "how
  do I trust this number" judge questions. Build them inside Phase 3–4, not as a
  stretch tacked on at the end.

**Cut ladder (in this order, if the 46-day budget is under real pressure):**
1. Adjudicator prose polish → fall back to templated certificate text
2. Tavily-cited repair context → repair without external context (still functions)
3. Patch export UI polish → keep the raw diff visible, drop the download button
4. Shrink batch corpus from 20 → 10, **reported honestly**, never silently
- **Never on this ladder:** the tamper gate, the classifier, the corpus itself (as a
  concept — its *size* may shrink per the rule above, its *existence* may not), and the
  three §6 enhancements once started (half-built calibration or an unsigned "signed"
  passport is worse than not claiming it).

**Decisive gate:** the Batch Lab (Phase 4, day 29–37). If this is not green by roughly
day 30 (~65% of the schedule), stop all other work and put every remaining hour here.
Without a measured number, RERUN is an anecdote, not a product.

---

## 4. ARCHITECTURE

```
Browser (React/Vite/Tailwind — timeline, logs, diffs)
   │ POST /runs · SSE /runs/{id}/stream
   ▼
FastAPI orchestrator
   ├─ intake ──────────────── shallow clone (GitHub)
   ├─ recon ────────────────► Nemotron 3 Nano    ┐
   ├─ planner ──────────────► Nemotron 3 Super   │  Nebius Token Factory
   ├─ sandbox ──────────────► Token Factory Sandbox
   │     create → upload → install → execute → stream logs → destroy (always)
   │                     │
   │                     ▼ exit code + stderr
   ├─ classifier    (PURE deterministic — taxonomy code, §5.2)
   │                     │
   │                     ▼ failure (or INDETERMINATE, §6.1)
   ├─ context ──────────────► Tavily (cited dependency evidence)
   ├─ repairer ─────────────► Nemotron 3 Super   (minimal diff)
   │                     │
   │                     ▼ diff
   ├─ tamper_gate   (PURE deterministic — diff + AST → PASS/REJECT, §5.3)
   │        PASS   → apply, re-execute (max 3 attempts total)
   │        REJECT → record violation, ask model for a different fix
   ├─ adjudicator ──────────► Nemotron 3 Ultra   (certificate prose; may only downgrade)
   ├─ passport ──────────────  SHA-256 sign the final certificate bundle (§6.3)
   └─ store (SQLite)

Offline: batch runner ──► Nebius Serverless Jobs (20 repos in parallel)
                              └─► batch_results.json (committed) ──► S4 Batch Lab
Hosting: Nebius Serverless Endpoints
```

### 4.1 Tech stack (fixed — do not renegotiate)

| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.11 + FastAPI | Async orchestration of sandbox + model calls; SSE; fastest solo path |
| DB | SQLite + SQLAlchemy | Single tenant; zero ops |
| Frontend | React + Vite + Tailwind | Custom timeline/log/diff UI anyway; no heavy kit needed |
| Diff/AST | `unidiff` + `libcst` (or `ast`) | Tamper gate must not be regex-only |
| Data fetch | TanStack Query | Polling fallback for free |
| Tests | `pytest` | Classifier + gate are pure and MUST have real tests — also a judging signal |
| Deploy | Docker + Compose → Nebius Serverless Endpoints | Reproducible setup (a reproducibility tool with an irreproducible README is an own goal) |
| Reasoning | Nemotron 3 Nano (recon) / Super (planning + repair) / Ultra (adjudication) via Token Factory | Task-routed, not one model doing everything — this is what "non-obvious use" means in the rubric |
| Live evidence | Tavily | Runtime-called, cited in the certificate — required for Best Use of Tavily |
| Batch compute | Nebius Serverless Jobs | 20 repos in parallel |

**Deliberately excluded:** LangChain/agent frameworks, a vector DB, any auth provider.

### 4.2 Repo structure

```
rerun/
├── README.md              # setup + explicit Nemotron/Token Factory/Sandboxes/Jobs usage
├── LICENSE                # Apache-2.0, visible at repo top (hackathon requirement)
├── DECISIONS.md           # running log of every autonomous decision made during build
├── docker-compose.yml · .env.example
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py · config.py · models.py · schemas.py
│   │   ├── routers/  repos.py  runs.py  batch.py  health.py
│   │   ├── services/
│   │   │   ├── intake.py
│   │   │   ├── recon.py
│   │   │   ├── planner.py
│   │   │   ├── sandbox.py         # Token Factory lifecycle; always destroys
│   │   │   ├── classifier.py      # PURE. no network, no model
│   │   │   ├── repairer.py
│   │   │   ├── tamper_gate.py     # PURE. the differentiator
│   │   │   ├── adjudicator.py
│   │   │   ├── passport.py        # SHA-256 signing, §6.3
│   │   │   └── cost_guard.py      # §9
│   │   └── batch/ corpus.yaml  runner.py
│   └── tests/  test_classifier.py  test_tamper_gate.py  test_passport.py  ...
├── frontend/  (Vite + React + Tailwind, screens S1–S4 per §8)
├── batch_results.json       # committed, precomputed — the S4 payload
├── METHODOLOGY.md           # corpus selection criteria + limitations, honestly stated
└── docs/
    └── demo_script.md       # §10, exact timing
```

---

## 5. CORE MECHANICS

### 5.1 Verdict grades

| Verdict | Meaning |
|---|---|
| `RUNS_CLEAN` | Built and executed successfully, zero patches |
| `RUNS_AFTER_REPAIR` | Executed successfully after N gate-approved patches (N reported) |
| `BLOCKED` | Failed after 3 attempts, with a taxonomy code explaining why |
| `INDETERMINATE` | See §6.1 — insufficient evidence to attempt or classify confidently |
| `NOT_ATTEMPTABLE` | No runnable code / non-Python / requires credentials, paid data, or GPU beyond limits |
| `TIMEOUT` | Exceeded wall-clock ceiling |

### 5.2 Failure taxonomy (deterministic — rule-based, no model call)

| Code | Family | Detection signal |
|---|---|---|
| `DEP_UNPINNED_CONFLICT` | Dependencies | pip resolver conflict / version solving failure |
| `DEP_MISSING` | Dependencies | `ModuleNotFoundError` for a package absent from declared deps |
| `DEP_YANKED_GONE` | Dependencies | package/version no longer on the index (404 from PyPI) |
| `PY_VERSION_INCOMPAT` | Environment | syntax/ABI errors tied to unsupported interpreter version |
| `SYS_LIB_MISSING` | Environment | linker/shared-object errors requiring an `apt` package |
| `DATA_MISSING` | Data | `FileNotFoundError` / dead data URL / unshipped local path |
| `DATA_CREDENTIALS` | Data | requires API key, login, or licensed dataset |
| `ENTRYPOINT_UNCLEAR` | Documentation | no runnable entrypoint discoverable in recon → feeds `INDETERMINATE`, §6.1 |
| `HARDCODED_PATH` | Code | absolute path from author's machine |
| `GPU_REQUIRED` | Resources | CUDA device assertions on a CPU sandbox |
| `NETWORK_BLOCKED` | Environment | outbound call to a host the sandbox policy denies |
| `RUNTIME_ERROR_OTHER` | Code | non-zero exit matching no rule above — must stay a small %; if it dominates, add rules |

### 5.3 The tamper gate — exact rejection rules

Every model-proposed patch is checked **before** application. Deterministic, AST- and
diff-based. Any violation → REJECT; the attempt is recorded and the loop asks the model
for a different fix (still counts toward the 3-attempt ceiling).

Reject a diff if it:
- Deletes or comments out a call to the evaluation/metric/assertion function identified
  during recon
- Replaces a real model/inference call with a stub, mock, or hardcoded return value
- Reduces dataset size, epoch count, or sample count from what the repo declares as its
  default, unless the *original* code already parameterizes this and the patch only
  restores a broken default
- Swallows an exception broadly (bare `except:`/`except Exception: pass`) around code
  that was previously expected to run to completion
- Modifies the taxonomy classifier, the gate itself, the corpus, or any test file — a
  patch is only ever applied to the target repo's own code
- Touches more than a bounded diff-size ceiling (e.g. >40 changed lines) without a clear
  single-cause justification — large diffs are a smell for "rewrote around the problem"

Each rule needs its own pytest **negative control**: construct a patch that should
trigger it, assert `REJECT`, assert the reason string names the specific rule.

### 5.4 Repair loop

Max 3 attempts total. Each attempt: Nemotron Super proposes a minimal diff → tamper
gate checks it → PASS: apply + re-execute; REJECT: record + ask again (still consumes
an attempt). After 3 attempts with no clean run → `BLOCKED` with the taxonomy code from
the most recent failure.

---

## 6. THE THREE ENHANCEMENTS TO BUILD IN (from the strategy review — build these, they are cheap and they close real judging gaps)

### 6.1 Calibrated abstention — the `INDETERMINATE` verdict

Do not let recon silently guess an entrypoint it isn't confident about and then blame a
downstream execution failure on the code. If recon (Nemotron Nano) cannot identify a
runnable entrypoint with reasonable confidence, or the repo's declared dependencies are
too ambiguous to build a build plan at all, the run terminates immediately as
`INDETERMINATE` — not `BLOCKED`. The certificate must show *why* (e.g. "no entrypoint
found: candidates were `train.py`, `run_experiment.py`, `main.py` — README does not
specify"), and must **not** count against the repo as a `RUNTIME_ERROR_OTHER` or any
executed-and-failed state, because nothing was actually attempted. This protects the
Batch Lab number from being inflated with false failures and protects a legitimate
repo's reputation from a bad verdict caused by RERUN's own uncertainty, not the repo's
quality.

### 6.2 Quantified impact metric — Reproducibility Recovery Rate

On the Batch Lab (S4), add one headline number above the existing breakdown:

```
Reproducibility Recovery Rate = (RUNS_CLEAN + RUNS_AFTER_REPAIR) / N
```

Show it as a single large stat plus the raw counts it's built from (never present a
percentage without the N it came from). Alongside it, add a clearly-labeled **estimate**
(not a measured claim):

```
Estimated researcher-hours saved ≈ (RUNS_AFTER_REPAIR count) × (avg manual
debug-time assumption, stated explicitly, e.g. 2–4 hrs/repo, cited or reasoned)
```

Label this line "Estimate — not measured" directly in the UI, in the same visual weight
as the number itself. This is the pattern that makes a number memorable to judges
without crossing into an unverifiable claim — exactly the discipline your existing
methodology already requires (quantify, never assert).

### 6.3 Reproduction Passport — signed certificate

Extend the S3 certificate: on verdict finalization, compute a SHA-256 hash over a
canonical bundle (build plan + full log + every applied/rejected diff + verdict +
timestamp) and display it as the **Reproduction Passport hash**. Ship a tiny standalone
verifier script (`scripts/verify_passport.py`) that recomputes the hash from a
downloaded certificate JSON and confirms it matches — so a judge or a reviewer can
verify the artifact wasn't altered after the fact, independent of trusting RERUN's own
UI. This turns the certificate from "text the app shows you" into an auditable
artifact — directly answers the "why should I trust this" judge question.

---

## 7. THE BATCH LAB CORPUS

- `corpus.yaml`: 20 real, publicly available paper repositories, Python, with a
  declared dependency file. Prefer repos spanning multiple failure modes (some clean,
  some genuinely broken) — a corpus that's all clean or all broken proves nothing.
- Runs via Nebius Serverless Jobs in parallel; output committed as `batch_results.json`
  (verdict, taxonomy code, repairs applied/rejected, timing per repo).
- `METHODOLOGY.md` documents: how the 20 were selected, any selection bias, what
  `SMOKE`-level reproduction does and does not prove, and the honest N if it had to
  shrink per the cut ladder.
- **Never render a zero or a placeholder if `batch_results.json` is missing — fail
  loudly in the UI instead.** A missing artifact must never silently become a fake 0%.

---

## 8. UI SPEC — screens S1 through S4

**S1 — Intake**
Paste a GitHub URL → validate (public? Python detected?) → error states each with a
distinct, specific message (private repo / not Python / no code found) → success → S2.

**S2 — Run timeline (the live screen)**
Vertical stage timeline: `Recon → Build plan → Sandbox created → Install → Execute →
Failure: <code> (or Indeterminate: <reason>) → Repair attempt 1/3 → Tamper gate:
PASS/REJECT → Re-execute → Verdict`. Each stage expands to real output (install log
tail, stderr excerpt, proposed diff). Live sandbox badge (id, elapsed time, wall-clock
remaining). **A tamper-gate REJECT must be visually loud** — a distinct, differently
colored card ("rejected patch — it deleted the evaluation call") — this is the moment
that separates RERUN from every other repair agent; if it's buried in a log, the whole
differentiator is invisible to a judge skimming the demo.

**S3 — Certificate**
Verdict badge · repo + commit SHA + timestamp · build plan as generated · failure
taxonomy chips (or Indeterminate reason) · applied patches (syntax-highlighted unified
diff) · rejected patches with reason · full log download · "Export patch" button ·
**Reproduction Passport hash + "Verify" instructions** (§6.3) · the fixed honest scope
line: *"Verifies that the artifact executes. Does not verify the paper's numerical
results."*

**S4 — Batch Lab (the wow screen)**
Headline: **Reproducibility Recovery Rate** (§6.2) with its N. Below it: N repos · X ran
clean · Y ran after repair · Z blocked · W indeterminate · median time-to-first-failure
· estimated researcher-hours saved (clearly labeled estimate). Failure-breakdown bar
chart by taxonomy code (the scientific payload — shows *what* actually breaks). Table
of all repos → click a row → the frozen S3 certificate. Loads a precomputed
`batch_results.json`; fails loudly if missing.

---

## 9. COST GUARD & DEMO_MODE

- Hard daily cost ceiling on model + sandbox spend; per-run token/attempt caps enforced
  in `cost_guard.py`, not just documented.
- `DEMO_MODE`: recorded fixtures for at least one guaranteed-clean and one
  guaranteed-repair-then-pass repo, so the live demo never depends on network/model
  flakiness at the worst possible moment. The single **live** run in the actual demo
  video should still be real (§10) — DEMO_MODE is the fallback if that live run breaks
  during recording, not the default presentation.

---

## 10. DEMO SCRIPT (exact 3-minute path — audio must explicitly cover Token Factory + Nemotron, this is a hackathon rules requirement, not a suggestion)

| Time | Screen | Narration |
|---|---|---|
| 0:00–0:20 | S1, stats visible | "Published papers say 'code is on GitHub.' In one study, only 7% shipped code that actually ran. The best AI agents top out at 54% reproducing it — and the wall isn't coding skill, it's environments and dependencies." |
| 0:20–0:50 | S2 live, stages appearing | "RERUN clones a real paper repo into a Nebius Token Factory Sandbox and builds the environment from scratch." *(say "Token Factory" and "Nemotron" out loud here)* |
| 0:50–1:25 | S2 failure + repair | "It fails — not randomly. A classified failure: unpinned dependency resolving to an incompatible version. Nemotron Super proposes a minimal patch." |
| 1:25–1:55 | S2 tamper gate REJECT | "Here's the part that matters. The model's first patch made it run — by deleting the evaluation call. RERUN's tamper gate catches that and rejects it before it's ever applied." |
| 1:55–2:20 | S2 re-repair → PASS → S3 | "The second patch passes the gate cleanly. Certificate generated, signed with a Reproduction Passport hash anyone can verify independently." |
| 2:20–2:50 | S4 Batch Lab | "Across 20 real published repos run in parallel on Nebius Serverless Jobs: [Recovery Rate]% reproducibility recovery — a measured number, not a claim." |
| 2:50–3:00 | Close | One line stating the honest scope boundary + call to action (public URL + repo). |

---

## 11. BUILD PHASES (loop-driven — one capability per iteration, commit on green)

| Phase | Days | Deliverable | Gate (exact command + expected result) |
|---|---|---|---|
| 0 — Kill gate | 1–3 | Sandbox lifecycle proven end-to-end on 3 throwaway repos | `pytest tests/test_sandbox_smoke.py` green; 3 real sandboxes created and destroyed, logs shown to human |
| 1 — Recon + classifier + taxonomy | 4–12 | `intake.py`, `recon.py`, `classifier.py` (+ its tests) | `pytest tests/test_classifier.py -v` — every taxonomy code has ≥1 passing + ≥1 negative-control test |
| 2 — Tamper gate + repair loop | 13–19 | `tamper_gate.py`, `repairer.py`, full negative-control suite (§5.3) | `pytest tests/test_tamper_gate.py -v` — every rejection rule has a passing negative control; a hand-crafted "delete the eval call" patch is asserted REJECTED |
| 3 — API + Timeline UI + §6 enhancements | 20–28 | FastAPI + SSE, S1/S2/S3, `passport.py`, `INDETERMINATE` state wired end-to-end | Browser run streams live stages, renders a certificate with a real diff and a verifiable passport hash; component test asserts a rejected patch never renders as applied |
| 4 — BATCH LAB (decisive gate) | 29–37 | `corpus.yaml` (20 repos), Serverless Job runner, S4 with Recovery Rate | `batch_results.json` committed with all verdicts + failure breakdown; S4 renders it live from the committed file; `METHODOLOGY.md` written |
| 5 — Should-haves | 38–41 | Patch export, Tavily-cited repair context, adjudicator polish | Downloaded `.patch` applies cleanly with `git apply` on a fresh clone; certificate shows ≥1 cited Tavily source |
| 6 — Harden + deploy | 42–44 | `cost_guard.py`, `DEMO_MODE`, Serverless Endpoints deploy, README, LICENSE | Public URL runs S1→S2→S3→S4 from a clean browser; `/healthz` all green; a fresh `git clone` + README steps work on a machine that never touched this project |
| 7 — Submit | 45–46 | Demo video, description, feedback, §12 checklist | All §12 boxes ticked; submit **Oct 28**, not Oct 30 |

**Cut rules:** Phase 2 slipping past day 19 → cut Phase 5 entirely. Phase 4 not done by
day 37 → shrink corpus 20→10, report N honestly, never cut Phase 4 itself. The tamper
gate is never cut, at any point, for any reason.

---

## 12. HACKATHON COMPLIANCE CHECKLIST

- [ ] Runs on Nebius Token Factory (Sandboxes + inference)
- [ ] Uses ≥1 NVIDIA open-source model — Nemotron 3 Nano + Super + Ultra
- [ ] Category: Coding and Agentic Engineering
- [ ] Project description: what it is, why, how it works
- [ ] Working demo URL (hosted app — required for this track)
- [ ] Demo video: public YouTube, ≤3 minutes, audio explicitly covers Token Factory +
      NVIDIA model usage (scripted at 0:20–0:50 per §10)
- [ ] Public repo, Apache-2.0 license visible at the top of the repo page
- [ ] README with setup instructions and clear run guidance
- [ ] README highlights NVIDIA model usage, where Token Factory accelerated the
      workflow, and every other Nebius service used (Sandboxes, Serverless Jobs,
      Serverless Endpoints)
- [ ] Feedback submitted on Token Factory / AI Cloud / NVIDIA tools
- [ ] Not built from pre-existing code (or the required written explanation is included)
- [ ] Builders & Brews city selected if attended
- [ ] Tavily called at runtime, cited in the certificate — Best Use of Tavily eligibility
- [ ] Submitted before Oct 30, 2026, 10:00am PDT (internal target: Oct 28)

---

## 13. DEFINITION OF DONE

The project is finished when, and only when, all of the following are true and each was
verified by a command the human can re-run:

1. `pytest` passes across the full suite, including every tamper-gate negative control.
2. A fresh `git clone` on a clean machine, following only the README, produces a running
   local instance.
3. The public deployed URL completes a full live S1→S2→S3 run against a real GitHub
   repo, unassisted.
4. `batch_results.json` exists, is loaded live by S4, and its Recovery Rate/N are
   consistent with the raw per-repo verdicts in the same file.
5. At least one tamper-gate REJECT is reproducible on demand (a known bad patch,
   available as a fixture, that the gate rejects every time).
6. A downloaded certificate's Reproduction Passport hash verifies against
   `scripts/verify_passport.py` independently of the running app.
7. Every item in §12 is checked, with evidence (a link, a screenshot, or a file) next to
   each line in the submission notes.
8. `DECISIONS.md` reads as a coherent record of what was chosen and why — the human
   should be able to audit the whole build from this file plus the git log alone.

---

## 14. FINAL RED-TEAM PASS (run this on yourself before declaring done)

- Can a rejected-then-corrected repair actually reach `RUNS_AFTER_REPAIR` without the
  gate ever seeing the final diff? (It must not — trace the code path.)
- Does any code path let `batch_results.json` render a percentage without the raw N
  visible next to it?
- Is there any patch shape that deletes the evaluation call *indirectly* (e.g. wrapping
  it in a function that's never called) that the current gate rules would miss? If so,
  add the rule and its negative control now, don't defer it.
- Does the "estimated researcher-hours saved" line ever appear without the word
  "estimate" in the same visual frame?
- If `batch_results.json` is deleted, does S4 fail loudly, or does it silently show
  zeros? (It must fail loudly.)
- Would a skeptical technical judge, given five minutes with the repo, conclude the
  reasoning is decorative rather than load-bearing? If there's any doubt, strengthen the
  places where Nemotron output feeds a decision no deterministic rule could have made
  (scope of a minimal diff, prose adjudication) and make that visible in the UI.

---

**Begin at Phase 0. Do not wait for further instructions between phases — proceed
through the gates in order, commit on green, log decisions, and only surface a question
to the human under the four conditions listed in §0.**
