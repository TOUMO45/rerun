"""Test double for harness-v1.4.0-rc: a fake Token Factory Sandboxes cloud behind the REAL sandbox runner.

`install(monkeypatch, behaviour)` replaces `sandbox.ContreeSync` so `sandbox.run_build_and_execute` runs unchanged against images that
behave like ConTree snapshots: every non-disposable run makes a new image (id -> the commands that built it, its files), an image can
be reopened by id, and every command run is counted. `behaviour(shell, built, files)` decides the outcome of a command from what the
image contains, so a test states "the run passes once the CPU shim is installed" instead of scripting call order. No network.
"""

from __future__ import annotations

import datetime
import io
import json
import tarfile
import uuid as uuidlib

from app.services import sandbox


class Result:
    def __init__(self, code, stdout="", stderr="", cost=0.01, seconds=2.0):
        self.exit_code, self.stdout, self.stderr, self.cost = code, stdout, stderr, cost
        self.elapsed_time = datetime.timedelta(seconds=seconds)


class FakeCloud:
    def __init__(self, behaviour=None, costs: dict | None = None, seconds: dict | None = None):
        self.images: dict[str, dict] = {}
        self.ran: list[str] = []
        self.reopened: list[str] = []
        self.cleaned: list[str] = []
        self.behaviour = behaviour
        self.costs = costs or {}
        self.seconds = seconds or {}

    def new_image(self, built: tuple, files: dict) -> "Image":
        image_id = str(uuidlib.uuid4())
        self.images[image_id] = {"built": built, "files": dict(files)}
        return Image(self, image_id)

    def count(self, command: str) -> int:
        return sum(1 for c in self.ran if c == command)


class Image:
    def __init__(self, cloud: FakeCloud, image_id: str | None, base: str | None = None):
        self.cloud, self.uuid, self.base = cloud, image_id, base
        self.result, self.exit_code = None, 0

    @property
    def state(self) -> dict:
        if self.uuid is None:
            return {"built": (f"FROM {self.base}",), "files": {}}
        return self.cloud.images[self.uuid]

    def apply_files(self, files):
        merged = dict(self.state["files"])
        merged.update({name: bytes(data) for name, data in files.items()})
        return self.cloud.new_image(self.state["built"], merged)

    def run(self, shell, timeout, disposable, preserve_env=False):
        cloud = self.cloud
        if shell == "true" and disposable:
            cloud.cleaned.append(self.uuid)
            out = Image(cloud, None)
            out.result = Result(0, cost=0.0)
            return out
        cloud.ran.append(shell)
        files = dict(self.state["files"])
        code, stdout, stderr = 0, "", ""
        if shell.startswith("tar -xpf " + sandbox.BRANCH_ARCHIVE):
            stdout = _apply_branch(files)
            outcome = cloud.behaviour(shell, self.state["built"], files) if cloud.behaviour is not None else None
            if outcome is not None:
                code, stdout, stderr = outcome
        elif shell.startswith("tar -xpf " + sandbox.UPLOAD_ARCHIVE):
            tar = tarfile.open(fileobj=io.BytesIO(files.pop(sandbox.UPLOAD_ARCHIVE)))
            files.update({m.name: tar.extractfile(m).read() for m in tar.getmembers()
                          if m.isfile() and not m.name.startswith(sandbox.UPLOAD_DIR)})
        elif cloud.behaviour is not None:
            outcome = cloud.behaviour(shell, self.state["built"], files)
            if outcome is not None:
                code, stdout, stderr = outcome
        cost = next((c for key, c in cloud.costs.items() if key in shell), 0.01)
        seconds = next((s for key, s in cloud.seconds.items() if key in shell), 2.0)
        out = Image(cloud, None) if disposable else cloud.new_image((*self.state["built"], shell), files)
        out.result = Result(code, stdout=stdout, stderr=stderr, cost=cost, seconds=seconds)
        out.exit_code = code
        return out

    def wait(self):
        return self


def _apply_branch(files: dict) -> str:
    tar = tarfile.open(fileobj=io.BytesIO(files.pop(sandbox.BRANCH_ARCHIVE)))
    members = {m.name: tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()}
    spec = json.loads(members[f"{sandbox.BRANCH_DIR}/branch.json"])
    for path in spec["files"]:
        files[path] = members[f"{sandbox.BRANCH_DIR}/files/{path}"]
    for path in spec["deleted"]:
        files.pop(path, None)
    return "RERUN_BRANCH_APPLIED"


def install(monkeypatch, behaviour=None, **kwargs) -> FakeCloud:
    cloud = FakeCloud(behaviour, **kwargs)

    class _Images:
        def docker(self, name):
            return Image(cloud, None, base=name)

        def use(self, ref, strict=False):
            if strict and str(ref) not in cloud.images:
                raise RuntimeError(f"no image {ref}")
            cloud.reopened.append(str(ref))
            return Image(cloud, str(ref))

    class _Client:
        def __init__(self, config=None):
            self.images = _Images()

    monkeypatch.setattr(sandbox, "ContreeSync", _Client)
    return cloud
