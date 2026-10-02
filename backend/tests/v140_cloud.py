"""Test double for harness-v1.4.0-rc: a fake Token Factory Sandboxes cloud behind the REAL sandbox runner.

`install(monkeypatch, behaviour)` replaces `sandbox.ContreeSync` so `sandbox.run_build_and_execute` runs unchanged against images that
behave like ConTree snapshots: every non-disposable run makes a new image (id -> the commands that built it, its files), an image can
be reopened by id, and every command run is counted. `behaviour(shell, built, files)` decides the outcome of a command from what the
image contains, so a test states "the run passes once the CPU shim is installed" instead of scripting call order. No network.

harness-v1.4.3-rc: like the real client, each fake client applies its own `default_truncate_output_at` (the SDK's default is 65,535 bytes) to every run it makes, cutting each
stream at that many BYTES (a cut may split a multi-byte character) and carrying the raw API record's `truncated` flags; a run asked for text (the SDK's default) raises
UnicodeDecodeError inside `.wait()` when the cut splits a character, a run asked for bytes (`stdout=bytes, stderr=bytes`) gets the cut stream undecoded.
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


def _cut_bytes(text: str, limit: int) -> tuple[bytes, bool]:
    """The START of the stream up to `limit` bytes, as the API returns it, and whether it cut anything (harness-v1.4.3-rc, D-41)."""
    data = text.encode("utf-8")
    return (data, False) if len(data) <= limit else (data[:limit], True)


class Result:
    def __init__(self, code, stdout="", stderr="", cost=0.01, seconds=2.0, limit=None, timed_out=False, max_rss=None, as_bytes=False):
        self.exit_code, self.stdout, self.stderr, self.cost = code, stdout, stderr, cost
        self.elapsed_time = datetime.timedelta(seconds=seconds)
        if limit is not None or timed_out or max_rss is not None:
            # a real result carries the raw API record: each stream's `truncated` flag and the step's `timed_out`
            out_cut = err_cut = False
            if limit is not None:
                (out, out_cut), (err, err_cut) = _cut_bytes(stdout, limit), _cut_bytes(stderr, limit)
                if as_bytes:
                    self.stdout, self.stderr = out, err
                else:
                    self.stdout, self.stderr = out.decode("utf-8"), err.decode("utf-8")  # strict, like the SDK's default text decoding
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
        self.output_limit = None  # the limit of the client the runner built last: what its ContreeConfig asked for (None = no client yet)
        self.max_rss = None  # the peak-memory figure the fake API returns for every step (None: the raw result has no usable figure)
        self.stops = tuple(stops)  # a command containing one of these is stopped by the sandbox at its limit: a normal result with state.timed_out (D-17)

    def new_image(self, built: tuple, files: dict, limit=None) -> "Image":
        image_id = str(uuidlib.uuid4())
        self.images[image_id] = {"built": built, "files": dict(files)}
        return Image(self, image_id, limit=limit)

    def count(self, command: str) -> int:
        return sum(1 for c in self.ran if c == command)


class Image:
    def __init__(self, cloud: FakeCloud, image_id: str | None, base: str | None = None, limit=None):
        self.cloud, self.uuid, self.base = cloud, image_id, base
        self.limit = limit  # the output limit of the CLIENT that made this image (each real client has its own config)
        self.result, self.exit_code, self._decode_error = None, 0, None

    @property
    def state(self) -> dict:
        if self.uuid is None:
            return {"built": (f"FROM {self.base}",), "files": {}}
        return self.cloud.images[self.uuid]

    def apply_files(self, files):
        merged = dict(self.state["files"])
        merged.update({name: bytes(data) for name, data in files.items()})
        return self.cloud.new_image(self.state["built"], merged, limit=self.limit)

    def run(self, shell, timeout, disposable, preserve_env=False, stdout=None, stderr=None):
        cloud = self.cloud
        as_bytes = stdout is bytes and stderr is bytes
        if shell == "true" and disposable:
            cloud.cleaned.append(self.uuid)
            out = Image(cloud, None, limit=self.limit)
            out.result = Result(0, cost=0.0)
            return out
        cloud.ran.append(shell)
        files = dict(self.state["files"])
        code, out_text, err_text = 0, "", ""
        if shell.startswith("tar -xpf " + sandbox.BRANCH_ARCHIVE):
            out_text = _apply_branch(files)
            outcome = cloud.behaviour(shell, self.state["built"], files) if cloud.behaviour is not None else None
            if outcome is not None:
                code, out_text, err_text = outcome
        elif shell.startswith("tar -xpf " + sandbox.UPLOAD_ARCHIVE):
            tar = tarfile.open(fileobj=io.BytesIO(files.pop(sandbox.UPLOAD_ARCHIVE)))
            files.update({m.name: tar.extractfile(m).read() for m in tar.getmembers()
                          if m.isfile() and not m.name.startswith(sandbox.UPLOAD_DIR)})
        elif cloud.behaviour is not None:
            outcome = cloud.behaviour(shell, self.state["built"], files)
            if outcome is not None:
                code, out_text, err_text = outcome
        cost = next((c for key, c in cloud.costs.items() if key in shell), 0.01)
        seconds = next((s for key, s in cloud.seconds.items() if key in shell), 2.0)
        stopped = any(key in shell for key in cloud.stops)
        if stopped:
            code, out_text, err_text = -1, "", ""
        out = Image(cloud, None, limit=self.limit) if disposable else cloud.new_image((*self.state["built"], shell), files, limit=self.limit)
        try:
            out.result = Result(code, stdout=out_text, stderr=err_text, cost=cost, seconds=seconds, limit=self.limit, timed_out=stopped, max_rss=cloud.max_rss,
                                as_bytes=as_bytes)
        except UnicodeDecodeError as exc:  # the SDK raises it inside `.wait()`; the finished operation's result is lost with it
            out._decode_error = exc
        out.exit_code = code
        return out

    def wait(self):
        if self._decode_error is not None:
            raise self._decode_error
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
        def __init__(self, limit):
            self.limit = limit

        def docker(self, name):
            return Image(cloud, None, base=name, limit=self.limit)

        def use(self, ref, strict=False):
            if strict and str(ref) not in cloud.images:
                raise RuntimeError(f"no image {ref}")
            cloud.reopened.append(str(ref))
            return Image(cloud, str(ref), limit=self.limit)

    class _Client:
        def __init__(self, config=None):
            # the real client applies `default_truncate_output_at` to every run it makes; the SDK's own default is 65,535 bytes
            limit = getattr(config, "default_truncate_output_at", SDK_DEFAULT_OUTPUT_LIMIT)
            self.images = _Images(limit)
            cloud.output_limit = limit

    monkeypatch.setattr(sandbox, "ContreeSync", _Client)
    return cloud
