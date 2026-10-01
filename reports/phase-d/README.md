# Phase D — passports (D1) and REPLAY (D2)

One passport per committed run record of harness-v1.3.2, harness-v1.3.3 and harness-v1.3.4, generated offline from the
committed blobs. The list of record ids is in [record_index.md](record_index.md); the passports are under `passports/`.

```bash
python -m phase_d.build_passports     # rebuild passports + record index from git blobs
python -m phase_d.verify_passports    # rebuild and diff to zero; exit 1 on any difference
python -m phase_d.check_tags          # exit 1 if any number lacks a tag
python -m phase_d.build_replay        # rebuild REPLAY (passports are verified first)
python -m phase_d.build_replay --check   # rebuild REPLAY and diff to zero; exit 1 on any difference
```

## Rules

- **Identity.** `record_id = <harness_tag>/<arm>/<entry>@<sha256>`. The SHA-256 is taken over the committed blob
  (`git cat-file blob HEAD:<path>`), never over the worktree file: a checkout with `core.autocrlf=true` rewrites line endings.
  `image_id` (the baseline sandbox id) is a separate field and is not an identity.
- **Records win.** A value is copied from the record and never recomputed, rounded or corrected. A correction is an
  annotation beside the original, with a quoted source.
- **Tags.** Every number carries exactly one tag:
  - `MEASURED`: a stored field of a committed record, or a count / sum / difference of such fields (then with `computed_from`);
  - `ESTIMATED`: flagged as an estimate by the cost guard itself (the killed step of harness-v1.3.4 entry 8);
  - `DERIVED`: parsed from event text or a `cost_events[].note`; the source line is quoted verbatim with its record id
    (`funded_seconds`, `wall_seconds`, `killed_by`, `killed_step_seconds`, the search count of the harness-v1.3.3 badge).
- **Absent fields.** A field the harness version did not store is `{"value": null, "reason": "not recorded by harness-vX.Y.Z"}`.
  `cited` is null on every attempt: `tavily_sources` is empty on all attempts, consistent with D-21 open.
- **Badges.** harness-v1.3.3 and harness-v1.3.4 passports carry the EXPLORATORY badge with that version's own measured gate
  line, linked to its run records and cost line. harness-v1.3.2 is the pre-registered run and carries no exploratory badge.
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

Passport schema v2 added the tagged fields REPLAY displays: `attempts[].consulted_count`, `cost.batch_cap`, `cost.operations[]`
(the cost guard's own log line per sandbox operation, DERIVED), the gate criteria b and d in the badge figures, and the
pre-registered primary line of harness-v1.3.2 (`badge.figures`, from `reports/corpus-v2.1/results_tables.json`).

## Ledger

The ledger total is a lower bound (D-27): it records only completed cost, and the spend of a killed step is absent wherever
the cost guard stored no estimate. Missing amounts are not reconstructed.
