# REPLAY index

Offline, deterministic replay of the committed records, cross-checked against the passports. The pre-registered run is the anchor;
the exploratory versions sit beside it with their badges. Rebuild with `python -m phase_d.build_replay`; check with
`python -m phase_d.build_replay --check`.

## `harness-v1.3.2` — PRE-REGISTERED ANCHOR

> `PRE-REGISTERED — harness-v1.3.2 is the pre-registered CONTROL / TREATMENT run; not exploratory.`

- [harness-v1.3.2.md](harness-v1.3.2.md) · sha256 `40816d0cddce414e7b69b80c6caa24faf6c2d2ed737ab98e6166bcd8c252b072`
- [harness-v1.3.2.json](harness-v1.3.2.json) · sha256 `c1677d9b4db6e814476edbf1b4e829eb7cab005b5c79f31f74ce282b71ec01e2`

## `harness-v1.3.3` — EXPLORATORY

> `EXPLORATORY — did not pass its pre-registered gate. a: 1/4 (measured), c: 0 citations in 7 searches.`

- [harness-v1.3.3.md](harness-v1.3.3.md) · sha256 `d984e693cccf7d2f011588ee48e9f5ac659c8fbe04caf88277138c015fd97479`
- [harness-v1.3.3.json](harness-v1.3.3.json) · sha256 `d294c983afe64a51af21139526b9ab32b10218074ea1de48156687c0e5a913f6`

## `harness-v1.3.4` — EXPLORATORY

> `EXPLORATORY — did not pass its pre-registered gate. a: 0/4, c: 0 citations (7 attempts consulted, 21 refs, 6 reasons recorded).`

- [harness-v1.3.4.md](harness-v1.3.4.md) · sha256 `366a047b385630c6d6f01de22208017cf040b27535042f6607fd9385a531f0b0`
- [harness-v1.3.4.json](harness-v1.3.4.json) · sha256 `c15737d30b236dd19f20fb738984df4246ff4f4e52fec7ce3fd4036001901e93`

## `harness-v1.4.0` — EXPLORATORY

> `EXPLORATORY — did not pass its pre-registered gate. a: 0/4, c: 3 citations (24 attempts consulted, 72 refs, 15 reasons recorded).`

- [harness-v1.4.0.md](harness-v1.4.0.md) · sha256 `590ddcd2097e947a87f44c370b85a421cd9aff1589f7333d3780577692c3bf67`
- [harness-v1.4.0.json](harness-v1.4.0.json) · sha256 `88c237f326fa5a27bae922a826930aa9b8e1af6f0abc22bbc2b5010d86f171e0`

## `harness-v1.4.1` — EXPLORATORY

> `EXPLORATORY — did not pass its pre-registered gate. a: 0/4, c: 6 citations (36 attempts consulted, 108 refs, 28 reasons recorded).`

- [harness-v1.4.1.md](harness-v1.4.1.md) · sha256 `8b44fdda93543889889ec2e3be0022f2bd250512393b2c74fa2908b178978c3e`
- [harness-v1.4.1.json](harness-v1.4.1.json) · sha256 `ec5d2f66136064527313f1fcfd88bd3798f642c3c938d887880b44f24c5c611e`

## `harness-v1.4.2` — EXPLORATORY

> `EXPLORATORY — did not pass its pre-registered gate. a: 1/4, c: 0 citations (15 attempts consulted, 51 refs, 15 reasons recorded).`

- [harness-v1.4.2.md](harness-v1.4.2.md) · sha256 `31b234562693ffde248917720a450e738b95f90767a7c575c14b961de0d63186`
- [harness-v1.4.2.json](harness-v1.4.2.json) · sha256 `dfffbbe1011ff2da24c144af121a925157490362f27bb5edc83b3fd769fae539`

## `harness-v1.4.3` — EXPLORATORY

> `EXPLORATORY — did not pass its pre-registered gate. a: 0/4, c: 7 citations (27 attempts consulted, 81 refs, 17 reasons recorded).`

- [harness-v1.4.3.md](harness-v1.4.3.md) · sha256 `93a2d48a25ea615c737cc6a204f3bec649f8da9a26cc4a4eaf5c82e66ef608a7`
- [harness-v1.4.3.json](harness-v1.4.3.json) · sha256 `935b79aab45a2d4f9920f394c11c853783cbd4e73eb3c7154d1c9a28cdf03c06`

## Tags

- `API-REPORTED` (formerly MEASURED): a stored field of a committed record, or a count or sum of such fields. A dollar figure with this tag is the sandbox API's reported operation cost, not account billing (`D-36`, open).
- `ESTIMATED`: flagged as an estimate by the cost guard itself.
- `DERIVED`: parsed from event text or a cost_events note; the source line is quoted verbatim with its record id.
- `BILLED`: an account-balance reading taken by the owner. It is used only on the explicit BILLED lines of `summary.json` (`ledger.billed`), never on an API cost.

## Summary

Headline counts, the defect register and the cost ledger (with its BILLED lines), each number with its tag and its records.

- [summary.json](summary.json) · sha256 `7f5c16e70720ba6c6d5da3ce386e898f7b599d2c249dec880ca461ef73f9e67a`
