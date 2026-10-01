"""harness-v1.4.0-rc (D-23): checkpoint operations in the sandbox runner, against a fake SDK that models images as snapshots.

The fake keeps a registry of images (id -> the commands that built it and the files in it), counts every command run, and lets an
image be reopened by id, which is what the real contree_sdk offers (`images.use(uuid)`). No network.
"""

from __future__ import annotations

import datetime
import io
import json
import tarfile
import uuid as uuidlib

import pytest

from app.services import runner_env, runner_hooks, sandbox
from app.services.sandbox import Checkpoint


class _Result:
    def __init__(self, code, stdout="", stderr="", cost=0.01, seconds=2.0):
        self.exit_code, self.stdout, self.stderr, self.cost = code, stdout, stderr, cost
        self.elapsed_time = datetime.timedelta(seconds=seconds)


class FakeCloud:
    """Images are immutable snapshots: (commands that built it, files). Every non-disposable run makes a new id."""

    def __init__(self, fail_on: str | None = None, costs: dict | None = None):
        self.images: dict[str, dict] = {}
        self.ran: list[str] = []
        self.reopened: list[str] = []
        self.cleaned: list[str] = []
        self.fail_on = fail_on
        self.costs = costs or {}

    def new_image(self, built: tuple, files: dict) -> "_Image":
        image_id = str(uuidlib.uuid4())
        self.images[image_id] = {"built": built, "files": dict(files)}
        return _Image(self, image_id)


class _Image:
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
            out = _Image(cloud, None)
            out.result = _Result(0, cost=0.0)
            return out
        cloud.ran.append(shell)
        files = dict(self.state["files"])
        code, stdout = 0, ""
        if shell.startswith("tar -xpf " + sandbox.BRANCH_ARCHIVE):
            stdout = _apply_branch(files)
        if shell.startswith("tar -xpf " + sandbox.UPLOAD_ARCHIVE):
            tar = tarfile.open(fileobj=io.BytesIO(files.pop(sandbox.UPLOAD_ARCHIVE)))
            files.update({m.name: tar.extractfile(m).read() for m in tar.getmembers()
                          if m.isfile() and not m.name.startswith(sandbox.UPLOAD_DIR)})
        if cloud.fail_on and cloud.fail_on in shell:
            code = 1
        cost = next((c for key, c in cloud.costs.items() if key in shell), 0.01)
        if disposable:
            out = _Image(cloud, None)
        else:
            out = cloud.new_image((*self.state["built"], shell), files)
        out.result = _Result(code, stdout=stdout, cost=cost)
        out.exit_code = code
        out.ran_on = self
        return out

    def wait(self):
        return self


def _apply_branch(files: dict) -> str:
    """What apply.py does, on the fake filesystem: unpack the overlay and write/delete the files."""
    tar = tarfile.open(fileobj=io.BytesIO(files.pop(sandbox.BRANCH_ARCHIVE)))
    members = {m.name: tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()}
    spec = json.loads(members[f"{sandbox.BRANCH_DIR}/branch.json"])
    for path in spec["files"]:
        files[path] = members[f"{sandbox.BRANCH_DIR}/files/{path}"]
    for path in spec["deleted"]:
        files.pop(path, None)
    return "RERUN_BRANCH_APPLIED"


@pytest.fixture
def cloud(monkeypatch):
    c = FakeCloud()

    class _Images:
        def docker(self, name):
            return _Image(c, None, base=name)

        def use(self, ref, strict=False):
            if strict and str(ref) not in c.images:
                raise RuntimeError(f"no image {ref}")
            c.reopened.append(str(ref))
            return _Image(c, str(ref))

    class _Client:
        def __init__(self, config=None):
            self.images = _Images()

    monkeypatch.setattr(sandbox, "ContreeSync", _Client)
    return c


TORCH = runner_env.plan_torch_setup(["pip install torch==1.8.1"], None)
PLAN = ["pip install -r requirements.txt"]


def _run(cloud, checkpoint, *, install=PLAN, extras=(), upload=True):
    return sandbox.run_build_and_execute(
        api_key="k", base_image="python:3.9-slim", install_commands=install, execute_command="python main.py",
        wall_clock_seconds=600, upload_files={"main.py": b"print(1)\n", "requirements.txt": b"numpy\n"} if upload else None,
        torch_setup=TORCH, checkpoint=checkpoint, runner_extras=tuple(extras),
    )


def _torch_installs(cloud) -> int:
    return sum(1 for c in cloud.ran if c == TORCH.install_command)


def test_a_fresh_checkpoint_operation_keeps_the_tree_and_every_setup_layer(cloud):
    result = _run(cloud, Checkpoint(keep_layers=True))
    expected_setup = sandbox.setup_commands(PLAN, TORCH)
    assert result.setup_commands == expected_setup and result.ran_setup == expected_setup
    assert [ops for ops, _ in result.layers] == [expected_setup[:k] for k in range(len(expected_setup) + 1)]
    # kept images are never cleaned up; the command itself ran disposable
    assert not set(result.kept_images) & set(cloud.cleaned)
    assert result.branch_from_image is None and result.rerun_steps[0].phase == "rerun_extract"
    assert _torch_installs(cloud) == 1


def test_an_operation_following_a_checkpoint_reopens_the_image_instead_of_rebuilding(cloud):
    first = _run(cloud, Checkpoint(keep_layers=True))
    env_ops, env_image = first.layers[-1]
    cloud.ran.clear()
    second = _run(cloud, Checkpoint(start_image=env_image, start_ops=env_ops, keep_layers=True,
                                    branch_files=(("main.py", b"print(2)\n", 0o644),)), upload=False)
    assert cloud.reopened == [env_image]
    assert second.branch_from_image == env_image and second.ran_setup == ()
    # nothing of the environment ran again: no upload/extract, no setup command, only the overlay and the command
    assert cloud.ran == [sandbox.BRANCH_COMMAND, "python main.py"]
    assert _torch_installs(cloud) == 0


def test_branching_never_reinstalls_a_package_already_in_the_image(cloud):
    """The fake client counts installs: across a checkpoint and nine branches (3 candidates x 3 rounds), torch is installed once."""
    first = _run(cloud, Checkpoint(keep_layers=True))
    env_ops, env_image = first.layers[-1]
    for k in range(9):
        result = _run(cloud, Checkpoint(start_image=env_image, start_ops=env_ops, keep_layers=True, keep_result=True,
                                        branch_files=((f"patch_{k}.py", b"x = 1\n", 0o644),)), upload=False)
        assert result.result_image is not None
    assert _torch_installs(cloud) == 1
    assert sum(1 for c in cloud.ran if c == PLAN[0]) == 1


def test_a_later_setup_command_runs_on_top_of_the_deepest_layer(cloud):
    """A runner hook appended after the plan (the CPU shim) is only the suffix: torch stays from the checkpoint."""
    first = _run(cloud, Checkpoint(keep_layers=True))
    env_ops, env_image = first.layers[-1]
    shim = runner_hooks.install_command(runner_hooks.CPU_SHIM)
    cloud.ran.clear()
    result = _run(cloud, Checkpoint(start_image=env_image, start_ops=env_ops, keep_layers=True), extras=(shim,), upload=False)
    assert cloud.ran == [shim, "python main.py"] and result.ran_setup == (shim,)
    assert result.layers[-1][0] == (*env_ops, shim)
    assert [s.phase for s in result.steps] == ["runner_setup", "repo_run"]


def test_the_overlay_writes_and_deletes_files_and_lands_after_the_setup(cloud):
    first = _run(cloud, Checkpoint(keep_layers=True))
    env_ops, env_image = first.layers[-1]
    result = _run(cloud, Checkpoint(start_image=env_image, start_ops=env_ops, keep_result=True,
                                    branch_files=(("main.py", b"print('patched')\n", 0o644),), branch_deleted=("requirements.txt",)),
                  upload=False)
    files = cloud.images[result.result_image]["files"]
    assert files["main.py"] == b"print('patched')\n" and "requirements.txt" not in files
    # the kept result image is the environment image plus the overlay, nothing else ran on it
    assert cloud.images[result.result_image]["built"][-1] == sandbox.BRANCH_COMMAND
    # the environment layer itself is unchanged (immutable snapshot): the next candidate starts from the pristine tree again
    assert cloud.images[env_image]["files"]["main.py"] == b"print(1)\n"


def test_an_early_overlay_is_applied_right_after_the_tree(cloud):
    result = _run(cloud, Checkpoint(keep_layers=False, branch_before_setup=True,
                                    branch_files=(("requirements.txt", b"numpy==1.19.5\n", 0o644),)))
    assert cloud.ran.index(sandbox.BRANCH_COMMAND) < cloud.ran.index(TORCH.install_command)
    assert result.layers == ()


def test_a_start_image_must_hold_a_prefix_of_the_setup(cloud):
    with pytest.raises(sandbox.SandboxError):
        _run(cloud, Checkpoint(start_image="x", start_ops=("apt-get install foo",)), upload=False)


def test_without_a_checkpoint_nothing_is_kept_and_nothing_changes(cloud):
    result = _run(cloud, None)
    assert result.layers == () and result.result_image is None and result.setup_commands == ()
    retained = [image_id for image_id in cloud.images if image_id not in cloud.cleaned]
    # every retained image (upload, extract, each setup step) got the disposal run, as before harness-v1.4.0-rc
    assert len(cloud.cleaned) == len(cloud.images) and not retained


def test_cost_and_seconds_include_the_overlay_step(cloud):
    cloud.costs = {sandbox.BRANCH_COMMAND: 0.002, "python main.py": 0.003}
    first = _run(cloud, Checkpoint(keep_layers=True))
    env_ops, env_image = first.layers[-1]
    result = _run(cloud, Checkpoint(start_image=env_image, start_ops=env_ops, branch_files=(("a.py", b"", 0o644),)), upload=False)
    assert result.total_cost_usd == pytest.approx(0.005)
    assert [s.phase for s in result.rerun_steps] == ["rerun_branch"]


def test_a_failed_overlay_check_is_a_harness_integrity_failure(cloud):
    cloud.fail_on = "apply.py"
    with pytest.raises(sandbox.UploadIntegrityError, match="patch overlay check"):
        _run(cloud, Checkpoint(keep_layers=False, branch_before_setup=True, branch_files=(("a.py", b"", 0o644),)))


def test_layers_completed_before_a_timeout_are_kept_and_reported(cloud, monkeypatch):
    from contree_sdk.sdk.exceptions import OperationTimedOutError

    real_run = _Image.run

    def run(self, shell, timeout, disposable, preserve_env=False):
        if shell == PLAN[0]:
            raise OperationTimedOutError(operation_uuid=uuidlib.uuid4())
        return real_run(self, shell, timeout, disposable, preserve_env)

    monkeypatch.setattr(_Image, "run", run)
    with pytest.raises(sandbox.SandboxTimeoutError) as info:
        _run(cloud, Checkpoint(keep_layers=True))
    layers = info.value.layers
    assert [len(ops) for ops, _ in layers] == [0, 1, 2]  # the tree, the torch install, the exec-stack fix
    assert not {image for _, image in layers} & set(cloud.cleaned)


def test_releasing_kept_images_reports_the_measured_cost_of_the_disposal_runs(cloud):
    first = _run(cloud, Checkpoint(keep_layers=True))
    ids = [image for _, image in first.layers[:2]]
    outcome = sandbox.release_images(api_key="k", image_ids=ids)
    assert outcome["released"] == 2 and cloud.cleaned[-2:] == ids
    assert outcome["cost_usd"] == 0.0 and outcome["seconds"] == pytest.approx(4.0)  # the fake's disposal runs: $0, 2 s each
    assert sandbox.release_images(api_key="", image_ids=ids) == {"released": 0, "cost_usd": 0.0, "seconds": 0.0}
