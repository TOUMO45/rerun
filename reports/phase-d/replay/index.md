# REPLAY index

Offline, deterministic replay of the committed records, cross-checked against the passports. The pre-registered run is the anchor;
the exploratory versions sit beside it with their badges. Rebuild with `python -m phase_d.build_replay`; check with
`python -m phase_d.build_replay --check`.

## `harness-v1.3.2` — PRE-REGISTERED ANCHOR

> `PRE-REGISTERED — harness-v1.3.2 is the pre-registered CONTROL / TREATMENT run; not exploratory.`

- [harness-v1.3.2.md](harness-v1.3.2.md) · sha256 `52eb42ca3a0a716689c124e3a3a2c07cf4aa6e271b6e720772dd6cbe57fa411b`
- [harness-v1.3.2.json](harness-v1.3.2.json) · sha256 `d485cb749beac21d74cba9d41c42f31b278233352385542c4220beea8b36756a`

## `harness-v1.3.3` — EXPLORATORY

> `EXPLORATORY — did not pass its pre-registered gate. a: 1/4 (measured), c: 0 citations in 7 searches.`

- [harness-v1.3.3.md](harness-v1.3.3.md) · sha256 `fe8838c9abb1dd95bbb92a09cdd8fabaff20173be0e0783e0dcea6e21e4aa77b`
- [harness-v1.3.3.json](harness-v1.3.3.json) · sha256 `fffa1b7d507bb03162a40930353116861d9b70b99512a5c4e09e7e4da718a7ed`

## `harness-v1.3.4` — EXPLORATORY

> `EXPLORATORY — did not pass its pre-registered gate. a: 0/4, c: 0 citations (7 attempts consulted, 21 refs, 6 reasons recorded).`

- [harness-v1.3.4.md](harness-v1.3.4.md) · sha256 `666da38890b1ef5e99735429909f97aa1ecee1c9104a370ae545da42fb7878d6`
- [harness-v1.3.4.json](harness-v1.3.4.json) · sha256 `caf815e734f8a1ed9ffeb9837851efa0d633c65395449b228879faa726daa90d`

## `harness-v1.4.0` — EXPLORATORY

> `EXPLORATORY — did not pass its pre-registered gate. a: 0/4, c: 3 citations (24 attempts consulted, 72 refs, 15 reasons recorded).`

- [harness-v1.4.0.md](harness-v1.4.0.md) · sha256 `4b36e8a8df0005218d2450b40cbf92f71594fe5ac9bdff6126e0006cd8bc126c`
- [harness-v1.4.0.json](harness-v1.4.0.json) · sha256 `47e177ddc7cc8fcbd30e04c00eecb479647cfef0fa4053477f686ef02b1e1c51`

## `harness-v1.4.1` — EXPLORATORY

> `EXPLORATORY — did not pass its pre-registered gate. a: 0/4, c: 6 citations (36 attempts consulted, 108 refs, 28 reasons recorded).`

- [harness-v1.4.1.md](harness-v1.4.1.md) · sha256 `c8797e916ce6474bdf631f121d1e2640828ed21461c4fc5028ceb45c8c2d58b0`
- [harness-v1.4.1.json](harness-v1.4.1.json) · sha256 `b50462ed44d3edd2f26f7820071e13717905f99b8e991b0269967d692cacbfc3`

## `harness-v1.4.2` — EXPLORATORY

> `EXPLORATORY — did not pass its pre-registered gate. a: 1/4, c: 0 citations (15 attempts consulted, 51 refs, 15 reasons recorded).`

- [harness-v1.4.2.md](harness-v1.4.2.md) · sha256 `ad7429f7883e64acfa7edc0aa3465a4418fa93fd3c9b5aeec7a234f320a5699f`
- [harness-v1.4.2.json](harness-v1.4.2.json) · sha256 `9bf817b56b4d73921bc80d36231021b9296603096c961fbddd093677aa21ff2a`

## Tags

- `API-REPORTED` (formerly MEASURED): a stored field of a committed record, or a count or sum of such fields. A dollar figure with this tag is the sandbox API's reported operation cost, not account billing (`D-36`, open).
- `ESTIMATED`: flagged as an estimate by the cost guard itself.
- `DERIVED`: parsed from event text or a cost_events note; the source line is quoted verbatim with its record id.
- `BILLED`: an account-balance reading taken by the owner. It is used only on the explicit BILLED lines of `summary.json` (`ledger.billed`), never on an API cost.

## Summary

Headline counts, the defect register and the cost ledger (with its BILLED lines), each number with its tag and its records.

- [summary.json](summary.json) · sha256 `a1dde28c969c573abb399d708d30c62101e115d5ecea69a2ccb52a376558f653`
