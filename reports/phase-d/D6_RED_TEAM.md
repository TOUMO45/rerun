# D6 red team (2026-10-02)

The brief: attack the submission and try to find one untagged number, one softened failure, one claim without a record, one way the replay could be tampered with without detection, one place the LLM loop is implied to have worked, and, added by the owner, any claim that still rests on a truncated stream. Each finding is fixed or documented; none is hidden. No live call was made.
Counts are counts over committed records or files (DERIVED), each reproducible with the command or test named beside it. The checks that failed when a fix was removed are listed at the end (negative controls).

| # | Attack | Findings | Fixed | Documented only |
|---|---|---|---|---|
| 1 | An untagged number | 5 | 4 | 1 |
| 2 | A softened failure | 4 | 2 | 2 |
| 3 | A claim without a record | 4 | 4 | 0 |
| 4 | A replay tampered with, undetected | 3 | 1 (partly) | 2 |
| 5 | The LLM loop implied to have worked | 3 | 1 | 2 |
| 6 | A claim resting on a truncated stream | 11 records, 2 narrative claims | the annotations, the scan, the tests, one text | the verdicts stay as recorded |

## 1. An untagged number

Method: the tests cover the JSON (`check_tags`), the dashboard (no digit outside a tagged number or a quote) and five submission texts (every number is in the REPLAY JSON and every line with a number carries a tag). I scanned what they do not cover: `reports/phase-d/README.md`, `docs/design/*.md`, the gate reports and the texts after the v1.4.3 update.

1. `reports/phase-d/README.md` stated "65 records" untagged. **Fixed** (tagged).
2. `docs/design/D-23.md` and `D-25.md` carry the retired first tag word (the one D-36 renamed) on 18 lines (DERIVED: 8 and 10) and `D-40-resources.md` has many untagged numbers (quotes from documentation pages, SDK source lines and earlier readings). **Documented**: a dated banner on each note says what the old word means and that untagged numbers there are quotes or planning arithmetic, not results; the notes are not rewritten (records win, annotate beside).
3. A tagged but wrong number: the README said the entry cap was $2.0 in the first gates and $1.5 in the root-cause gates; the records show $1.25 in harness-v1.4.0 and caps from $0.7819 in harness-v1.3.4. The existing tests only prove that a number exists somewhere in the JSON, not that it is the right one where it is used. **Fixed**, and `test_the_entry_caps_the_readme_states_are_the_caps_of_the_records` compares the sentence with each version's own caps.
4. The ledger total and the room were stated as $29.1703 and $2.8297 in the gate report, METHODOLOGY and CHANGELOG; the unrounded records add up to 29.17038 ($29.1704, room $2.8296). The report's rows, rounded as their sources state them, had added up to the wrong figure. **Fixed**: the three texts, the Phase D quotes and a sentence under the report's table; `test_the_last_gate_report_and_the_texts_that_repeat_it_state_the_rebuilt_figures` checks every ledger and spend figure in them against the rebuilt value at the precision they state.
5. After the v1.4.3 update the headline denominator was stale in several texts ("of 20"), and the gate report said "five exploratory gates" for six. **Fixed**; `test_the_headline_sentence_of_every_text_is_the_recomputed_one` fails if any text keeps the old denominator.

## 2. A softened failure

Method: grep for hedges and for the word the owner's rule governs, then compare each failure statement with its record; check each status against the register's rule; check whether anything was re-run after its outcome had been seen.

1. "Recovered" without its criterion beside it, in the README, the description, the Devpost answers, the criteria map and the demo script (spoken line, on-screen text, evidence row). **Fixed**: the text now says "reached RUNS_AFTER_REPAIR" (the pre-registered primary measure); the dashboard's list titles and table header name the verdict class; a test asserts the bare word is absent from the headline card.
2. Two annotations beside the same entry-3 verdicts disagreed: the D-35 annotation said "the cause is not established" while the D-41 annotation names it. **Fixed** (the D-35 text now points at the D-41 annotation).
3. D-25 ("a deliberate silent exit cannot be located") reads as a harness failure still unfixed, but its premise, a deliberate silent exit on entry 3, was a CUDA error behind a cut stream (D-41). **Documented**: a note on the register row, on `docs/design/D-25.md` and in the defects notes; the register keeps it open. **Owner decision**: retire it or keep it as a design for a genuine silent exit.
4. D-40 is `fixed-and-gated` although the platform limit remains (the SDK has no instance-size parameter, pinned by `test_contree_sdk_0_3_6_has_no_memory_cpu_size_or_instance_parameter`). I checked it against the rule, which asks for no open remainder in the harness; the remainder is a platform limit, named in the row note and in the README's Known limits. **Documented as a judgement**; changing the status is one line in `phase_d/defects.py`.

Checked, no finding: no entry of the final gate was re-run after its outcome had been seen. The three killed attempts left stdout files with no verdict line for the entries that were run again (the verdict lines in them are the ones that became records: entries 3 and 7); entry 8 was killed before any verdict.

## 3. A claim without a record

Method: trace each factual sentence of the README and the submission texts that states more than a figure to a record or a pinned test.

1. "A dataset the repository does not contain" (the final gate's entry 3, in five places: the passport annotation, the README, the gate report, the changelog). No record shows what the repository contains; the error is a `FileNotFoundError` on an absolute path outside the checkout. **Fixed**: the texts say the path does not exist in the sandbox and that whether the repository documents how to obtain it was not examined; the gate report keeps a dated note.
2. The D-41 annotation said "the silent exit in this record was a CUDA error" on records whose own operation the probe never re-ran (it re-ran one record's command). **Fixed**: the probed record says so with the probe record's id; the others say it is an inference from the same command and the same cut point (a different point for harness-v1.3.2), "not a measurement of this run"; `test_the_annotations_say_what_was_probed_what_is_inferred_and_what_is_only_suspected` pins the wording.
3. "The SDK has no parameter to choose a larger instance" had no pointer in the README. **Fixed**: it cites the pinned test.
4. The Devpost answers counted "patched blindly on a silent exit" against the model; the missing error text was the harness's cut stream. **Fixed**: it now counts against the harness.

Checked, no finding (each traced to a committed record): the model calls of the pre-registered run (40, 99, 38), its recorded spend ($21.7572 over 41 records, the largest entry $5.6773), the VM's 3.85 GiB, 4 CPUs and no swap (the evidence block of the last two gates' entry 11), the gate spends of all six exploratory versions against the records (new test), the classifier importing no model client.

## 4. A way to tamper with the replay without detection

Method: a scratch clone of the committed state (never the real checkout), four experiments, each followed by the four tooling checks (`verify_passports`, `build_replay --check`, `build_dashboard --check`, `truncation_scan --check`) and the Phase D tests.

| Experiment (in a scratch clone) | Four tooling checks | Phase D tests | Detected |
|---|---|---|---|
| T0 the committed state, untouched | all pass | | |
| T1 one byte of one final-gate record (a timestamp), nothing regenerated | all four FAIL | not run | yes |
| T2 the same byte, passports, REPLAY, scan and dashboard rebuilt and committed | all pass | 141 passed, 1 skipped | **no** |
| T3 one entry's recorded spend halved in its record, everything rebuilt | all pass | 10 failed | yes, by the figures the tests pin |
| T4 a percentage in a sentence of the final gate report, outside any quoted line | all pass | 141 passed, 1 skipped | **no** (before the check added below) |

Findings:

1. **A record changed and every generated file rebuilt is not detected by the tooling or by any Phase D test** (T2): the build trusts the committed blobs it is given and the record id follows them. Only the git history shows it. **Documented**; the defence is an anchor outside the repository: the commit hash (or a tag) and the sha256 of `reports/phase-d/record_index.md`, recorded where the repository's author cannot rewrite them (the Devpost text, a timestamp). Values for this commit are in the report to the owner. Not fixable inside the repository, and `reports/phase-d/README.md` now says so (Trust boundary).
2. A changed cost or verdict is caught by the figures the tests pin (T3), but only because the tests were left alone; an attacker who edits the tests too is not caught. **Documented**.
3. The prose of a gate report outside quoted lines was not checked at all (T4: the changed percentage passed every check and every test). **Fixed in part**: the new agreement tests check, for the final gate's report, the spend table, the criteria rows (b), (c), (d), the share of the cap, the verdict table and the ledger figures, and for every gate report the spend line against the records; with the share-of-cap check the T4 change now fails. Any other sentence of that report, and the prose of the older reports, remains unchecked: **documented**.

## 5. The LLM loop implied to have worked

Method: read every sentence that names a model, the repairer, a patch or a candidate, and ask whether it suggests the model made something work; the submission test only catches sentences that use a recovery word.

1. The demo script said one added package "lets the command run for the smoke limit". **Fixed**: "a run with one added package was still alive at the smoke limit".
2. The dashboard shows criteria (b) and (c) of the final gate as PASS (a patch was applied, a citation was stored). They are process criteria; a reader can take PASS for "the repairer worked". **Documented**: each criterion line carries its own text ("applied", "cited"), the card says EXPLORATORY and the headline says no gate passed; the Devpost answer says "well-formed enough to apply" and that whether a citation shaped a decision is not measured.
3. The verdict name RUNS_AFTER_REPAIR contains the word "repair". **Documented**: it is the record's own name and stays; every text that names it puts the smoke criterion beside it, and the dashboard shows the SMOKE-CRITERION annotation next to the chip.

## 6. Any claim that still rests on a truncated stream

Method: the SDK cut each stream at its default limit and kept the start; the harness stored the last 2000 characters of what it received. `python -m phase_d.truncation_scan` (reads the committed blobs; `--check` diffs to zero) flags a record when a full-length stored tail ends inside a line, or when a recorded error text has no word in it. It is a heuristic: a tail cannot prove a cut, the one proof is the probe, and a tail shorter than the stored length cannot have been cut at all. RUNS_* verdicts rest on the exit code and on liveness at the smoke limit, not on the stream.

Result: 11 of 65 records flagged (DERIVED), 54 not. In the final gate no stream was cut: all 68 streams of its 34 operations that ran a command say `truncated` false (`test_no_stream_of_the_four_final_gate_records_was_cut_and_the_api_said_so`), the largest was 400941 bytes.

| Record | Flag | Annotation beside its verdict |
|---|---|---|
| v1.4.2 entry 3 | probed: the real stderr was longer, a CUDA error behind the cut | D-41, the probe record named |
| v1.3.3, v1.3.4, v1.4.0, v1.4.1 entry 3 | same command, same cut point, recorded error `1` | D-41, "inference, not a measurement of this run" |
| v1.3.2 TREATMENT entry 3 (pre-registered) | tail ends mid-progress-bar at a different point, recorded last error `17.6` | D-41, inference with the weaker basis stated |
| v1.3.2 TREATMENT entry 6 (pre-registered) | tails of four attempts end inside a pip build log | D-41 suspected, not probed |
| v1.4.0 entry 8, v1.4.2 entry 8 | one tail each ends inside a build log | D-41 suspected; the COST_CAP verdict rests on the cost guard |
| v1.3.3 entry 11 | tail ends mid-progress-bar; verdict RUNS_AFTER_REPAIR | D-41 checked: rests on liveness, not on the stream |
| v1.4.1 entry 11 | recorded error is a progress line; the tail ends in `Killed` (not cut) | D-41 checked; the progress line was misread as an error (D-38) |

What this changes: no verdict, no count. Neither the headline nor the pre-registered 0 of 16 is read from a stream. Two things follow that matter more than the labels. First, **the repair loop worked blind on entry 3 in every version before the last**: it was shown a cut stream, could not act on the CUDA error behind it, and the final gate, which saw the error and the CPU shim answer it, got as far as the dataset path. So the counts measure the harness as it was, not what repair could do with the whole error; the README says so beside the entry-3 finding. Second, labels do depend on streams: the BLOCKED and INDETERMINATE codes of the flagged records may rest on text from before a cut, and two of them are in the pre-registered run (entries 3 and 6 of TREATMENT). They stay as recorded, with the annotation beside them. Not visible to the scan: the baseline streams of the CONTROL arm (no tail is stored, only a 500-character evidence line), the install logs of any record, and the seal and probe records. Not probed: all live work stopped.

Narrative claims that rested on the cut: "the silent exit of entry 3" (D-19, D-25, D-35, the `EXIT_OUTSIDE_PYTHON` verdict) and the Devpost sentence about blind patching (fixed, finding 3.4). The defects notes annotate the first group; the earlier documents are left as written.

## Negative controls

Each new check was shown to fail when the thing it guards is broken, with the file restored byte for byte afterwards: the ledger total in the gate report changed (fails), a verdict code in the report changed (fails), an older gate's spend changed in its report (fails), an annotation of a flagged record removed (fails), an inferred record presented as probed (fails), the scan's threshold made unreachable (fails), the T4 percentage changed (fails after the share-of-cap check was added).
