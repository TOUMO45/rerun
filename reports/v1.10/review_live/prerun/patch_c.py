"""Run C of the dry check: replace M-FAC's three nn.parallel.parallel_apply calls in optim.py by sequential calls (the same functions, the same order).
A stand-in for a plausible honest model patch of the failure run B ends on; not a patch the harness proposed.

    python patch_c.py <copy>/optim.py
"""
import sys

path = sys.argv[1]
src = open(path, encoding="utf-8").read()
new = src.replace("""        nn.parallel.parallel_apply(
            [f] * len(self.grads), list(range(len(self.gpus)))
        )
""", """        for i in range(len(self.gpus)):
            f(i)
""").replace("""        outputs = nn.parallel.parallel_apply(
            [f] * len(self.gpus), list(range(len(self.gpus)))
        )""", """        outputs = [f(i) for i in range(len(self.gpus))]""").replace("""        outputs = nn.parallel.parallel_apply(
            [f] * len(self.grads), self.grads
        )""", """        outputs = [f(G) for G in self.grads]""")
assert new.count("parallel_apply") == 0, "optim.py is not M-FAC at 8116367"
open(path, "w", encoding="utf-8", newline="\n").write(new)
print("patched", path)
