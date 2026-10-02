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
import types
import uuid as uuidlib

from app.services import sandbox


SDK_DEFAULT_OUTPUT_LIMIT = 65535  # contree_sdk ContreeConfig.default_truncate_output_at (v0.3.6)


def _cut(text: str, limit: int) -> tuple[str, bool]:
    """The START of the stream up to `limit` bytes, as the API returns it, and whether it cut anything (harness-v1.4.3-rc, D-41)."""
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text, False
    return data[:limit].decode("utf-8", "ignore"), True


class Result:
    def __init__(self, code, stdout="", stderr="", cost=0.01, seconds=2.0, limit=None, timed_out=False, max_rss=None):
        self.exit_code, self.stdout, self.stderr, self.cost = code, stdout, stderr, cost
        self.elapsed_time = datetime.timedelta(seconds=seconds)
        if limit is not None or timed_out or max_rss is not None:
            # a real result carries the raw API record: each stream's `truncated` flag and the step's `timed_out`
            out_cut = err_cut = False
            if limit is not None:
                self.stdout, out_cut = _cut(stdout, limit)
                self.stderr, err_cut = _cut(stderr, limit)
            raw = types.SimpleNamespace(stdout=types.SimpleNamespace(truncated=out_cut), stderr=types.SimpleNamespace(truncated=err_cut),
                                        state=types.SimpleNamespace(timed_out=timed_out), resources=types.SimpleNamespace(max_rss=max_rss))
            self._raw = types.SimpleNamespace(result=raw)


class FakeCloud:
    def __init__(self, behaviour=None, costs: dict | None = None, seconds: dict | None = None, stops: tuple = ()):
        self.images: dict[str, dict] = {}
        self.ran: list[str] = []
        self.reopened: list[str] = []
        self.cleaned: list[str] = []
        self.behaviour = behaviour
        self.costs = costs or {}
        self.seconds = seconds or {}
        self.output_limit = None  # set when the runner builds its client: what ContreeConfig asked for (None = no client yet)
        self.max_rss = None  # the peak-memory figure the fake API returns for every step (None: the raw result has no usable figure)
        self.stops = tuple(stops)  # a command containing one of these is stopped by the sandbox at its limit: a normal result with state.timed_out (D-17)

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
        stopped = any(key in shell for key in cloud.stops)
        if stopped:
            code, stdout, stderr = -1, "", ""
        out = Image(cloud, None) if disposable else cloud.new_image((*self.state["built"], shell), files)
        out.result = Result(code, stdout=stdout, stderr=stderr, cost=cost, seconds=seconds, limit=cloud.output_limit, timed_out=stopped, max_rss=cloud.max_rss)
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
            # the real client applies `default_truncate_output_at` to every run; the SDK's own default is 65,535 bytes
            cloud.output_limit = getattr(config, "default_truncate_output_at", SDK_DEFAULT_OUTPUT_LIMIT)

    monkeypatch.setattr(sandbox, "ContreeSync", _Client)
    return cloud
