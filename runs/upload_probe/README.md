# Upload-cap probe records

| File | Status |
|---|---|
| `probe_2026-09-28.json` | First registered probe (150 / 500 MB). 150 MB uploaded but the sandbox operation failed with `OSError 28 'No space left on device'` → per its rule, no cap; led to amendment 1. |
| `void_probe_2026-09-28_amendment1_payload-bug.json` | **VOID** — first run of amendment 1. Stopped at 25 MB by a bug in the probe's own payload (`run.sh` had an unquoted `file(s)`, a `sh` syntax error), although that step's upload (17.3 s) and extract + verify (0.12 s) succeeded. **Not used for the cap or the throughput constant** (human decision). Payload fixed and tested; the probe is re-run from 25 MB per the registered rule. |
| `probe_2026-09-29_amendment1.json` | The re-run of amendment 1 that sets the cap and the throughput constant. |
