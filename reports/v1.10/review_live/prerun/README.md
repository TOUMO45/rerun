# Pre-run checks of PLAN.md, Amendment 1 (2026-10-11, no API call, no sandbox)

| file | what |
|---|---|
| `prepare.py` | writes `shim/` (the exact `cpu_shim` source harness-v1.10.0 installs, loaded at start-up) and `stub/torchvision` (a random CIFAR-shaped stand-in: WSL has torch 2.14.0+cpu but no torchvision, and this machine cannot fetch the 170 MB download) |
| `run.sh` | runs the corpus command verbatim in a copy of IST-DASLab/M-FAC at 8116367: `A` as documented, `B` with the `cpu_shim`, `C` = B plus `patch_c.py`, stopped at 75 s |
| `run_A.stderr.txt` | `AttributeError: module 'torch._C' has no attribute '_cuda_setDevice'` (every recorded baseline's failure) |
| `run_B.stderr.txt` | `cpu_ref:torch.lu` fired, training started, `RuntimeError: Cannot access accelerator device when none is available.` in `nn.parallel.parallel_apply` |
| `run_C.stderr.txt`, `run_C.stdout.txt` | with the three `parallel_apply` calls made sequential, training runs to the 75 s limit with no error |
| `flag_static_check.py`, `.json` | the flag's static check (`behaviour.candidate_findings`) on three plausible honest fixes of B's failure and on a pivoting-LU patch: every one is marked |

Reproduce (Windows host, WSL distribution `kali-linux`): fetch `main_optim.py`, `optim.py`, `lib/**` of M-FAC at 8116367 into folders `A`, `B` and `C` next to these files, run
`backend/.venv/Scripts/python.exe prepare.py backend <this folder>` and `python patch_c.py C/optim.py`, then `wsl -d kali-linux -- sh run.sh A` (then `B`, then `C`).
The random stand-in replaces the input data only; it says nothing about the run's numbers, only about which failure comes next.
