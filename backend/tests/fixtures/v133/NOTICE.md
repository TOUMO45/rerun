# Third-party material in these fixtures

The v1.3.3 tests replay source patches that the repair model proposed for 7 public research repositories (corpus-v2, v1.3.2 TREATMENT records). Each case
needs the original file of its repository at the pinned commit. The licence of each repository was checked (LICENSE file in the pinned tree and the GitHub
licence API, 2026-09-30):

| repository | pinned commit | licence | original in git |
|---|---|---|---|
| https://github.com/IST-DASLab/M-FAC | `8116367fb537b48484e2e4bde24f11f42b117f8a` | **MIT**, Copyright (c) 2021 IST Austria Distributed Algorithms and Systems Lab | **yes**: `patches/e14_a*/original/main_optim.py` (byte-exact, unmodified) |
| https://github.com/nadiinchi/power_laws_deep_ensembles | `d0aaf2f309a833199cdca58b6459fd56b194c50c` | LICENSE headed "BSD 2-Clause License" with the disclaimer only and no grant text (GitHub: NOASSERTION): not cleared | no, fetched |
| https://github.com/autumn9999/vmtl | `e20022da842cd44c3e9566ee76c2f888e08b8e80` | none | no, fetched |
| https://github.com/damo-cv/img-comp-reference | `193fc9464d27fcd806d5288448628923b54a5a19` | none | no, fetched |
| https://github.com/edenton/svg | `3f19f0b581161614382b2d529f8d92c7d25999e5` | none | no, fetched |
| https://github.com/alevine0/patchSmoothing | `6bdd01cdedde97763f36953de768f2b68952689c` | UMD permission notice: non-commercial use only, no copying or redistribution | no, fetched |
| https://github.com/Haichao-Zhang/FeatureScatter | `77e9140d5112ace5ba60301c224868257434b3e6` | none | no, fetched |

The commits are those recorded in `patches/SOURCES.json` (authoritative).

Only permissive licences (MIT/BSD/Apache) are committed. For the others, `patches/SOURCES.json` holds the repository, the pinned commit, the git blob SHA-1 and
SHA-256 of each file, and `scripts/fetch_patch_fixtures.py` fetches them from GitHub into the gitignored `_fetched/` directory, refusing any file whose blob
differs from the recorded one. The tests that need them are marked `requires_network` and are skipped offline. `patches/*/diff.txt` is what the repair model
wrote (RERUN's own data) and `patches/*/meta.json` points back to the record it came from.

MIT License (M-FAC), as in the repository's LICENSE file: Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify,
merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the
condition that the above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software. THE SOFTWARE IS
PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
