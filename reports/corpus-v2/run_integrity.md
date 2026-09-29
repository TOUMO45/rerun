This is a **pilot run**, not a baseline. Corpus `corpus-v2`, hash `7df090be…`, harness tag `harness-v1.2`.

- **Run A** — entries 1–3, 2026-09-29 18:53–19:09 UTC (records committed in `56fc710`).
- **Stopped by the operator** at entry 4 under the freeze rule (a failure charged to the repository that is
  not the repository's fault: entry 3). Entry 4 (`damo-cv/img-comp-reference`) was started and killed
  before completing; it has **no record** and is not counted. Entries 4–20 were **not run** on this harness.
- The driver did not crash. An earlier working hypothesis in this session ("driver died, orphaned
  child") was wrong; the evidence is commit `56fc710` and the absence of any entry-4 record.
- No run B exists on `harness-v1.2`. The full 20-entry evaluation is the corpus-v2.1 ablation on a new sealed harness tag.
- What the pilot found: (1) the Nebius sandbox refuses shared objects that require an executable stack
  (stock PyTorch wheels fail to load); (2) an upload cap of 125,009,920 B.
- **Reading the PRIMARY lines:** they count entry 3 as measured and failed. Entry 3 is MISATTRIBUTED (see its note), so the honest measured count is 1, not 2. The harness was frozen, so the driver's own line was not edited.
