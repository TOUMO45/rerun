"""Prepare a local, no-spend dry check of M-FAC's failure sequence under harness-v1.10.0 (run on Windows; the runs happen in WSL).

Writes into <out>:
  shim/rerun_cpu_shim.py + shim/sitecustomize.py  the EXACT cpu_shim source harness-v1.10.0 installs (runner_hooks._SOURCES), loaded at start-up like the .pth
  stub/torchvision/...                            a stand-in for torchvision ONLY (WSL has torch but no torchvision, and the 170 MB CIFAR-10 download cannot
                                                  be fetched over this machine's link): CIFAR10 returns 512 random 3x32x32 images; transforms pass tensors through.
The repository files are M-FAC at 8116367 (copied by the caller into <out>/repo)."""
import sys
from pathlib import Path

backend, out = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(backend))
from app.services import runner_hooks  # noqa: E402

shim = out / "shim"
shim.mkdir(parents=True, exist_ok=True)
(shim / "rerun_cpu_shim.py").write_text(runner_hooks._SOURCES[runner_hooks.CPU_SHIM], encoding="utf-8", newline="\n")
(shim / "sitecustomize.py").write_text("import rerun_cpu_shim\n", encoding="utf-8", newline="\n")

tv = out / "stub" / "torchvision"
tv.mkdir(parents=True, exist_ok=True)
(tv / "__init__.py").write_text("from . import datasets, transforms\n", encoding="utf-8", newline="\n")
(tv / "transforms.py").write_text('''
class _Pass:
    def __init__(self, *a, **k):
        pass

    def __call__(self, x):
        return x


class Compose(_Pass):
    pass


ToTensor = Normalize = RandomCrop = RandomHorizontalFlip = Resize = CenterCrop = RandomResizedCrop = Pad = _Pass
''', encoding="utf-8", newline="\n")
(tv / "datasets.py").write_text('''
import sys
import torch


class _Random(torch.utils.data.Dataset):
    """DRY-RUN STAND-IN: no download; random CIFAR-shaped data."""

    def __init__(self, root=None, train=True, download=False, transform=None, classes=10, n=512, shape=(3, 32, 32), **k):
        sys.stderr.write("DRYRUN_STUB_DATASET %s root=%r train=%s download=%s\\n" % (type(self).__name__, root, train, download))
        g = torch.Generator().manual_seed(0 if train else 1)
        self.x = torch.randn((n,) + shape, generator=g)
        self.y = torch.randint(0, classes, (n,), generator=g)

    def __len__(self):
        return len(self.y)

    def __getitem__(self, i):
        return self.x[i], int(self.y[i])


class CIFAR10(_Random):
    pass


class CIFAR100(_Random):
    def __init__(self, *a, **k):
        super().__init__(*a, classes=100, **k)


class MNIST(_Random):
    def __init__(self, *a, **k):
        super().__init__(*a, shape=(1, 28, 28), **k)


class ImageFolder(_Random):
    pass
''', encoding="utf-8", newline="\n")
print("prepared", out)
