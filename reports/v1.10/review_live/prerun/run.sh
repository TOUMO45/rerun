#!/bin/sh
# The local dry check of PLAN.md, Amendment 1 (no API call, no sandbox). Run in WSL from the folder prepare.py filled:
#   A  the documented command as written (no hook)                       = the run's baseline
#   B  the same, with harness-v1.10.0's cpu_shim loaded at start-up         = the time machine's cpu_shim step
#   C  B plus patch_c.py's sequential replacement of nn.parallel.parallel_apply (a plausible honest model patch), stopped at 75 s
# Each of A, B, C is a copy of IST-DASLab/M-FAC at 8116367; the command is the corpus entry's, verbatim.
D=$(cd "$(dirname "$0")" && pwd)
cd "$D/$1" || exit 9
if [ "$1" = A ]; then export PYTHONPATH="$D/stub"; else export PYTHONPATH="$D/shim:$D/stub"; fi
LIMIT=600
if [ "$1" = C ]; then LIMIT=75; fi
python3 --version >&2
timeout "$LIMIT" sh -c 'CUDA_VISIBLE_DEVICES=0 python3 main_optim.py --model resnet20 --dataset DATASET --optim mfac --ngrads 512 --weightdecay .003 --batchsize 128 --save rn20-mfac.pth > rn20-mfac.txt'
echo "EXIT $?" >&2
