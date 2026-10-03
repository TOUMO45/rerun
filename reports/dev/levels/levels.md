# Outcome ladder of the DEV and gate entries, from the committed records (offline; every figure is a count of stored fields)

TEST entries are absent by the firewall (rule F). Definitions are in `compute_levels.py`. FIRST_ERROR_CLEARED = the as-published failure was cleared by a later attempt,
with the origin of that attempt (`time_machine` / rule names = deterministic, no model call; `model` = a model proposal that passed the gate). ENV_RESOLVED = the last recorded
blocker is not a dependency or system-library error (the environment stopped being what blocks the run). ENTRYPOINT_RUNS = verdict RUNS_* (smoke criterion, as recorded).

| version | arm | records | FIRST_ERROR_CLEARED (by origin) | ENV_RESOLVED | ENTRYPOINT_RUNS | final blockers (class@phase: n) |
|---|---|---|---|---|---|---|
| harness-v1.3.2 | control | 12 | 0 () | 3 | 0 | DEP_MISSING@repo_run: 7, RUNTIME_ERROR_OTHER@repo_run: 3, DEP_UNPINNED_CONFLICT@runner_setup: 1, DEP_YANKED@runner_setup: 1 |
| harness-v1.3.2 | treatment | 12 | 7 (time_machine: 6, model: 1) | 8 | 0 | RUNTIME_ERROR_OTHER@repo_run: 4, RUNTIME_ERROR_OTHER@repo_install: 3, DEP_UNPINNED_CONFLICT@runner_setup: 1, DEP_YANKED@runner_setup: 1, RUNTIME_ERROR_OTHER@runner_setup: 1, DEP_YANKED@repo_install: 1, DEP_MISSING@repo_run: 1 |
| harness-v1.3.3 | smoke | 4 | 3 (time_machine: 3) | 4 | 1 | RUNTIME_ERROR_OTHER@repo_run: 2, RUNTIME_ERROR_OTHER@repo_install: 1 |
| harness-v1.3.4 | smoke | 4 | 3 (time_machine: 3) | 2 | 0 | RUNTIME_ERROR_OTHER@repo_run: 2, DEP_NOT_ON_PYPI@repo_install: 1, DEP_MISSING@repo_run: 1 |
| harness-v1.4.0 | gate | 4 | 3 (time_machine: 3) | 2 | 0 | RUNTIME_ERROR_OTHER@repo_run: 1, RUNTIME_ERROR_OTHER@repo_install: 1, SYS_LIB_MISSING@repo_install: 1, DEP_MISSING@repo_run: 1 |
| harness-v1.4.1 | gate | 4 | 4 (time_machine: 4) | 3 | 0 | RUNTIME_ERROR_OTHER@repo_run: 2, SYS_LIB_MISSING@repo_install: 1, GPU_REQUIRED@repo_run: 1 |
| harness-v1.4.2 | gate | 4 | 4 (time_machine: 4) | 4 | 1 | RUNTIME_ERROR_OTHER@repo_run: 2, RESOURCE_LIMIT@repo_run: 1 |
| harness-v1.4.3 | gate | 4 | 4 (time_machine: 4) | 4 | 0 | DATA_MISSING@repo_run: 1, RUNTIME_ERROR_OTHER@repo_install: 1, RUNTIME_ERROR_OTHER@repo_run: 1, RESOURCE_LIMIT@repo_run: 1 |
| harness-v1.5.0 | dev | 8 | 5 (time_machine: 3, model: 2) | 6 | 1 | RUNTIME_ERROR_OTHER@repo_run: 4, DEP_UNPINNED_CONFLICT@runner_setup: 1, DEP_YANKED@runner_setup: 1, RUNTIME_ERROR_OTHER@repo_install: 1 |
| harness-v1.5.1 | dev | 8 | 6 (time_machine: 5, model: 1) | 7 | 2 | RUNTIME_ERROR_OTHER@repo_run: 4, DEP_UNPINNED_CONFLICT@runner_setup: 1, RUNTIME_ERROR_OTHER@repo_install: 1 |

## Per record

| entry | version | arm | verdict | first error (class@phase) | cleared by | ENV_RESOLVED | final blocker | error |
|---|---|---|---|---|---|---|---|---|
| 03 | harness-v1.3.2 | control | BLOCKED | DEP_MISSING@repo_run | - | no | DEP_MISSING@repo_run (REPO) | `ModuleNotFoundError: No module named 'sklearn'` |
| 03 | harness-v1.3.2 | treatment | BLOCKED | DEP_MISSING@repo_run | time_machine | yes | RUNTIME_ERROR_OTHER@repo_run (REPO) | `17.6` |
| 03 | harness-v1.3.3 | smoke | BLOCKED | DEP_MISSING@repo_run | time_machine | yes | RUNTIME_ERROR_OTHER@repo_run (REPO) | `1` |
| 03 | harness-v1.3.4 | smoke | BLOCKED | DEP_MISSING@repo_run | time_machine | yes | RUNTIME_ERROR_OTHER@repo_run (REPO) | `1` |
| 03 | harness-v1.4.0 | gate | BLOCKED | DEP_MISSING@repo_run | time_machine | yes | RUNTIME_ERROR_OTHER@repo_run (REPO) | `1` |
| 03 | harness-v1.4.1 | gate | BLOCKED | DEP_MISSING@repo_run | time_machine | yes | RUNTIME_ERROR_OTHER@repo_run (REPO) | `1` |
| 03 | harness-v1.4.2 | gate | INDETERMINATE | DEP_MISSING@repo_run | time_machine | yes | RUNTIME_ERROR_OTHER@repo_run (REPO) | `1` |
| 03 | harness-v1.4.3 | gate | BLOCKED | DEP_MISSING@repo_run | time_machine | yes | DATA_MISSING@repo_run (REPO) | `FileNotFoundError: Caught FileNotFoundError in DataLoader worker process 0.` |
| 04 | harness-v1.3.2 | control | BLOCKED | RUNTIME_ERROR_OTHER@repo_run | - | yes | RUNTIME_ERROR_OTHER@repo_run (REPO) | `Exception: No GPU found, please run without --cuda` |
| 04 | harness-v1.3.2 | treatment | BLOCKED | RUNTIME_ERROR_OTHER@repo_run | - | yes | RUNTIME_ERROR_OTHER@repo_run (REPO) | `Exception: No GPU found, please run without --cuda` |
| 04 | harness-v1.5.0 | dev | BLOCKED | RUNTIME_ERROR_OTHER@repo_run | model | yes | RUNTIME_ERROR_OTHER@repo_run (REPO) | `SystemExit: 1` |
| 04 | harness-v1.5.1 | dev | BLOCKED | RUNTIME_ERROR_OTHER@repo_run | model | yes | RUNTIME_ERROR_OTHER@repo_run (REPO) | `NameError: name 'restore' is not defined` |
| 05 | harness-v1.3.2 | control | INDETERMINATE | DEP_UNPINNED_CONFLICT@runner_setup | - | no | DEP_UNPINNED_CONFLICT@runner_setup (ENV) | `ERROR: ResolutionImpossible: for help visit https://pip.pypa.io/en/latest/topics/dependency-resolution/#dealing-with-dependency-conflicts` |
| 05 | harness-v1.3.2 | treatment | INDETERMINATE | DEP_UNPINNED_CONFLICT@runner_setup | - | no | DEP_UNPINNED_CONFLICT@runner_setup (ENV) | `ERROR: ResolutionImpossible: for help visit https://pip.pypa.io/en/latest/topics/dependency-resolution/#dealing-with-dependency-conflicts` |
| 05 | harness-v1.5.0 | dev | INDETERMINATE | DEP_UNPINNED_CONFLICT@runner_setup | - | no | DEP_UNPINNED_CONFLICT@runner_setup (ENV) | `ERROR: ResolutionImpossible: for help visit https://pip.pypa.io/en/latest/topics/dependency-resolution/#dealing-with-dependency-conflicts` |
| 05 | harness-v1.5.1 | dev | INDETERMINATE | DEP_UNPINNED_CONFLICT@runner_setup | - | no | DEP_UNPINNED_CONFLICT@runner_setup (ENV) | `ERROR: ResolutionImpossible: for help visit https://pip.pypa.io/en/latest/topics/dependency-resolution/#dealing-with-dependency-conflicts` |
| 07 | harness-v1.3.2 | control | BLOCKED | DEP_MISSING@repo_run | - | no | DEP_MISSING@repo_run (REPO) | `ModuleNotFoundError: No module named 'numpy'` |
| 07 | harness-v1.3.2 | treatment | BLOCKED | DEP_MISSING@repo_run | time_machine | yes | RUNTIME_ERROR_OTHER@repo_install (REPO) | `× Encountered error while generating package metadata.` |
| 07 | harness-v1.3.3 | smoke | BLOCKED | DEP_MISSING@repo_run | time_machine | yes | RUNTIME_ERROR_OTHER@repo_install (REPO) | `× Encountered error while generating package metadata.` |
| 07 | harness-v1.3.4 | smoke | BLOCKED | DEP_MISSING@repo_run | time_machine | no | DEP_NOT_ON_PYPI@repo_install (REPO) | `ERROR: Could not find a version that satisfies the requirement gcc (from versions: none)` |
| 07 | harness-v1.4.0 | gate | BLOCKED | DEP_MISSING@repo_run | time_machine | yes | RUNTIME_ERROR_OTHER@repo_install (REPO) | `× Encountered error while generating package metadata.` |
| 07 | harness-v1.4.1 | gate | BLOCKED | DEP_MISSING@repo_run | time_machine | no | SYS_LIB_MISSING@repo_install (REPO) | `/bin/sh: 1: pkg-config: not found` |
| 07 | harness-v1.4.2 | gate | RUNS_AFTER_REPAIR | DEP_MISSING@repo_run | time_machine | yes | DEP_MISSING@repo_run (REPO) | `ModuleNotFoundError: No module named 'Box2D'` |
| 07 | harness-v1.4.3 | gate | BLOCKED | DEP_MISSING@repo_run | time_machine | yes | RUNTIME_ERROR_OTHER@repo_install (REPO) | `× Encountered error while generating package metadata.` |
| 08 | harness-v1.3.2 | control | BLOCKED | DEP_MISSING@repo_run | - | no | DEP_MISSING@repo_run (REPO) | `ModuleNotFoundError: No module named 'sklearn'` |
| 08 | harness-v1.3.2 | treatment | BLOCKED | DEP_MISSING@repo_run | model | yes | RUNTIME_ERROR_OTHER@repo_install (REPO) | `E: Package 'python3-distutils' has no installation candidate` |
| 08 | harness-v1.3.3 | smoke | INVALID_HARNESS | DEP_MISSING@repo_run | time_machine | yes | RUNTIME_ERROR_OTHER@repo_run (REPO) | `ImportError: cannot import name 'compare_psnr' from 'skimage.measure' (/usr/local/lib/python3.10/site-packages/skimage/measure/__init__.py)` |
| 08 | harness-v1.3.4 | smoke | INDETERMINATE | DEP_MISSING@repo_run | - | no | DEP_MISSING@repo_run (REPO) | `ModuleNotFoundError: No module named 'sklearn'` |
| 08 | harness-v1.4.0 | gate | INDETERMINATE | DEP_MISSING@repo_run | time_machine | no | SYS_LIB_MISSING@repo_install (REPO) | `[Errno 2] No such file or directory: 'gcc'` |
| 08 | harness-v1.4.1 | gate | BLOCKED | DEP_MISSING@repo_run | time_machine | yes | GPU_REQUIRED@repo_run (REPO) | `raise AssertionError("Torch not compiled with CUDA enabled")` |
| 08 | harness-v1.4.2 | gate | INDETERMINATE | DEP_MISSING@repo_run | time_machine | yes | RUNTIME_ERROR_OTHER@repo_run (REPO) | `ImportError: cannot import name 'compare_psnr' from 'skimage.metrics' (/usr/local/lib/python3.10/site-packages/skimage/metrics/__init__.py)` |
| 08 | harness-v1.4.3 | gate | BLOCKED | DEP_MISSING@repo_run | time_machine | yes | RUNTIME_ERROR_OTHER@repo_run (REPO) | `ImportError: cannot import name 'compare_psnr' from 'skimage.measure' (/usr/local/lib/python3.10/site-packages/skimage/measure/__init__.py)` |
| 09 | harness-v1.3.2 | control | INDETERMINATE | DEP_YANKED@runner_setup | - | no | DEP_YANKED@runner_setup (ENV) | `ERROR: Could not find a version that satisfies the requirement torch==1.2.0 (from versions: 1.11.0, 1.11.0+cpu, 1.12.0, 1.12.0+cpu, 1.12.1, ` |
| 09 | harness-v1.3.2 | treatment | INDETERMINATE | DEP_YANKED@runner_setup | - | no | DEP_YANKED@runner_setup (ENV) | `ERROR: Could not find a version that satisfies the requirement torch==1.2.0 (from versions: 1.11.0, 1.11.0+cpu, 1.12.0, 1.12.0+cpu, 1.12.1, ` |
| 09 | harness-v1.5.0 | dev | INDETERMINATE | DEP_YANKED@runner_setup | - | no | DEP_YANKED@runner_setup (ENV) | `ERROR: Could not find a version that satisfies the requirement torch==1.2.0 (from versions: 1.11.0, 1.11.0+cpu, 1.12.0, 1.12.0+cpu, 1.12.1, ` |
| 09 | harness-v1.5.1 | dev | INDETERMINATE | SYS_LIB_MISSING@repo_install | time_machine | yes | RUNTIME_ERROR_OTHER@repo_run (REPO) | `AssertionError: Download cifar10 dataset!!` |
| 11 | harness-v1.3.2 | control | BLOCKED | DEP_MISSING@repo_run | - | no | DEP_MISSING@repo_run (REPO) | `ModuleNotFoundError: No module named 'tqdm'` |
| 11 | harness-v1.3.2 | treatment | INDETERMINATE | DEP_MISSING@repo_run | time_machine | yes | RUNTIME_ERROR_OTHER@runner_setup (ENV) | `subprocess.CalledProcessError: Command '['/usr/local/bin/python', '-c', "import torch; print('RERUN_TORCH_OK', torch.__version__)"]' returne` |
| 11 | harness-v1.3.3 | smoke | RUNS_AFTER_REPAIR | DEP_MISSING@repo_run | - | yes | DEP_MISSING@repo_run (REPO) | `ModuleNotFoundError: No module named 'tqdm'` |
| 11 | harness-v1.3.4 | smoke | INDETERMINATE | DEP_MISSING@repo_run | time_machine | yes | RUNTIME_ERROR_OTHER@repo_run (REPO) | `UnboundLocalError: local variable 'torch' referenced before assignment` |
| 11 | harness-v1.4.0 | gate | INDETERMINATE | DEP_MISSING@repo_run | - | no | DEP_MISSING@repo_run (REPO) | `ModuleNotFoundError: No module named 'tqdm'` |
| 11 | harness-v1.4.1 | gate | BLOCKED | DEP_MISSING@repo_run | time_machine | yes | RUNTIME_ERROR_OTHER@repo_run (REPO) | `170499072it [00:20, 8225019.15it/s]` |
| 11 | harness-v1.4.2 | gate | INDETERMINATE | DEP_MISSING@repo_run | time_machine | yes | RESOURCE_LIMIT@repo_run (SANDBOX_QUOTA) | `exit code 137: the process was killed by SIGKILL (the shell printed 'Killed')` |
| 11 | harness-v1.4.3 | gate | INDETERMINATE | DEP_MISSING@repo_run | time_machine | yes | RESOURCE_LIMIT@repo_run (SANDBOX_QUOTA) | `exit code 137: the process was killed by SIGKILL (the shell printed 'Killed')` |
| 12 | harness-v1.3.2 | control | BLOCKED | DEP_MISSING@repo_run | - | no | DEP_MISSING@repo_run (REPO) | `ModuleNotFoundError: No module named 'tensorflow'` |
| 12 | harness-v1.3.2 | treatment | BLOCKED | DEP_MISSING@repo_run | time_machine | yes | RUNTIME_ERROR_OTHER@repo_install (REPO) | `E: Unable to locate package libnvinfer6` |
| 12 | harness-v1.5.0 | dev | BLOCKED | DEP_MISSING@repo_run | time_machine | yes | RUNTIME_ERROR_OTHER@repo_run (REPO) | `AttributeError: module 'tensorflow' has no attribute 'get_variable'` |
| 12 | harness-v1.5.1 | dev | BLOCKED | DEP_MISSING@repo_run | time_machine | yes | RUNTIME_ERROR_OTHER@repo_run (REPO) | `AttributeError: module 'tensorflow' has no attribute 'get_variable'` |
| 14 | harness-v1.3.2 | control | BLOCKED | RUNTIME_ERROR_OTHER@repo_run | - | yes | RUNTIME_ERROR_OTHER@repo_run (REPO) | `AttributeError: module 'torch._C' has no attribute '_cuda_setDevice'` |
| 14 | harness-v1.3.2 | treatment | BLOCKED | RUNTIME_ERROR_OTHER@repo_run | - | yes | RUNTIME_ERROR_OTHER@repo_run (REPO) | `AttributeError: module 'torch._C' has no attribute '_cuda_setDevice'` |
| 14 | harness-v1.5.0 | dev | BLOCKED | RUNTIME_ERROR_OTHER@repo_run | model | yes | RUNTIME_ERROR_OTHER@repo_run (REPO) | `RuntimeError: linalg.lu_factor: LU without pivoting is not implemented on the CPU` |
| 14 | harness-v1.5.1 | dev | BLOCKED | GPU_REQUIRED@repo_run | time_machine | yes | RUNTIME_ERROR_OTHER@repo_run (REPO) | `RuntimeError: Cannot access accelerator device when none is available.` |
| 15 | harness-v1.3.2 | control | BLOCKED | DEP_MISSING@repo_run | - | no | DEP_MISSING@repo_run (REPO) | `ModuleNotFoundError: No module named 'matplotlib'` |
| 15 | harness-v1.3.2 | treatment | INDETERMINATE | DEP_MISSING@repo_run | time_machine | no | DEP_YANKED@repo_install (REPO) | `ERROR: Could not find a version that satisfies the requirement dataclasses==0.8 (from versions: 0.1, 0.2, 0.3, 0.4, 0.5, 0.6)` |
| 15 | harness-v1.5.0 | dev | RUNS_AFTER_REPAIR | DEP_MISSING@repo_run | time_machine | yes | DEP_YANKED@repo_install (REPO) | `ERROR: Could not find a version that satisfies the requirement dataclasses==0.8 (from versions: 0.1, 0.2, 0.3, 0.4, 0.5, 0.6)` |
| 15 | harness-v1.5.1 | dev | RUNS_AFTER_REPAIR | DEP_MISSING@repo_run | time_machine | yes | DEP_YANKED@repo_install (REPO) | `ERROR: Could not find a version that satisfies the requirement dataclasses==0.8 (from versions: 0.1, 0.2, 0.3, 0.4, 0.5, 0.6)` |
| 16 | harness-v1.3.2 | control | BLOCKED | DEP_MISSING@repo_run | - | no | DEP_MISSING@repo_run (REPO) | `ModuleNotFoundError: No module named 'sklearn'` |
| 16 | harness-v1.3.2 | treatment | BLOCKED | DEP_MISSING@repo_run | time_machine | no | DEP_MISSING@repo_run (REPO) | `ModuleNotFoundError: No module named 'language_evaluation'` |
| 16 | harness-v1.5.0 | dev | BLOCKED | DEP_MISSING@repo_run | time_machine | yes | RUNTIME_ERROR_OTHER@repo_install (REPO) | `E: Failed to fetch http://security.debian.org/debian-security/pool/updates/main/g/glibc/libc-devtools_2.31-13%2bdeb11u14_amd64.deb  404  Not` |
| 16 | harness-v1.5.1 | dev | BLOCKED | DEP_MISSING@repo_run | time_machine | yes | RUNTIME_ERROR_OTHER@repo_install (REPO) | `E: Failed to fetch http://security.debian.org/debian-security/pool/updates/main/g/glibc/libc-devtools_2.31-13%2bdeb11u14_amd64.deb  404  Not` |
| 17 | harness-v1.3.2 | control | BLOCKED | RUNTIME_ERROR_OTHER@repo_run | - | yes | RUNTIME_ERROR_OTHER@repo_run (REPO) | `ImportError: cannot import name 'zero_gradients' from 'torch.autograd.gradcheck' (/usr/local/lib/python3.10/site-packages/torch/autograd/gra` |
| 17 | harness-v1.3.2 | treatment | BLOCKED | RUNTIME_ERROR_OTHER@repo_run | - | yes | RUNTIME_ERROR_OTHER@repo_run (REPO) | `ImportError: cannot import name 'zero_gradients' from 'torch.autograd.gradcheck' (/usr/local/lib/python3.10/site-packages/torch/autograd/gra` |
| 17 | harness-v1.5.0 | dev | INDETERMINATE | RUNTIME_ERROR_OTHER@repo_run | - | yes | RUNTIME_ERROR_OTHER@repo_run (REPO) | `ImportError: cannot import name 'zero_gradients' from 'torch.autograd.gradcheck' (/usr/local/lib/python3.10/site-packages/torch/autograd/gra` |
| 17 | harness-v1.5.1 | dev | RUNS_AFTER_REPAIR | RUNTIME_ERROR_OTHER@repo_run | - | yes | RUNTIME_ERROR_OTHER@repo_run (REPO) | `ImportError: cannot import name 'zero_gradients' from 'torch.autograd.gradcheck' (/usr/local/lib/python3.10/site-packages/torch/autograd/gra` |
