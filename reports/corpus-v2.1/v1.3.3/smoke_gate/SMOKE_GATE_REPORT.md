# v1.3.3 smoke gate (Step 2): NOT PASSED (2026-09-30)

Sealed tag `harness-v1.3.3` (`8af1717`), launcher `run_smoke_gate.py` at `f167921`, TREATMENT only, entries 11, 7, 3, 8 (METHODOLOGY amendments), cap $6.
Records: `runs/corpus_v2_batch/harness-v1.3.3/smoke/`; mechanical result: `smoke_gate_result.json` (same folder as this file). Exploratory, development set: not a confirmatory result.

## Mechanical result

| criterion | result | evidence |
|---|---|---|
| (a) at least 2 of 4 RUNS_CLEAN / RUNS_AFTER_REPAIR | **FAIL**: 1 of 4 | #11 RUNS_AFTER_REPAIR; #7 BLOCKED; #3 BLOCKED; #8 INVALID_HARNESS |
| (b) at least 1 source patch applied via `git apply` | **PASS**: 2 applied of 4 proposed | #3 repair 1 and repair 2 applied and re-executed (first applied patches of the project: v1.3.2 0 of 16); #3 repair 3 rejected by the gate (broke the file's syntax); #7 repair 3 was a mis-targeted edit (see D-18) |
| (c) at least 1 repair with a real Tavily citation in a record | **FAIL**: 0 | 7 searches in 3 entries (#3: 3, #7: 3, #8: 1, #11: 0), 0 cited; the repairer declared no `cited_sources` |
| (d) no entry over $2, cost guard fired on nothing or correctly | **PASS** | $0.6171, $0.4610, $0.9018, $0.9499; no cost event, no COST_CAP |

Spend: **$2.9298** (gate). Cumulative on the new ledger: seal $2.496 + gate $2.930 = **$5.426**.

## Per entry

| # | verdict | what happened | repairs (tags) | Tavily cited | cost |
|--:|---|---|---|---|--:|
| 11 | RUNS_AFTER_REPAIR | baseline `No module named 'tqdm'`; the time machine (era lock, Python 3.9, NumPy<2 beside torch 1.8.1) fixed it in one step; smoke re-execution `alive_at_limit` (still running at 60 s, output, no traceback). v1.3.2 ended this entry INDETERMINATE RUNNER_SETUP_FAILED (D-16) | time_machine only | no (no model repair, 0 searches) | $0.6171 |
| 7 | BLOCKED | era lock on Python 3.8 (19 packages); install fails at `metadata-generation-failed` (native `pygame` needs SDL headers) | 0 time_machine; 1 env_only (apt pkg-config, libsdl1.2-dev, libfreetype6-dev); 2 env_only (add libsdl-ttf2.0-dev, libsdl-image1.2-dev, libsdl-mixer1.2-dev, libportmidi-dev); 3 source_patch REJECT (edit of the lock shown as `requirements.txt`) | no (3 searches; off-target results) | $0.4610 |
| 3 | BLOCKED | README Python 3.6 honoured (D-11 works); era lock 9 packages; every re-execution exits 1 with only a `17.7%` progress stream, recorded evidence `1` | 0 time_machine; 1 source_patch (applied); 2 source_patch (applied); 3 source_patch REJECT (unparseable result) | no (3 searches) | $0.9018 |
| 8 | INVALID_HARNESS | era lock failed on a yanked `torchvision`, the fallback (one unpinned pip step, D-5 fix) reached `ImportError: cannot import name 'compare_psnr' from 'skimage.measure'`; repair 1 proposed a source patch that passed the gate and was applied; the next upload failed its post-extraction check (`utils.py (content)`, exit 97) | 0 time_machine (fallback); 1 source_patch (applied, NOT recorded, D-22) | no (1 search; the scikit-image API page was the top result) | $0.9499 |

## Root causes (no spend, no fix made: the harness is sealed)

- **D-20 (entry 8, decisive): the download route cannot carry a patched file.** A repository over the upload cap (125.8 MB) is fetched inside the sandbox at its pinned commit and every
  file is verified against a manifest built from the local tree. After a patch is applied locally the manifest holds the PATCHED `utils.py` blob, the sandbox fetches the ORIGINAL,
  and the check fails with exit 97: INVALID_HARNESS on the first re-execution after any applied patch. Only 1 file mismatched, and it is the patched one; entry 8's tree is 143 MB.
  Four of the 20 corpus entries are over the cap (2, 8, 10, 11), so no source patch can succeed there in v1.3.3. Not seen in v1.3.2 because no patch ever reached a re-execution. Fix (needs a
  new seal and a NEW tag): ship the patched files in the manifest-only archive under the upload directory and copy them over the fetched tree before the verification.
- **D-19 (entry 3): a silent exit 1 after a progress stream gives the repairer nothing to act on.** The denoised evidence is `1`; the model patched blindly (2 applied patches, neither changed
  the outcome, the third broke the file). The classifier did its job (no noise taken for an error); the information is simply not in the output.
- **D-18 (entry 7): the repairer is shown RERUN's resolved lock under the name `requirements.txt`.** It tried to edit it with `file_edits`; the patch pipeline correctly refused ("not an existing
  file in the repository"), which cost a re-ask in repair 2 and the whole of repair 3. The lock should be presented as RERUN-owned, editable only through `env_delta`.
- **D-21 (criterion c): no Tavily citation in 7 searches.** The queries carried error, framework and Python version as designed and returned results, including for entry 8 the scikit-image
  API documentation for a moved function, yet the repairer never declared a `cited_sources`. Whether it used a result is unknown (entry 8's attempt is unrecorded). The mechanism (validated, stored, hashed)
  is tested offline; the model does not use it unprompted.
- **D-22: an attempt whose execution ends in INVALID_HARNESS is not recorded.** Entry 8's repair-1 attempt (the patch and its delta) exists only as log lines.
- Entry 7 itself: a native build failure whose real compiler output is not in the captured tail; the apt packages tried did not change the classification. It is a repository/system-library problem,
  not a platform requirement, as selected; it was not recovered.
- What worked, live: README-declared Python (entry 3), NumPy cap + era lock (entry 11 recovered with no model call), the fallback batch pip after a failed lock (entry 8 went from `sklearn` to a real API
  error), 2 source patches rebuilt by the pipeline and applied, smoke execution (`alive_at_limit` and `exited` both observed), budget enforcement (no cost event needed).

## Reading

One of four recovered, and it was the deterministic time machine, not the model repair loop. The model repair loop recovered 0 of the 3 entries that reached it; its failures are traceable to D-18,
D-19, D-20 and to a repairer that does not cite. This is a statement about the v1.3.3 repair loop on four entries, not about the papers.
