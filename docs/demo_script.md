# RERUN demo video script (§10)

Exact 3-minute path for the hackathon demo video. Audio must explicitly say "Token
Factory" and "Nemotron" out loud where marked — this is a hackathon rules requirement,
not a suggestion (§12).

The narration below is the reference script from `RERUN_BUILD_DIRECTIVE.md` §10,
extracted here as its own file per the directive's repo structure (§4.2). Swap the
specific failure mode / repo in the 0:50–1:55 beats for whatever real repo is actually
used in the recording — the *shape* of the sequence (fail → classify → repair attempt →
tamper gate REJECT → repair attempt → PASS) is what the script is built around, not
these exact words.

| Time | Screen | Narration |
|---|---|---|
| 0:00–0:20 | S1, stats visible | "Published papers say 'code is on GitHub.' In one study, only 7% shipped code that actually ran. The best AI agents top out at 54% reproducing it — and the wall isn't coding skill, it's environments and dependencies." |
| 0:20–0:50 | S2 live, stages appearing | "RERUN clones a real paper repo into a Nebius Token Factory Sandbox and builds the environment from scratch." *(say "Token Factory" and "Nemotron" out loud here)* |
| 0:50–1:25 | S2 failure + repair | "It fails — not randomly. A classified failure: unpinned dependency resolving to an incompatible version. Nemotron Super proposes a minimal patch." |
| 1:25–1:55 | S2 tamper gate REJECT | "Here's the part that matters. The model's first patch made it run — by deleting the evaluation call. RERUN's tamper gate catches that and rejects it before it's ever applied." |
| 1:55–2:20 | S2 re-repair → PASS → S3 | "The second patch passes the gate cleanly. Certificate generated, signed with a Reproduction Passport hash anyone can verify independently." |
| 2:20–2:50 | S4 Batch Lab | "Across 20 real published repos run in parallel on Nebius Serverless Jobs: [Recovery Rate]% reproducibility recovery — a measured number, not a claim." |
| 2:50–3:00 | Close | One line stating the honest scope boundary + call to action (public URL + repo). |

## Before recording

- [ ] Pick the actual repo for the 0:20–1:55 sequence. It needs a real, reproducible
      failure that the repair loop can genuinely fix in ≤2 attempts, **and** a first
      repair attempt that the tamper gate will genuinely REJECT — this is the single
      most load-bearing few seconds of the whole video (§14: this is the moment that
      separates RERUN from every other repair agent). Don't stage a REJECT with a
      contrived patch; let the real bounded loop produce one, or use a fixture
      specifically built and verified to reproduce this exact sequence (see the
      DEMO_MODE gap noted in `DECISIONS.md` — as of this writing, DEMO_MODE's recorded
      fixtures are declared as a config flag but not yet actually implemented, so this
      sequence currently needs a real live run, not a guaranteed fallback).
- [ ] Confirm `batch_results.json` is the real, committed corpus result — the [Recovery
      Rate] placeholder at 2:20–2:50 must be the actual number from that file, with its N
      visible in the same frame (§6.2, §14: never a percentage without the N next to it).
- [ ] Confirm the closing scope line matches the fixed wording used everywhere else in
      the app: "Verifies that the artifact executes. Does not verify the paper's
      numerical results."
