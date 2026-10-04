"""harness-v1.7, R3 (METHODOLOGY "harness-v1.7 — PRE-REGISTRATION"): data_prep. Failure class: DATA_MISSING where the repository documents how to prepare its data.

Recorded: DEV #9 round 4 (runs/corpus_v2_batch/harness-v1.6.0/dev/09_omarfoq__fedem.json: `AssertionError: Download cifar10 dataset!!`, then COST_CAP). Its README says
"go to `./data/cifar10`, follow the instructions in `README.md`", and data/cifar10/README.md runs `python generate_data.py --n_tasks 80 ...` in its first code block.
Negative controls, recorded DATA_MISSING the rule must NOT fire on: gate #3 v1.4.3 (vmtl: the README links an HTML page for Office-Home, no archive, no script) and
DEV #4 round 4 (img-comp-reference: `original.png`, placeholders, a Google Drive folder link). Firing is single-case (#9); the class is covered by three recorded entries.

The README fixtures below are short excerpts of the repositories at their recorded commits (the lines the rule reads), not whole files."""

from __future__ import annotations

import base64
import http.server
import io
import json
import socketserver
import subprocess
import sys
import tarfile
import threading
from pathlib import Path

import pytest

from app.services import data_prep, runner_hooks, tavily
from app.services.cost_guard import CostGuard
from app.services.intake import RepoIntake
from app.services.orchestrator import PipelineDeps, run_pipeline
from app.services.sandbox import SandboxRunResult, StepResult
from test_v151_pins_and_removals import _Chat, _git_repo, _ok

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "runs" / "corpus_v2_batch"


def _evidence(rel: str) -> str:
    return json.loads((RUNS / rel).read_text(encoding="utf-8"))["result"]["error_chain"][-1]["error"]


E9 = "harness-v1.6.0/dev/09_omarfoq__fedem.json"
E3 = "harness-v1.4.3/gate/03_autumn9999__vmtl.json"
E4 = "harness-v1.6.0/dev/04_damo-cv__img-comp-reference.json"

FEDEM = {
    "README.md": ("# Federated Multi-Task Learning under a Mixture of Distributions\n\n## Evaluation\n\n"
                  "We give instructions to run experiments on CIFAR-10 dataset as an example\n"
                  "(the same holds for the other datasets). You need first to go to \n"
                  "`./data/cifar10`, follow the instructions in `README.md` to download and partition\nthe dataset.\n"),
    "data/cifar10/README.md": ("# CIFAR10 Dataset\n\n## Instructions\n\n### Base usage\n\nFor basic usage, run generate_data.py with a choice of the following arguments:\n\n"
                               "## Paper Experiments\n\n```\npython generate_data.py \\\n    --n_tasks 80 \\\n    --n_components 3 \\\n    --alpha 0.4 \\\n"
                               "    --s_frac 1.0 \\\n    --tr_frac 0.8 \\\n    --seed 12345    \n```\n\nIn order to include the validation set, run\n\n"
                               "```\npython generate_data.py \\\n    --n_tasks 80 \\\n    --val_frac 0.25 \\\n    --seed 12345    \n```\n"),
    "data/cifar10/generate_data.py": "print('generate')\n",
    "data/emnist/generate_data.py": "print('generate')\n",
    "run_experiment.py": "print('run')\n",
}
VMTL = {
    "README.md": ("### Getting Started\nInside this repository, we mainly conduct comprehensive experiments on Office-Home. Download the dataset from the following "
                  "link, and place it in [`Dataset/`](./Dataset/) directory.\n- Office-home; [[link]](https://www.hemanthdv.org/officeHomeDataset.html)\n\n"
                  "To extract the input features based on VGG16 by using the following command:\n```\npython feature_vgg16.py #gpu_id #split\n```\n"),
    "Dataset/.keep": "",
    "feature_vgg16.py": "print(1)\n",
}
IMGCOMP = {
    "README.md": ("## Evaluation on [Kodak](http://r0k.us/graphics/kodak/) Dataset\n\n```\nsh compress.sh original.png [model_path]\n```\n\n"
                  "Download the pre-trained [models](https://drive.google.com/drive/folders/1YH8P5XCKCc0UcMJTCX-Y4xSIIcbD2uLN?usp=sharing) optimized by MSE.\n"),
    "compress.sh": "python main.py\n",
}


def _tree(tmp_path: Path, files: dict) -> Path:
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return tmp_path


# --- the decision (pure) -------------------------------------------------------------------------------------------------------------------------

def test_replay_entry_9_the_documented_script_and_its_first_invocation_are_found(tmp_path):
    evidence = _evidence(E9)
    assert evidence == "AssertionError: Download cifar10 dataset!!"
    d = data_prep.decide(_tree(tmp_path, FEDEM), evidence)
    assert d.prep is not None and d.prep.kind == "script"
    assert d.prep.script == "data/cifar10/generate_data.py" and d.prep.workdir == "data/cifar10" and d.prep.readme == "data/cifar10/README.md"
    assert d.prep.command == ("python", "generate_data.py", "--n_tasks", "80", "--n_components", "3", "--alpha", "0.4", "--s_frac", "1.0",
                              "--tr_frac", "0.8", "--seed", "12345")
    assert d.prep.dataset_name.lower() == "cifar10"
    assert d.readmes == ("README.md", "data/cifar10/README.md")  # data/emnist is not named by the root README: never read


@pytest.mark.parametrize("files,rel", [(VMTL, E3), (IMGCOMP, E4)], ids=["gate3_vmtl", "dev4_img_comp"])
def test_negative_controls_the_rule_does_not_fire_and_fabricates_nothing(tmp_path, files, rel):
    d = data_prep.decide(_tree(tmp_path, files), _evidence(rel))
    assert d.prep is None and "no README names" in d.reason


def test_two_documented_scripts_need_the_evidence_to_name_one(tmp_path):
    files = {**FEDEM, "README.md": FEDEM["README.md"] + "\nOr go to `./data/emnist` and run generate_data.py there.\n",
             "data/emnist/README.md": "```\npython generate_data.py --n_tasks 10\n```\n"}
    root = _tree(tmp_path, files)
    assert data_prep.decide(root, "AssertionError: Download emnist dataset!!").prep.workdir == "data/emnist"
    assert data_prep.decide(root, "AssertionError: Download the data first").prep is None


def test_a_sudo_or_shell_operator_in_the_documented_command_is_refused_not_rewritten(tmp_path):
    files = {**FEDEM, "data/cifar10/README.md": "```\nsudo python generate_data.py --n_tasks 80\n```\n"}
    d = data_prep.decide(_tree(tmp_path, files), "AssertionError: Download cifar10 dataset!!")
    assert d.prep is None and "sudo" in d.reason
    files = {**FEDEM, "data/cifar10/README.md": "```\npython generate_data.py --n_tasks 80 && rm -rf /\n```\n"}
    assert "shell operators" in data_prep.decide(_tree(tmp_path / "b", files), "AssertionError: Download cifar10 dataset!!").reason


def test_a_documented_archive_goes_where_the_evidence_path_says(tmp_path):
    files = {"README.md": "## Data\nDownload the dataset:\nhttps://example.org/files/toy-data.tar.gz\n", "train.py": "print(1)\n"}
    d = data_prep.decide(_tree(tmp_path, files), "FileNotFoundError: [Errno 2] No such file or directory: 'data/toy/train.csv'")
    assert d.prep.kind == "archive" and d.prep.url == "https://example.org/files/toy-data.tar.gz" and d.prep.workdir == "data/toy"
    far = {"README.md": "Download\n\n\n\n\nhttps://example.org/x.zip\n", "train.py": ""}
    assert data_prep.decide(_tree(tmp_path / "far", far), "FileNotFoundError: [Errno 2] No such file or directory: 'd/a.csv'").prep is None


def test_the_tavily_query_carries_the_readme_dataset_name():
    assert tavily.dataset_query("https://github.com/omarfoq/fedem", "AssertionError: Download cifar10 dataset!!", "CIFAR10") == "omarfoq fedem CIFAR10 dataset download"
    assert tavily.dataset_query("https://github.com/omarfoq/fedem", "AssertionError: Download cifar10 dataset!!") == \
        "omarfoq fedem dataset download Download cifar10 dataset!!"


# --- the launcher (runs here with this interpreter; inside the sandbox it runs with the image's python3) ------------------------------------------

def _launch(cwd: Path, spec: dict) -> dict:
    code = runner_hooks.data_prep_source()
    arg = base64.b64encode(json.dumps(spec).encode("utf-8")).decode("ascii")
    done = subprocess.run([sys.executable, "-c", code, arg], cwd=cwd, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    record = runner_hooks.parse_data_prep(done.stdout)
    assert record is not None, done.stdout
    return record


def _script_spec(argv, **kw):
    return {"kind": "script", "workdir": "data/cifar10", "script": "data/cifar10/generate_data.py", "argv": argv, "url": "",
            "max_bytes": kw.get("max_bytes", 10_000_000), "max_seconds": kw.get("max_seconds", 60)}


def test_the_launcher_runs_the_script_in_its_directory_and_records_bytes_and_hash(tmp_path):
    _tree(tmp_path, {"data/cifar10/generate_data.py": "import os\nos.makedirs('all_data', exist_ok=True)\nopen('all_data/x.bin','wb').write(b'0'*4096)\n"})
    record = _launch(tmp_path, _script_spec([sys.executable, "generate_data.py"]))
    assert record["exit_code"] == 0 and record["bytes_written"] == 4096 and len(record["sha256"]) == 64
    assert (tmp_path / "data" / "cifar10" / "all_data" / "x.bin").is_file()


def test_over_the_byte_cap_the_new_files_are_removed_and_the_record_says_so(tmp_path):
    _tree(tmp_path, {"keep.txt": "old\n", "data/cifar10/generate_data.py": "open('big.bin','wb').write(b'0'*20000)\n"})
    old = tmp_path / "keep.txt"
    import os
    import time
    os.utime(old, (time.time() - 3600, time.time() - 3600))
    record = _launch(tmp_path, _script_spec([sys.executable, "generate_data.py"], max_bytes=1000))
    assert record["over_cap"] is True and record["removed_files"] >= 1
    assert not (tmp_path / "data" / "cifar10" / "big.bin").exists() and old.exists()


def test_over_the_time_cap_the_step_is_stopped_and_the_launcher_still_exits_0(tmp_path):
    _tree(tmp_path, {"data/cifar10/generate_data.py": "import time\ntime.sleep(30)\n"})
    record = _launch(tmp_path, _script_spec([sys.executable, "generate_data.py"], max_seconds=1))
    assert record["exit_code"] is None and "stopped" in record["error"]


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def _serve(directory: Path):
    handler = lambda *a, **k: _Quiet(*a, directory=str(directory), **k)  # noqa: E731
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _tar(members: dict) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_the_launcher_downloads_and_extracts_a_documented_archive_and_refuses_an_unsafe_one(tmp_path):
    served = tmp_path / "served"
    served.mkdir()
    (served / "toy.tar.gz").write_bytes(_tar({"toy/train.csv": b"a,b\n1,2\n"}))
    (served / "evil.tar.gz").write_bytes(_tar({"../escape.txt": b"x"}))
    server = _serve(served)
    try:
        repo = tmp_path / "repo"
        repo.mkdir()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        spec = {"kind": "archive", "workdir": "data", "script": "", "argv": [], "max_bytes": 10_000_000, "max_seconds": 60}
        ok = _launch(repo, {**spec, "url": f"{base}/toy.tar.gz"})
        assert ok["exit_code"] == 0 and ok["extracted"] and ok["downloaded_bytes"] > 0 and (repo / "data" / "toy" / "train.csv").is_file()
        bad = _launch(repo, {**spec, "url": f"{base}/evil.tar.gz"})
        assert bad["exit_code"] is None and "refused archive member" in bad["error"] and not (repo / "escape.txt").exists()
    finally:
        server.shutdown()


def test_the_setup_command_carries_the_spec_and_never_fails_the_setup(tmp_path):
    d = data_prep.decide(_tree(tmp_path, FEDEM), "AssertionError: Download cifar10 dataset!!")
    cmd = runner_hooks.data_prep_command(d.prep)
    assert cmd.startswith("python3 -c ") and cmd.endswith(" || true")
    spec = json.loads(base64.b64decode(cmd.split()[-3]).decode("utf-8"))
    assert spec["argv"][:2] == ["python", "generate_data.py"] and spec["max_seconds"] == 180 and spec["max_bytes"] == 500_000_000


# --- the pipeline ------------------------------------------------------------------------------------------------------------------------------------

def test_replay_entry_9_in_the_pipeline_the_step_runs_before_the_rerun_and_no_model_is_called(tmp_path):
    _tree(tmp_path, FEDEM)
    _git_repo(tmp_path, {})
    evidence = _evidence(E9)
    fail = SandboxRunResult(steps=(StepResult("python run_experiment.py cifar10 FedAvg", 1, "", f"Traceback (most recent call last):\n{evidence}\n", 1.0, 0.01),))
    marker = 'RERUN_DATA_PREP {"bytes_written": 180000000, "exit_code": 0, "kind": "script", "seconds": 95.0, "sha256": "ab", "workdir": "data/cifar10"}'
    prep_done = SandboxRunResult(steps=(StepResult("python3 -c ...", 0, marker + "\n", "", 95.0, 0.5), StepResult("python run_experiment.py", 0, "ok", "", 1.0, 0.01)))
    results, plans = [fail, prep_done], []

    def runner(*, runner_extras=(), **kw):
        plans.append({**kw, "runner_extras": runner_extras})
        return results.pop(0)

    repair = _Chat()
    deps = PipelineDeps(recon_client=_Chat([{"entrypoint": "run_experiment.py", "confidence": 0.9}]), recon_model="r", repair_client=repair, repair_model="p",
                        adjudicator_client=None, adjudicator_model=None, sandbox_api_key="k", sandbox_wall_clock_seconds=100, sandbox_runner=runner,
                        tavily_client=None, smoke_seconds=0, max_attempts=3)
    intake = RepoIntake(tmp_path, "a" * 40, {}, frozenset(), (), ("run_experiment.py",), None)
    result = run_pipeline(repo_url="https://github.com/omarfoq/fedem", commit_sha="a" * 40, workdir=tmp_path, intake_result=intake, deps=deps,
                          cost_guard=CostGuard(daily_cost_ceiling_usd=100), run_id="v17-data", documented_command="python run_experiment.py cifar10 FedAvg")
    assert not results and not repair.calls
    assert result.verdict == "RUNS_AFTER_REPAIR"
    step = next(a for a in result.attempts if (a.time_machine_action or {}).get("rule") == "data_prep")
    act = step.time_machine_action
    assert act["readme"] == "data/cifar10/README.md" and act["command"].startswith("python generate_data.py --n_tasks 80") and act["workdir"] == "data/cifar10"
    assert act["result"]["bytes_written"] == 180000000 and act["caps"] == {"seconds": 180, "bytes_written": 500000000}
    assert not plans[0]["runner_extras"] and any("RERUN_DATA_PREP" in base64.b64decode(c.split("'")[1]).decode() for c in plans[1]["runner_extras"])
