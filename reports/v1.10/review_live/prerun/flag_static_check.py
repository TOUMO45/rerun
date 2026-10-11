"""Offline: what harness-v1.10.0's static checks (behaviour.candidate_findings, the flag) say about plausible honest repairs of M-FAC's
next failure after the CPU shim (nn.parallel.parallel_apply on a CPU-only torch), and about the recorded harness-v1.5.2 LU patch."""
import json
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from app.services import behaviour  # noqa: E402

src = Path(sys.argv[2]).read_text(encoding="utf-8")
CMD = "CUDA_VISIBLE_DEVICES=0 python3 main_optim.py --model resnet20 --dataset DATASET --optim mfac --ngrads 512 --weightdecay .003 --batchsize 128 --save rn20-mfac.pth > rn20-mfac.txt"

SEQ_SET = src.replace(
    """        nn.parallel.parallel_apply(
            [f] * len(self.grads), list(range(len(self.gpus)))
        )
""", """        for i in range(len(self.gpus)):
            f(i)
""")
SEQ_ALL = SEQ_SET.replace(
    """        outputs = nn.parallel.parallel_apply(
            [f] * len(self.gpus), list(range(len(self.gpus)))
        )
        return sum(outputs)""", """        outputs = [f(i) for i in range(len(self.gpus))]
        return sum(outputs)""").replace(
    """        outputs = nn.parallel.parallel_apply(
            [f] * len(self.grads), self.grads
        )
        return torch.cat(outputs)""", """        outputs = [f(G) for G in self.grads]
        return torch.cat(outputs)""")
GUARD = src.replace(
    """import torch
import torch.nn as nn
""", """import torch
import torch.nn as nn

if not torch.cuda.is_available():
    def _sequential_apply(modules, inputs, kwargs_tup=None, devices=None):
        return [m(x) for m, x in zip(modules, inputs)]
    nn.parallel.parallel_apply = _sequential_apply
""")
LU_V152 = src.replace("self.giHig = torch.lu(self.giHig + diag, pivot=False)[0]", "self.giHig = torch.linalg.lu_factor(self.giHig + diag)[0]")

assert SEQ_SET != src and SEQ_ALL != SEQ_SET and GUARD != src and LU_V152 != src
out = {}
for name, new in (("sequential set_grad only", SEQ_SET), ("sequential, all three parallel_apply calls", SEQ_ALL),
                  ("module-level CPU fallback for parallel_apply", GUARD), ("pivoting LU (the kind of patch harness-v1.5.2 adopted)", LU_V152)):
    found = behaviour.candidate_findings({"optim.py": src}, {"optim.py": new}, command_before=CMD, command_after=CMD)
    out[name] = [{"reason": f.reason, "detail": f.detail[:160]} for f in found]
print(json.dumps(out, indent=1))
