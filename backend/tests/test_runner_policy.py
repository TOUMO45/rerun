"""Phase 3: the Python version policy (6 fixture repos) and the runner-provided torch policy."""

from __future__ import annotations

import pytest

from app.services import python_policy as pp
from app.services import runner_env as re_, sandbox, sandbox_limits as lim


# --- python version policy: 6 fixture repos ------------------------------------------------

FIXTURES = [
    # (id, files, readme, version, source)
    ("undeclared", {"requirements.txt": "numpy\n"}, None, "3.10", "default"),
    ("python-version-file", {".python-version": "3.7.9\n"}, None, "3.7", ".python-version"),
    ("setup-python-requires", {"setup.py": "setup(name='x', python_requires='>=3.6,<3.9')"}, None, "3.8", "setup.py"),
    ("pyproject-modern", {"pyproject.toml": '[project]\nname="x"\nrequires-python = ">=3.11"\n'}, None, "3.11", "pyproject.toml"),
    ("conda-environment", {"environment.yml": "name: e\ndependencies:\n  - python=3.8\n  - numpy\n"}, None, "3.8", "environment.yml"),
    ("readme-only", {}, "# Proj\nTested with Python 3.7.\n", "3.7", "README"),
]


@pytest.mark.parametrize("name, files, readme, version, source", FIXTURES, ids=[f[0] for f in FIXTURES])
def test_version_policy_on_fixture_repos(name, files, readme, version, source):
    choice = pp.resolve(files, readme)
    assert (choice.version, choice.source) == (version, source)
    assert choice.image == f"python:{version}-slim"
    assert choice.reason  # always logged
    assert choice.is_declared == (source != "default")


def test_or_later_resolves_to_the_first_preferred_minor_that_satisfies():
    # ">= 3.7" is a claim about a range, not a request for its oldest member: 3.10 satisfies it.
    assert pp.resolve({}, "Requires Python 3.7 or later.").version == "3.10"
    assert pp.resolve({}, "Python >= 3.11 is required").version == "3.11"


def test_default_is_3_10_not_3_11():
    assert pp.DEFAULT_VERSION == "3.10" and pp.DEFAULT_IMAGE == "python:3.10-slim"


def test_precedence_and_unsatisfiable_declarations_fall_back_with_a_reason():
    both = pp.resolve({".python-version": "3.9", "setup.py": "python_requires='>=3.6'"})
    assert both.source == ".python-version" and both.version == "3.9"
    py2 = pp.resolve({"setup.py": "python_requires='<3.0'"})
    assert py2.source == "default" and "not satisfiable" in py2.reason
    caret = pp.resolve({"pyproject.toml": '[tool.poetry.dependencies]\npython = "^3.8"\n'})
    assert caret.version == "3.10" and caret.source == "pyproject.toml"  # ^3.8 = >=3.8,<4 -> first preference


def test_resolve_from_repo_reads_files_and_readme(tmp_path):
    (tmp_path / ".python-version").write_text("3.8.10\n", encoding="utf-8")
    assert pp.resolve_from_repo(tmp_path).version == "3.8"
    other = tmp_path / "o"
    other.mkdir()
    (other / "README.md").write_text("Tested with Python 3.9.\n", encoding="utf-8")
    assert pp.resolve_from_repo(other) == pp.PythonChoice("3.9", "README", "3.9", pp.resolve_from_repo(other).reason)


# --- torch policy ----------------------------------------------------------------------------

def test_pins_are_read_from_requirements_and_printf_lists_and_local_suffix_is_dropped():
    texts = ["numpy==1.23.3 torch==1.12.1 torchvision==0.13.1 typing-extensions==4.3.0",
             "torch>=1.4,<2\nscipy\n", "torch==1.12.1+cu113"]
    assert re_.torch_specs(texts[:1]) == {"torch": "==1.12.1", "torchvision": "==0.13.1"}
    assert re_.torch_specs([texts[1]]) == {"torch": ">=1.4,<2"}
    assert re_.torch_specs([texts[2]]) == {"torch": "==1.12.1"}  # no GPU in the sandbox: +cu113 dropped
    assert re_.torch_specs(["pytorch-lightning==1.0 torchmetrics==0.5 my-torch==1"]) == {}


def test_setup_for_a_pinned_repo_keeps_the_pins_and_installs_the_whole_family():
    s = re_.plan_torch_setup(["pip install -r x.txt; printf 'torch==1.12.1 torchvision==0.13.1'"], None)
    assert s.specs == ("torch==1.12.1", "torchvision==0.13.1", "torchaudio")
    tail = "--index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple"
    # the matched set first; if torchaudio has no wheel for this Python/torch, only what the repo uses
    assert s.install_command == (f"pip install torch==1.12.1 torchvision==0.13.1 torchaudio {tail} "
                                 f"|| pip install torch==1.12.1 torchvision==0.13.1 {tail}")
    assert "RERUN_TORCH_OK" in s.fix_command and "clear-execstack" in s.fix_command


def test_companion_pin_without_a_torch_pin_installs_torch_unpinned_beside_it():
    s = re_.plan_torch_setup(["pip install torchvision==0.13.1 torch"], None)
    assert s.specs == ("torch", "torchvision==0.13.1", "torchaudio")


def test_repo_that_imports_torch_without_declaring_it_gets_the_newest_matched_cpu_wheels(tmp_path):
    (tmp_path / "train.py").write_text("import torch\nprint(torch.zeros(1))\n", encoding="utf-8")
    s = re_.plan_torch_setup(["true"], tmp_path)
    assert s.specs == ("torch", "torchvision", "torchaudio") and s.needed == ("torch",) and "without declaring" in s.reason


def test_importing_only_torchvision_installs_torch_and_torchvision_together(tmp_path):
    """Attempt 1, entry 4: the repo imported torchvision, the runner installed torch alone, torchvision was missing."""
    (tmp_path / "a.py").write_text("import numpy\nfrom torchvision import transforms\n", encoding="utf-8")
    s = re_.plan_torch_setup(["true"], tmp_path)
    assert s.specs == ("torch", "torchvision", "torchaudio") and s.needed == ("torch", "torchvision")
    assert s.install_command.startswith("pip install torch torchvision torchaudio ")
    for module in ("torch", "torchvision", "torchaudio"):
        (tmp_path / "a.py").write_text(f"import {module}.nn\n", encoding="utf-8")
        assert re_.plan_torch_setup(["true"], tmp_path).specs == ("torch", "torchvision", "torchaudio")


def test_a_torch_free_repo_pays_nothing(tmp_path):
    (tmp_path / "a.py").write_text("import numpy\n# torch is mentioned in a comment only\n", encoding="utf-8")
    assert re_.plan_torch_setup(["pip install numpy==1.0"], tmp_path) is None


def test_cpu_only_policy_states_the_no_gpu_fact():
    assert re_.SANDBOX_HAS_GPU is False and "whl/cpu" in re_.CPU_INDEX


# --- runner integration: torch is its own ops, before the repo's requirements -------------------

def test_runner_torch_ops_come_after_system_packages_and_before_the_rest():
    setup = re_.plan_torch_setup(["pip install torch==1.12.1"], None)
    ops = lim.split_setup_ops(["pip install -r requirements.txt", "apt-get update && apt-get install -y gcc"],
                              (setup.install_command, setup.fix_command))
    assert [o.kind for o in ops] == ["system", "torch", "torch", "requirements"]
    assert ops[1].command == setup.install_command and ops[2].command == setup.fix_command
    assert all(o.within_limit for o in ops)  # the CPU wheel and the fix are estimated well under 12 GB


def test_run_build_and_execute_passes_torch_ops_to_the_sandbox(monkeypatch):
    seen = {}
    monkeypatch.setattr(sandbox, "_run_once", lambda **kw: seen.update(kw) or sandbox.SandboxRunResult(
        steps=(sandbox.StepResult("x", 0, "", "", 0.0, 0.0),)))
    setup = re_.plan_torch_setup(["pip install torch==2.0.0"], None)
    sandbox.run_build_and_execute(api_key="k", base_image="python:3.10-slim", install_commands=["pip install -r r.txt"],
                                  execute_command="python t.py", wall_clock_seconds=60, torch_setup=setup)
    assert seen["commands"] == [setup.install_command, setup.fix_command, "pip install -r r.txt", "python t.py"]


def test_fix_script_is_valid_python_and_verifies_the_import():
    compile(re_.FIX_AND_VERIFY, "<fix>", "exec")
    assert "PT_GNU_STACK" in re_.FIX_AND_VERIFY and "import torch" in re_.FIX_AND_VERIFY


def test_batch_preflight_refuses_a_non_sealed_default_image():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("b", Path(__file__).resolve().parents[2] / "scripts" / "run_corpus_v1_batch.py")
    batch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(batch)
    batch.check_sandbox_image("python:3.10-slim")
    with pytest.raises(batch.PreflightError, match="3.11"):
        batch.check_sandbox_image("python:3.11-slim")


def test_fix_script_uses_a_runner_owned_prefix_and_verifies_the_flag_before_use():
    """Attempt 1, entry 3: pip on python:3.6-slim resolved an unpinned patchelf to 0.17.2, which lacks --clear-execstack."""
    fix = re_.FIX_AND_VERIFY
    assert "--target" in fix and "/opt/rerun_tools" in fix and "patchelf==0.19.1.0" in fix
    assert fix.index('"--help"') < fix.index('"--clear-execstack"')
    assert "RERUN_SANDBOX_INCOMPAT" in fix and "sys.exit(98)" in fix
    assert '"-q", "patchelf"' not in fix  # no unpinned install into the repo's environment
