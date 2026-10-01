# Phase D — passports (D1), REPLAY (D2) and dashboard (D3)

One passport per committed run record of harness-v1.3.2, v1.3.3, v1.3.4, v1.4.0, v1.4.1 and v1.4.2 (61 records), generated offline from the
committed blobs. The list of record ids is in [record_index.md](record_index.md); the passports are under `passports/`.

```bash
python -m phase_d.build_passports     # rebuild passports + record index from git blobs
python -m phase_d.verify_passports    # rebuild and diff to zero; exit 1 on any difference
python -m phase_d.check_tags          # exit 1 if any number lacks a tag
python -m phase_d.build_replay        # rebuild REPLAY (passports are verified first)
python -m phase_d.build_replay --check   # rebuild REPLAY and diff to zero; exit 1 on any difference
python -m phase_d.build_dashboard     # build dashboard/index.html (stops if the REPLAY check or the page check fails)
python -m phase_d.build_dashboard --check   # rebuild the page and diff to zero
python -m phase_d.check_dashboard     # parse the page: every number tagged and linked, no external resource
```

## Rules

- **Identity.** `record_id = <harness_tag>/<arm>/<entry>@<sha256>`. The SHA-256 is taken over the committed blob
  (`git cat-file blob HEAD:<path>`), never over the worktree file: a checkout with `core.autocrlf=true` rewrites line endings.
  `image_id` (the baseline sandbox id) is a separate field and is not an identity.
- **Records win.** A value is copied from the record and never recomputed, rounded or corrected. A correction is an
  annotation beside the original, with a quoted source.
- **Tags.** Every number carries exactly one tag:
  - `API-REPORTED` (formerly MEASURED): a stored field of a committed record, or a count / sum / difference of such fields (then with `computed_from`).
    A dollar figure with this tag is the sandbox API's reported operation cost, not account billing (D-36, open); the meaning is unchanged, only the word;
  - `ESTIMATED`: flagged as an estimate by the cost guard itself (the killed step of harness-v1.3.4 entry 8 and of harness-v1.4.0 entry 8);
  - `DERIVED`: parsed from event text or a `cost_events[].note`; the source line is quoted verbatim with its record id
    (`funded_seconds`, `wall_seconds`, `killed_by`, `killed_step_seconds`, the search count of the harness-v1.3.3 badge);
  - `BILLED`: an account-balance reading taken by the owner. It never appears on a passport or on a REPLAY version file and is never used on an API cost;
    it appears only as the explicit BILLED lines of `replay/summary.json` (`ledger.billed`), where the check refuses it anywhere else.
- **Absent fields.** A field the harness version did not store is `{"value": null, "reason": "not recorded by harness-vX.Y.Z"}`.
  `cited` is null on every attempt of the harness-v1.3.x passports: `tavily_sources` is empty on all of their attempts, consistent with D-21 open.
  From harness-v1.4.0 the record stores the cited sources and `cited` is the list of them (title, url, a hash of the stored content), empty when the model cited none.
- **Badges.** The passports of harness-v1.3.3, v1.3.4, v1.4.0, v1.4.1 and v1.4.2 carry the EXPLORATORY badge with that version's own measured gate
  line (a version whose gate has a RUNS_AFTER_REPAIR carries the smoke-criterion note beside figure a), linked to its run records and cost line. harness-v1.3.2 is the pre-registered run and carries no exploratory badge.
- **Arms.** harness-v1.3.2 CONTROL and TREATMENT are separate passports, never merged. The kept first attempt of CONTROL
  entry 7 (INFRA_ERROR) is a passport marked `superseded_by` the registered retry.

## Attempt outcome

`outcome` is `applied`, `rejected`, `declined` or `gate_passed_not_executed`. `applied` follows the smoke gate's own rule
(`run_smoke_gate.py`): the gate passed the change and a re-execution result exists (`exit_code` is not null).
`gate_passed_not_executed` is a gate PASS with no re-execution result in the record (the patch failed to apply, or the
operation was stopped first).

## Not machine-checked

The tag check covers JSON numbers. Numbers inside quoted text (error messages, event lines, the badge sentence, annotation
text) are strings; the badge figures are repeated as tagged fields under `badge.figures` and `badge.gate_cost`.

This limit is deliberate: the tag check stays JSON-only. It is closed downstream. In REPLAY (D2) and the dashboard (D3) no
displayed number may be taken from text (a badge sentence, an event line, an error message); it must be read from a tagged
passport field, and an acceptance test enforces that.

## REPLAY (D2)

[replay/index.md](replay/index.md) lists one replay per harness version (`.json` and `.md`). REPLAY reads each record blob,
rebuilds the entry's timeline (baseline, era lock, attempts, execution and kills, verdict, cost) and cross-checks every value
it shows against the passport field it displays; a mismatch stops the build. The pre-registered run is the anchor and the
exploratory versions sit beside it with their D1 badges. The output has no build timestamp and is byte-identical across runs.

Every number in the replay JSON is a tagged passport field carried with a pointer: `ref` (one passport field), `sum_of` (the
sum of one passport field over the version's run order) or `count_of` (how many passports have a field value). In the
Markdown, text in code spans is quoted verbatim; outside code spans every number is a tagged value followed by its tag.
The one exception is the BILLED lines of `replay/summary.json` (`ledger.billed`): they are the owner's account-balance reading, not a passport field, and
carry `owner_reading` (the account line) or `for_component` (a gate line, null with a reason) instead of a passport pointer.

Passport schema v2 added the tagged fields REPLAY displays: `attempts[].consulted_count`, `cost.batch_cap`, `cost.operations[]`
(the cost guard's own log line per sandbox operation, DERIVED), the gate criteria b and d in the badge figures, and the
pre-registered primary line of harness-v1.3.2 (`badge.figures`, from `reports/corpus-v2.1/results_tables.json`).
Passport schema v4 renamed the first tag to API-REPORTED (D-36, see Tags above); no value changed.
Passport schema v5 (the passports of harness-v1.4.0, v1.4.1 and v1.4.2 only; the older passports stay v4 and keep their bytes, except for the D-41 annotation beside the entry-3 passports of v1.3.3 and v1.3.4) adds, per attempt, `candidate`,
`chosen`, `branch`, `adjudication` and `rule_step` (a deterministic step recorded by the harness: hook, wrapper, CPU shim, evidence run), the attempt labels `attempt-<n>-candidate-<k>` and `attempt-0-<rule>` (three candidates share one attempt number),
`repair-round-<n>` in `cleared_by`, and `cost.stored_operations` (the record's own operation list, numbers API-REPORTED). A time-machine kill is attached to the step that has no exit code.

## Dashboard (D3)

[dashboard/index.html](dashboard/index.html) is one static page, built from the REPLAY JSON only (the six version files and
`replay/summary.json`, which holds the headline counts, the defect register and the cost ledger). It opens from `file://`: no
script, no animation, no external resource. Every number is shown with its tag and links to the record, or the list of records,
it was read from; dollar values show 4 decimals with the full-precision value in the `data-value` attribute and the tooltip.
Text in code style is quoted verbatim from the REPLAY JSON. A cost bar always draws API-REPORTED and ESTIMATED as separate segments. The one BILLED number on the page
(the owner's account-balance reading, in the ledger section) links to its own source line instead of to a record.

Defect status rule (`phase_d/defects.py`, each row with quoted sources that the build checks): `fixed-and-gated` means the fix map
calls it fixed with no open remainder and a committed gate or seal report line states the fix was observed working live (it does
not mean the gate passed); `fixed-unvalidated` means a fix or correction exists without such a line; `open` means no fix, a fix
the fix map itself calls partial, or a defect that still shows in practice.

## Ledger

The ledger is $22.4935 = $21.3218 API-REPORTED + $1.1717 ESTIMATED: the sum of the full-precision cost fields of the seal-verification
records, the pre-batch upload smoke records and the gate records (`replay/summary.json`, `ledger`). It is a lower bound (D-27): it records only completed cost,
and the spend of a killed step is absent wherever the cost guard stored no estimate (four estimates are stored: $1.1717 in all). Missing amounts are not reconstructed.
Rebuilt from the records it equals, to the fourth decimal, the figure the last gate report states; the figures the earlier gate reports stated ($10.134, $14.6495, $18.5083) are
quoted beside it on the dashboard and each is reproduced by the components up to that gate.

These figures are the sandbox API's reported operation cost, not account billing. Beside them, `replay/summary.json` holds `ledger.billed`: the owner's
readings of the Nebius account balance page (BILLED: the latest, at most $0.43 for the whole account, cumulative, not per gate, with the first reading, at most $0.39, kept beside it;
Nebius billing lag is unknown; each reading is quoted as the line's source) and, for each gate that exists in REPLAY, a BILLED line: null with a reason where no balance reading was taken
for that gate or the reading has not been received yet (harness-v1.4.2), and for harness-v1.4.1 the difference of the two readings, the one interval that holds a gate. The two kinds of
figure are not reconciled (D-36, open).
