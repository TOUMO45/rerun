# Diagnosis re-generated from the records (harness-v1.8, Phase 2 item a)

Answer key: `diagnosis_key.json`, committed before `backend/app/services/diagnosis.py` existed. Script: `check_diagnosis.py`. The 14 entries are the blocker records among the 21 held-out entries, now DEV-CONTAMINATED.

**Was wrong, now right: 9 of 9. Was right, still right: 5 of 5.** The key rejects the old stored text for 9 of the 9 (so the key and my triage judgement agree). Error line verbatim in the record's own output: all.

| entry | was | new cause | new right | fixable_by (old -> new) |
|---|---|---|---|---|
| E-T1 power_laws_deep_ensembles | was_wrong | `VENDORED_MODULE_MISSING` (evidence) | yes | deterministic -> human |
| E-T2 NeuralTracking | was_wrong | `DOCKER_REQUIRED` (evidence) | yes | model -> platform |
| E-T6 rocgan | was_wrong | `DOCUMENTED_COMMAND_REJECTED` (evidence) | yes | model -> human |
| E-T19 RBP | was_wrong | `REPO_EXTENSION_NOT_BUILT` (evidence) | yes | deterministic -> human |
| E-TB1 Ordered-Neurons | was_wrong | `NLTK_RESOURCE_LICENSED` (evidence) | yes | model -> human |
| E-TB5 cwn | was_wrong | `CONDA_REQUIRED` (evidence) | yes | deterministic -> human |
| E-TB7 Hindsight-Goal-Generation | was_wrong | `MUJOCO_LIBRARY_MISSING` (evidence) | yes | deterministic -> human |
| E-O2 fb_friend_list_scraper | was_wrong | `ERA_PAIR_MISMATCH` (evidence) | yes | deterministic -> human |
| E-O4 openstreetmap-heatmap | was_wrong | `EMBEDDED_RUNTIME_REQUIRED` (evidence) | yes | deterministic -> human |
| E-T13 neo_gnns | was_right | `SYSTEM_PACKAGE_MISSING` (evidence) | yes | deterministic -> deterministic |
| E-T20 fashion-retrieval | was_right | `DATA_MISSING` (class_default) | yes | human -> human |
| E-TB2 ovis | was_right | `PRERELEASE_PIN_UNAVAILABLE` (evidence) | yes | deterministic -> deterministic |
| E-TB3 video_prediction | was_right | `GIT_PROTOCOL_RETIRED` (evidence) | yes | deterministic -> deterministic |
| E-TB8 gandissect | was_right | `SYSTEM_PACKAGE_MISSING` (evidence) | yes | deterministic -> deterministic |

## Texts, entry by entry

### E-T1 power_laws_deep_ensembles (was_wrong; new text judged right)

- old: nothing, if the era lock resolves it; otherwise the exact release of curves the authors used
- new: the module `curves`, which the code imports although the repository does not contain it (the gate admitted `add curves`, so no file or package of that name is in the tree), and the PyPI project of that name (0.1.5, 0.1.6) did not install (SyntaxError: invalid syntax): it is a different, unrelated or unbuildable package, not what the code means
- next action: supply `curves` (a `curves.py` or a `curves/` package) from the project this code was derived from and put it where the importing file can see it; do not pip-install the PyPI name `curves`
- error line: `ModuleNotFoundError: No module named 'curves'`

### E-T2 NeuralTracking (was_wrong; new text judged right)

- old: a code change; the repairer proposes one and the tamper gate decides
- new: a machine with Docker: the documented command's script `start_nnrt.sh` runs `docker`, and this sandbox has no Docker client and no daemon to connect to
- next action: run the documented command on a host with Docker installed, or run the steps the script performs without the container
- error line: `start_nnrt.sh: 27: docker: not found`

### E-T6 rocgan (was_wrong; new text judged right)

- old: a code change; the repairer proposes one and the tamper gate decides
- new: a command its own argument parser accepts: the documented command was refused (`train_mn.py: error: unrecognized arguments: --config jobs/rocgan/iclr_5layer_rocgan_super.yml`); the script (`train_mn.py`) defines `--config_path`, not `--config`
- next action: correct the command in the README to use `--config_path` instead of `--config`, or add `--config` as an alias in the script's argument parser
- error line: `train_mn.py: error: unrecognized arguments: --config jobs/rocgan/iclr_5layer_rocgan_super.yml`

### E-T19 RBP (was_wrong; new text judged right)

- old: nothing, if the era lock resolves it; otherwise the exact release of operators._ext the authors used
- new: `operators._ext`: `operators` is the repository's own package, and `operators._ext` is not in its tree: it is a module the repository builds itself (the gate refused to install an unrelated PyPI package named `operators`)
- next action: run the repository's own build step for `operators._ext` (look for a build script in `operators/`, a `setup.sh` or Makefile, or `python setup.py build_ext --inplace` in its README) before the command
- error line: `ModuleNotFoundError: No module named 'operators._ext'`

### E-TB1 Ordered-Neurons (was_wrong; new text judged right)

- old: a code change; the repairer proposes one and the tamper gate decides
- new: NLTK data resource `ptb`, which is the Penn Treebank (Linguistic Data Consortium, licensed): NLTK's downloadable `ptb` package is only a stub for it, so a download cannot supply it
- next action: obtain the licensed corpus and place it under `nltk_data/corpora/ptb`, or use the data files the repository ships, if it ships any
- error line: `Resource ptb not found.`

### E-TB5 cwn (was_wrong; new text judged right)

- old: nothing, if the era lock resolves it; otherwise the exact release of graph_tool the authors used
- new: a conda environment: the documented command calls `conda`, which this sandbox does not have, and `graph_tool` has no distribution on PyPI (pip lists no versions for it), so pip cannot stand in for conda
- next action: create the conda environment the authors describe (their install script or environment file) outside the sandbox, or install `graph_tool` from the channel the authors name
- error line: `graph-tool_install.sh: 3: conda: not found`

### E-TB7 Hindsight-Goal-Generation (was_wrong; new text judged right)

- old: nothing, if the era lock resolves it; otherwise the exact release of mujoco_py the authors used
- new: the MuJoCo physics library 2.0: mujoco-py provides only the Python bindings and expected the library at `/root/.mujoco/mujoco200`
- next action: install MuJoCo under `~/.mujoco`: mujoco-py 2.0.x expects `mujoco200`; mujoco-py 2.1.x expects `mujoco210`, the MuJoCo 2.1.0 binaries, which are free to download (https://github.com/deepmind/mujoco/releases/tag/2.1.0)
- error line: `You appear to be missing MuJoCo.  We expected to find the file here: /root/.mujoco/mujoco200`

### E-O2 fb_friend_list_scraper (was_wrong; new text judged right)

- old: nothing, if the era lock or a removed-API row resolves it; otherwise the release of OpenSSL the authors used (older or newer)
- new: a matched set of versions: the newest `pyOpenSSL` removed the name the code uses (`AttributeError: module 'OpenSSL.SSL' has no attribute 'SSLv2_METHOD'. Did you mean: 'SSLv23_METHOD'?`); pinning `pyOpenSSL==19.1.0` (attempt 3) moved the error to `AttributeError: module 'lib' has no attribute 'GEN_EMAIL'`, which comes from `OpenSSL`'s own binding to the library it wraps, so `pyOpenSSL` has to be pinned together with that library's release of the same era
- next action: pin `pyOpenSSL` together with the release of the library it wraps that the authors' era had (the record shows `pyOpenSSL==19.1.0` alone is not enough), then re-run
- error line: `AttributeError: module 'OpenSSL.SSL' has no attribute 'SSLv2_METHOD'. Did you mean: 'SSLv23_METHOD'?`

### E-O4 openstreetmap-heatmap (was_wrong; new text judged right)

- old: nothing, if the era lock or a removed-API row resolves it; otherwise the release of bpy the authors used (older or newer)
- new: Blender: `bpy` is Blender's embedded Python API; the script has to run inside Blender of the release it targets, and a `bpy` installed from PyPI is not necessarily that release (or any Blender at all) (here `bpy.app.version` is None, which is what the stand-in reports)
- next action: run the script with Blender, for example `blender --background --python <script>.py`, using a Blender release the script supports
- error line: `AttributeError: module 'bpy.ops.object' has no attribute 'select_by_layer'. Did you mean: 'select_by_type'?`

### E-T13 neo_gnns (was_right; new text judged right)

- old: nothing, if the apt rule adds the build dependencies; otherwise a wheel of the package for this platform
- new: nothing: the system package `build-essential` provides `g++` (the C/C++ compiler); RERUN's harness-v1.8 apt rule installs it
- next action: install `build-essential` with apt before the build (`apt-get install -y build-essential`). RERUN's own spend cap then stopped the run in a later operation (a sandbox operation reached its budget-derived limit of 257s; not resumed: $0.0000 left funds 0s, below one operation (80s)), so the effect of the step above was not seen: re-run with a larger per-entry budget to see it
- error line: `subprocess.CalledProcessError: Command '['which', 'g++']' returned non-zero exit status 1.`

### E-T20 fashion-retrieval (was_right; new text judged right)

- old: the dataset the repository expects at caption_models/infos_best.pkl, obtained as its README describes
- new: the dataset the repository expects at caption_models/infos_best.pkl, obtained as its README describes
- next action: the dataset the repository expects at caption_models/infos_best.pkl, obtained as its README describes
- error line: `FileNotFoundError: [Errno 2] No such file or directory: 'caption_models/infos_best.pkl'`

### E-TB2 ovis (was_right; new text judged right)

- old: nothing, if the era lock resolves it; otherwise the exact release of torchvision the authors used
- new: nothing: the pin `torchvision==0.6.0a0` names a pre-release that was never published to the index; its final release is `0.6.0`, which RERUN's harness-v1.8 rule pins instead (labelled a dependency change)
- next action: pin `torchvision==0.6.0` (the final release of the pre-release the repository names)
- error line: `ERROR: Could not find a version that satisfies the requirement torchvision==0.6.0a0 (from versions: 0.1.6, 0.1.7, 0.1.8, 0.1.9, 0.2.0, 0.2.1, 0.2.2, 0.2.2.post2, 0.2.2.post3, 0.3.0, 0.4.0, 0.4.0+cpu, 0.4.1, 0.4.1+cpu, 0.4.2, 0.4.2+cpu, 0.5.0, 0.5.0+cpu, 0.6.0, 0.6.0+cpu, 0.6.1, 0.6.1+cpu, 0.7.0, 0.7`

### E-TB3 video_prediction (was_right; new text judged right)

- old: nothing, if the apt rule adds the build dependencies; otherwise a wheel of the package for this platform
- new: the requirement written with `https://` instead of `git://`: GitHub switched off the unauthenticated git:// protocol in March 2022, so a `git+git://github.com/...` line cannot be cloned (RERUN's harness-v1.8 rewrites it in its own copy and installs `git`)
- next action: change `git+git://github.com/` to `git+https://github.com/` in the requirements file (and install `git`, which pip needs for a `git+` requirement)
- error line: `fatal: unable to connect to github.com:`

### E-TB8 gandissect (was_right; new text judged right)

- old: nothing, if the apt rule resolves it; otherwise the system package that provides ft2build.h
- new: nothing: the system package `libfreetype6-dev` provides `ft2build.h`; RERUN's harness-v1.8 apt rule installs it
- next action: install `libfreetype6-dev` with apt before the build (`apt-get install -y libfreetype6-dev`)
- error line: `src/checkdep_freetype2.c:1:10: fatal error: ft2build.h: No such file or directory`
