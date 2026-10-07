"""harness-v1.8 (T15, D-52), from the out-of-sample scan (runs/live_scan/oos_v1.7.2/2026-10-05_Frimkron__mud-pi_api_certificate.json): a script the
repository's own README tells the reader to run (`python simplemud.py`) is an entrypoint candidate even though it has no `__main__` guard, no
argparse and no `sys.argv` (mud-pi's `simplemud.py` is a module-level `while True:` loop), so recon no longer ends ENTRYPOINT_UNCLEAR with "no candidate
scripts found" for a repository that names its command.

The fixture reproduces mud-pi's tree (`README.md simplemud.py mudserver.py`) with a few README lines quoted from the scanned file (CRLF line endings
and the tab-indented command, as committed) and the loop's opening lines. No network: the "repository" is a local git repo cloned by `run_intake`.

Scope: the recon / UI path only (`run_intake`, used by routers/runs.py). A corpus run (`run_one_repo` -> `parse_intake`) names its command itself and
never reads the README for candidates: the tests below pin that, and that `build_plan` keeps a documented command verbatim."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.batch.run_single_repo import run_one_repo
from app.services import intake, recon
from app.services.intake import RepoIntake, find_entrypoint_candidates, parse_intake, run_intake
from app.services.orchestrator import PipelineResult
from app.services.planner import build_plan
from app.services.recon import ReconResult, parse_recon_response, run_recon

README_MUD = (
    "MUD Pi\r\n======\r\n\r\nA simple text-based Multi-User Dungeon (MUD) game, which could be run on a \r\nRaspberry Pi or other low-end server.\r\n\r\n"
    "Running the Server\r\n------------------\r\n\r\n### On Windows\r\n\r\nDouble click on `simplemud.py` - the file will be opened with the Python \r\n"
    "interpreter. To stop the server, simply close the terminal window.\r\n\r\n### On Mac OSX and Linux (including Raspberry Pi)\r\n\r\n"
    "From the terminal, change to the directory containing the script and run \r\n\r\n\tpython simplemud.py\r\n\t\r\n"
    "Note, if you are connected to the machine via SSH, you will find that the \r\nscript stops running when you quit the SSH session.\r\n"
)
SIMPLEMUD = (
    "import time\n\nfrom mudserver import MudServer\n\n# stores the players in the game\nplayers = {}\n\n# start the server\nmud = MudServer()\n\n"
    "# main game loop. We loop forever (i.e. until the program is terminated)\nwhile True:\n\n    time.sleep(0.2)\n    mud.update()\n"
)
MUDSERVER = "class MudServer(object):\n    def __init__(self):\n        self._clients = {}\n\n    def update(self):\n        pass\n"
MAIN_GUARDED = "def main():\n    pass\n\n\nif __name__ == '__main__':\n    main()\n"
BARE_SCRIPT = "import os\n\nprint(os.getcwd())\n"  # module-level code, no guard, reads no arguments: not found by discovery today


def _write(root: Path, files: dict[str, str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))  # bytes: the README keeps its CRLF
    return root


def _git_repo(root: Path, files: dict[str, str]) -> Path:
    _write(root, files)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True, capture_output=True)
    for key, value in (("core.autocrlf", "false"), ("user.email", "t@e.st"), ("user.name", "t")):
        subprocess.run(["git", "config", key, value], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=root, check=True, capture_output=True)
    return root


def run_intake_like(repo: Path) -> RepoIntake:
    return parse_intake(repo, "a" * 40, readme_entrypoints=True)


def _mud_files() -> dict[str, str]:
    return {"README.md": README_MUD, "simplemud.py": SIMPLEMUD, "mudserver.py": MUDSERVER}


# --- the mud-pi case ----------------------------------------------------------------------------------------------------------------------


def test_before_discovery_alone_finds_no_candidate_in_the_mud_pi_tree(tmp_path):
    repo = _write(tmp_path / "mud", _mud_files())
    assert find_entrypoint_candidates(repo) == ()  # the rule that ended the scan ENTRYPOINT_UNCLEAR is itself unchanged


def test_after_the_ui_path_intake_names_simplemud_from_the_readme(tmp_path):
    src = _git_repo(tmp_path / "src", _mud_files())
    result = run_intake(str(src), tmp_path / "clone", shallow=False)  # what routers/runs.py calls
    assert result.entrypoint_candidates == ("simplemud.py",)
    assert result.readme_entrypoints == {"simplemud.py": "python simplemud.py"}
    # the record says why this candidate is there; mudserver.py (named by no command) is not one
    assert result.as_dict()["readme_entrypoints"] == {"simplemud.py": "python simplemud.py"}
    assert "mudserver.py" not in result.entrypoint_candidates


def test_the_run_record_of_the_ui_router_lists_the_readme_named_candidate(tmp_path, client):
    from app.db import get_db
    from app.main import app
    from app.models import Run

    src = _git_repo(tmp_path / "src", _mud_files())
    created = client.post("/runs", json={"repo_url": str(src)})  # POST /runs -> intake.run_intake -> the run row's build_plan
    assert created.status_code == 201, created.text
    session = next(app.dependency_overrides[get_db]())
    try:
        assert session.get(Run, created.json()["id"]).build_plan["entrypoint_candidates"] == ["simplemud.py"]
    finally:
        session.close()


# --- which README commands count ---------------------------------------------------------------------------------------------------------


def test_fenced_indented_and_inline_commands_are_read_and_the_path_is_normalised(tmp_path):
    files = {name: BARE_SCRIPT for name in ("a.py", "b.py", "c.py", "d.py", "e.py", "tools/serve.py", "tools/other.py")}
    files["README.md"] = (
        "# Usage\n\n```bash\n$ python3 -u ./tools/serve.py --port 80\n```\n\n"            # fenced; `$` prompt; `-u`; python3; `./`; arguments
        "    python a.py --flag one\n\n"                                                  # indented code block
        "or run `python b.py`, or ``python3.11 c.py`` in an RST-style span.\n\n"           # inline code spans
        "~~~\npython d.py \\\n  --long-arg 5 && python e.py\n~~~\n"                        # ~~~ fence, backslash continuation, a second command after &&
    )
    repo = _write(tmp_path / "r", files)
    found = intake.find_readme_entrypoints(repo)
    assert list(found) == ["tools/serve.py", "a.py", "b.py", "c.py", "d.py"]  # README order; `./` dropped from the key
    assert found["tools/serve.py"] == "python3 -u ./tools/serve.py --port 80"  # the command as the README writes it, prompt removed
    assert found["a.py"] == "python a.py --flag one" and found["b.py"] == "python b.py" and found["c.py"] == "python3.11 c.py"
    assert found["d.py"] == "python d.py --long-arg 5"  # continuation joined; stops before `&&`
    assert "e.py" not in found and "tools/other.py" not in found  # the command after `&&` is not the README's run command for e.py; other.py is never named


def test_rst_and_txt_readmes_are_read_too(tmp_path):
    repo = _write(tmp_path / "r", {"README.rst": "Run it\n======\n\nRun::\n\n   python3 serve.py --debug\n\nor ``python alt.py``.\n", "serve.py": BARE_SCRIPT, "alt.py": BARE_SCRIPT})
    assert intake.find_readme_entrypoints(repo) == {"serve.py": "python3 serve.py --debug", "alt.py": "python alt.py"}
    repo2 = _write(tmp_path / "r2", {"readme.txt": "Start with:\n\n    python tool.py\n", "tool.py": BARE_SCRIPT})
    assert intake.find_readme_entrypoints(repo2) == {"tool.py": "python tool.py"}


def test_commands_that_must_not_add_a_candidate(tmp_path):
    outside = tmp_path / "outside.py"
    outside.write_text(BARE_SCRIPT, encoding="utf-8")
    repo = _write(tmp_path / "repo", {
        "README.md": (
            "```\npython missing.py\npython -m pkg\npip install x\npython ../outside.py\npython ../repo/../outside.py\npython /etc/outside.py\n"
            "python setup.py install\npython ~/home.py\npython $HOME/env.py\npython realdir.py\npython2 old.py\n./direct.py\npython3 -c 'print(1)'\n"
            "python .hidden/h.py\npython sub/../../outside.py\n```\n\nThen run python prose.py to start.\n"  # prose line: not in a fence, an indented block or a span
        ),
        "setup.py": "from setuptools import setup\nsetup()\n", "home.py": BARE_SCRIPT, "env.py": BARE_SCRIPT, "old.py": BARE_SCRIPT, "direct.py": BARE_SCRIPT,
        "prose.py": BARE_SCRIPT, ".hidden/h.py": BARE_SCRIPT, "sub/keep.py": BARE_SCRIPT, "realdir.py/inner.txt": "a directory named like a script\n",
    })
    assert intake.find_readme_entrypoints(repo) == {}
    assert run_intake_like(repo).entrypoint_candidates == ()


def test_a_symlinked_readme_or_script_is_never_followed(tmp_path):
    outside = tmp_path / "outside.py"
    outside.write_text(BARE_SCRIPT, encoding="utf-8")
    secret = tmp_path / "secret.md"
    secret.write_text("    python real.py\n", encoding="utf-8")
    repo = _write(tmp_path / "repo", {"real.py": BARE_SCRIPT})
    try:
        os.symlink(secret, repo / "README.md")
        os.symlink(outside, repo / "linked.py")
        os.symlink(tmp_path, repo / "linkdir", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this host cannot create symlinks")
    assert intake.find_readme_entrypoints(repo) == {}  # the README is a symlink: not read
    (repo / "README.md").unlink()
    (repo / "README.md").write_text("    python linked.py\n    python linkdir/outside.py\n    python real.py\n", encoding="utf-8")
    assert intake.find_readme_entrypoints(repo) == {"real.py": "python real.py"}  # a symlinked script and a script under a symlinked directory are refused


def test_a_readme_script_or_directory_that_reports_as_a_symlink_is_refused(tmp_path, monkeypatch):
    # the same refusal without needing the OS to create a link (this host may not): Path.is_symlink answers True for the named entries
    repo = _write(tmp_path / "r", {"README.md": "    python real.py\n    python link.py\n    python linkdir/x.py\n", "real.py": BARE_SCRIPT, "link.py": BARE_SCRIPT,
                                   "linkdir/x.py": BARE_SCRIPT})
    reports = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda self: self.name in ("link.py", "linkdir") or reports(self))
    assert intake.find_readme_entrypoints(repo) == {"real.py": "python real.py"}
    monkeypatch.setattr(Path, "is_symlink", lambda self: self.name == "README.md" or reports(self))
    assert intake.find_readme_entrypoints(repo) == {}


def test_a_script_spelled_with_the_wrong_case_is_not_a_candidate(tmp_path):
    # the sandbox is case-sensitive: `python Serve.py` names no file there even where this host's file system would find serve.py
    repo = _write(tmp_path / "r", {"README.md": "    python Serve.py\n    python serve.py\n", "serve.py": BARE_SCRIPT})
    assert intake.find_readme_entrypoints(repo) == {"serve.py": "python serve.py"}


# --- candidates that exist today are unchanged ----------------------------------------------------------------------------------------------


def test_existing_candidates_keep_their_content_and_order_and_new_ones_are_appended(tmp_path):
    repo = _write(tmp_path / "r", {
        "train.py": MAIN_GUARDED, "eval.py": MAIN_GUARDED, "helper.py": BARE_SCRIPT, "lib.py": "def f():\n    return 1\n",
        "README.md": "```\npython train.py --epochs 3\npython helper.py\npython train.py\n```\n",
    })
    before = find_entrypoint_candidates(repo)
    assert before == ("eval.py", "train.py")
    result = run_intake_like(repo)
    assert result.entrypoint_candidates[: len(before)] == before  # unchanged, same order
    assert result.entrypoint_candidates == ("eval.py", "train.py", "helper.py")  # helper.py appended; train.py not duplicated
    assert result.readme_entrypoints == {"helper.py": "python helper.py"}  # only what the README alone added; train.py was found by discovery already


def test_a_repository_whose_readme_names_only_found_scripts_has_an_identical_record(tmp_path):
    repo = _write(tmp_path / "r", {"train.py": MAIN_GUARDED, "main.py": "x = 1\n", "README.md": "Run `python train.py` then `python main.py`.\n"})
    result = run_intake_like(repo)
    assert result.entrypoint_candidates == find_entrypoint_candidates(repo) == ("main.py", "train.py")
    assert result.readme_entrypoints == {}
    assert "readme_entrypoints" not in result.as_dict()  # nothing added: the intake record has exactly the keys it had before
    assert set(result.as_dict()) == {"local_path", "commit_sha", "dependency_files", "declared_dependencies", "notebook_paths", "entrypoint_candidates", "python_version_hint"}


def test_a_repository_without_a_readme_or_with_no_command_in_it_is_unchanged(tmp_path):
    bare = _write(tmp_path / "bare", {"train.py": MAIN_GUARDED})
    assert run_intake_like(bare).entrypoint_candidates == ("train.py",)
    prose = _write(tmp_path / "prose", {"README.md": "# Title\n\nSome words about `notes.py` and python.\n", "notes.py": BARE_SCRIPT})
    assert run_intake_like(prose).entrypoint_candidates == ()


def test_the_number_of_readme_named_candidates_is_capped_in_readme_order(tmp_path):
    names = [f"s{i:02d}.py" for i in range(15)]
    repo = _write(tmp_path / "r", {**{n: BARE_SCRIPT for n in names}, "README.md": "```\n" + "\n".join(f"python {n}" for n in reversed(names)) + "\n```\n"})
    found = intake.find_readme_entrypoints(repo)
    assert list(found) == list(reversed(names))[: intake.MAX_README_ENTRYPOINTS] and len(found) == intake.MAX_README_ENTRYPOINTS


# --- the corpus path is untouched --------------------------------------------------------------------------------------------------------


def test_the_corpus_intake_never_reads_the_readme_for_candidates(tmp_path, monkeypatch):
    repo = _write(tmp_path / "mud", _mud_files())

    def _boom(*a, **k):
        raise AssertionError("the corpus path must not reach the README scan")

    monkeypatch.setattr(intake, "find_readme_entrypoints", _boom)
    result = parse_intake(repo, "a" * 40)  # exactly the call run_single_repo.run_one_repo and scripts/live_run.py make
    assert result.entrypoint_candidates == () and result.readme_entrypoints == {}


def test_a_run_with_a_documented_command_does_not_go_through_the_readme_scan(tmp_path, monkeypatch):
    src = _write(tmp_path / "src", _mud_files())

    def _copy_clone(url, dest, commit_sha):
        shutil.copytree(src, dest, dirs_exist_ok=True)
        return "a" * 40

    def _boom(*a, **k):
        raise AssertionError("the corpus path must not reach the README scan")

    monkeypatch.setattr(intake, "find_readme_entrypoints", _boom)
    seen: dict = {}

    def _fake_pipeline(**kwargs):
        seen.update(kwargs)
        from datetime import datetime, timezone

        return PipelineResult(verdict="RUNS_CLEAN", taxonomy_code=None, indeterminate_reason="", attempts=(), build_plan={}, full_log="[fake]",
                              certificate_prose="ok", reproduction_passport_hash="a" * 64, timestamp=datetime.now(timezone.utc).isoformat(),
                              repo_url=kwargs["repo_url"], commit_sha=kwargs["commit_sha"])

    class _Settings:
        nebius_api_key = "fake-key-for-construction-only"
        nebius_base_url = "https://api.tokenfactory.nebius.com/v1"
        nebius_model_recon = "nvidia/nemotron-3-nano"
        nebius_model_repairer = "nvidia/nemotron-3-super"
        nebius_model_adjudicator = "nvidia/nemotron-3-ultra"
        nebius_model_planner = "nvidia/nemotron-3-super"
        nebius_sandbox_wall_clock_seconds = 60
        max_attempts_per_run = 3
        daily_cost_ceiling_usd = 25.0
        tavily_configured = False
        nebius_sandbox_image = "python:3.11-slim"
        nebius_project_id = ""
        nebius_sandbox_backend = "token_factory"

    result = run_one_repo("https://example.com/mud", "a" * 40, "mud", settings=_Settings(), run_pipeline_fn=_fake_pipeline, clone_fn=_copy_clone,
                          command="python simplemud.py --corpus-arg 7")
    assert result["verdict"] == "RUNS_CLEAN"
    assert seen["documented_command"] == "python simplemud.py --corpus-arg 7"  # the corpus command, verbatim
    assert seen["intake_result"].entrypoint_candidates == () and seen["intake_result"].readme_entrypoints == {}


def test_a_documented_command_is_still_the_execute_command_whatever_the_readme_names():
    named = RepoIntake(Path("/fake"), "a" * 40, {}, frozenset(), (), ("simplemud.py",), None, readme_entrypoints={"simplemud.py": "python simplemud.py"})
    plan = build_plan(named, ReconResult(is_indeterminate=True), documented_command="python other.py --x 1")
    assert plan.execute_command == "python other.py --x 1"
    # and without a documented command the plan still runs the recon-chosen path, quoted as before
    chosen = build_plan(named, ReconResult(is_indeterminate=False, entrypoint="simplemud.py", confidence=0.9))
    assert chosen.execute_command == "python simplemud.py"


# --- recon -----------------------------------------------------------------------------------------------------------------------------------


class _Chat:
    def __init__(self, reply: dict):
        self.reply = json.dumps(reply)
        self.calls: list[dict] = []

    def chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        return self.reply


def _mud_intake() -> RepoIntake:
    return RepoIntake(Path("/fake"), "a" * 40, {}, frozenset(), (), ("simplemud.py",), None, readme_entrypoints={"simplemud.py": "python simplemud.py"})


def test_recon_shows_the_model_the_readme_command_and_the_record_says_why(tmp_path):
    chat = _Chat({"entrypoint": "simplemud.py", "confidence": 0.9, "python_version": None, "reasoning": "the README runs it"})
    result = run_recon(chat, "m", _mud_intake(), {"simplemud.py": SIMPLEMUD})
    assert result.is_indeterminate is False and result.entrypoint == "simplemud.py"
    assert result.reasoning.startswith("README-NAMED: the repository's README tells the reader to run `python simplemud.py`")
    assert result.reasoning.endswith("the README runs it")
    call = chat.calls[0]
    assert '"readme_named_commands"' in call["user_prompt"] and '"simplemud.py": "python simplemud.py"' in call["user_prompt"]
    assert "readme_named_commands" in call["system_prompt"]  # the instruction that explains the key


def test_recon_prompt_and_reasoning_are_unchanged_when_the_readme_added_nothing():
    plain = RepoIntake(Path("/fake"), "a" * 40, {}, frozenset(), (), ("train.py",), None)
    chat = _Chat({"entrypoint": "train.py", "confidence": 0.9, "reasoning": "r"})
    result = run_recon(chat, "m", plain, {"train.py": MAIN_GUARDED})
    assert "readme_named_commands" not in chat.calls[0]["user_prompt"]
    assert chat.calls[0]["system_prompt"] == recon._SYSTEM_PROMPT
    assert result.reasoning == "r"
    # a README-added candidate the model does not choose leaves the reasoning alone
    two = RepoIntake(Path("/fake"), "a" * 40, {}, frozenset(), (), ("train.py", "simplemud.py"), None, readme_entrypoints={"simplemud.py": "python simplemud.py"})
    other = run_recon(_Chat({"entrypoint": "train.py", "confidence": 0.9, "reasoning": "r"}), "m", two, {"train.py": MAIN_GUARDED})
    assert other.reasoning == "r"


def test_a_readme_named_script_does_not_lower_the_confidence_bar():
    # D-52 adds the candidate and the evidence, not a new threshold: a low-confidence pick of a script whose source shows no recognised start-up code
    # (`while True:` is not one) is still INDETERMINATE, exactly as for any other sole candidate (v1.7.2 rule unchanged)
    low = parse_recon_response({"entrypoint": "simplemud.py", "confidence": 0.35}, candidates=("simplemud.py",), source_by_path={"simplemud.py": SIMPLEMUD},
                               readme_commands={"simplemud.py": "python simplemud.py"})
    assert low.is_indeterminate is True and "0.35" in low.indeterminate_reason
    # and the model still cannot name a path the candidates do not hold, README or not
    assert parse_recon_response({"entrypoint": "mudserver.py", "confidence": 0.99}, candidates=("simplemud.py",),
                                readme_commands={"simplemud.py": "python simplemud.py"}).is_indeterminate is True


def test_the_no_candidate_message_is_unchanged_for_a_repository_the_readme_does_not_help():
    nothing = RepoIntake(Path("/fake"), "a" * 40, {}, frozenset(), (), (), None)
    result = run_recon(_Chat({}), "m", nothing)
    assert result.is_indeterminate is True and result.indeterminate_code == "ENTRYPOINT_UNCLEAR"
    assert result.indeterminate_reason == ("no runnable entrypoint discoverable in recon: no candidate scripts found "
                                           "(no train.py/main.py/run.py-style file, and no file with a __main__ guard)")
