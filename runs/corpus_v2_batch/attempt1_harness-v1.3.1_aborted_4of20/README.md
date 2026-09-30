# attempt 1 (harness-v1.3.1), aborted at 4/20

CONTROL arm, started 2026-09-30 10:34Z, stopped by the operator's stop rule after entry 4 (spend $0.47).
Not results; not used in any number. Evidence for METHODOLOGY "Attempt 1: two runner defects found by the attribution audit".
Records are under control/.

- 01 power_laws_deep_ensembles: BLOCKED, undeclared `tabulate` (REPO): correct.
- 02 DeformableFriends/NeuralTracking: INVALID_HARNESS, in-sandbox download route exit 97 (harness defect).
- 03 vmtl: BLOCKED, `patchelf: getting info about '--clear-execstack'` classified DATA_MISSING/REPO (runner defect charged to the repo).
- 04 img-comp-reference: BLOCKED, torchvision missing (ENV): runner installed torch only.
- The driver crashed once (UnicodeEncodeError on U+FFFD echoed to a cp1252 stdout) and was relaunched with PYTHONUTF8=1
  (driver_20260930T103422Z.log = first driver, driver_20260930T103958Z.log = relaunch).
