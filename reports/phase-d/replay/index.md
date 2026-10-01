# REPLAY index

Offline, deterministic replay of the committed records, cross-checked against the passports. The pre-registered run is the anchor;
the exploratory versions sit beside it with their badges. Rebuild with `python -m phase_d.build_replay`; check with
`python -m phase_d.build_replay --check`.

## `harness-v1.3.2` — PRE-REGISTERED ANCHOR

> `PRE-REGISTERED — harness-v1.3.2 is the pre-registered CONTROL / TREATMENT run; not exploratory.`

- [harness-v1.3.2.md](harness-v1.3.2.md) · sha256 `52eb42ca3a0a716689c124e3a3a2c07cf4aa6e271b6e720772dd6cbe57fa411b`
- [harness-v1.3.2.json](harness-v1.3.2.json) · sha256 `ecbb5b9082fadd29af78ad89c0b531b8db37519c1c74380a42e1e6762b410e9c`

## `harness-v1.3.3` — EXPLORATORY

> `EXPLORATORY — did not pass its pre-registered gate. a: 1/4 (measured), c: 0 citations in 7 searches.`

- [harness-v1.3.3.md](harness-v1.3.3.md) · sha256 `746f3c61bcb34b6cb804a3426c96d434014b6dfe41fa4776b10aa4afb61fbf3a`
- [harness-v1.3.3.json](harness-v1.3.3.json) · sha256 `4169338c3254490ae3bbb7a1a86182caaf5d5743573ba3cb17494d745d07c67b`

## `harness-v1.3.4` — EXPLORATORY

> `EXPLORATORY — did not pass its pre-registered gate. a: 0/4, c: 0 citations (7 attempts consulted, 21 refs, 6 reasons recorded).`

- [harness-v1.3.4.md](harness-v1.3.4.md) · sha256 `39fa1fc19f11bacaddff7f333dc1b19aefc023f25b8aacd3d069ba9d5b981884`
- [harness-v1.3.4.json](harness-v1.3.4.json) · sha256 `2eceb43f6ec20eefc65949518ad693312a8cafd47be553314ac56f478be28a01`

## Tags

- `API-REPORTED` (formerly MEASURED): a stored field of a committed record, or a count or sum of such fields. A dollar figure with this tag is the sandbox API's reported operation cost, not account billing (`D-36`, open).
- `ESTIMATED`: flagged as an estimate by the cost guard itself.
- `DERIVED`: parsed from event text or a cost_events note; the source line is quoted verbatim with its record id.
- `BILLED`: an account-balance reading taken by the owner. It is used only on the explicit BILLED lines of `summary.json` (`ledger.billed`), never on an API cost.

## Summary

Headline counts, the defect register and the cost ledger (with its BILLED lines), each number with its tag and its records.

- [summary.json](summary.json) · sha256 `11216d8cb698faa844a3250edb477919830311bb2690e316a16899d198d8439c`
