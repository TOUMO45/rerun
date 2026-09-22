"""Tests for compute_sandbox.py's pure/structural logic and orchestration
flow — the Compute-VM-backed sandbox scaffold added by this session's
Nebius integration audit (see DECISIONS.md and compute_sandbox.py's own
module docstring for what is and isn't live-verified).

These do NOT provision a real Nebius Compute VM — there is no
NEBIUS_COMPUTE_CREDENTIALS_FILE in this environment. What's tested here:

  1. Ephemeral SSH keypair generation produces a key paramiko can actually
     parse, and cloud-init user-data renders valid YAML with the expected
     shape (both independently verified against the real installed
     `cryptography`/`paramiko`/`pyyaml` — not mocked).
  2. `_shell_quote` correctly escapes single quotes — this is the actual
     boundary between a planner-generated command string and a remote
     `bash -lc '...'` invocation over SSH, so it is a real security
     surface, not incidental formatting.
  3. `run_build_and_execute` fails fast with a clear, specific error when
     Compute credentials are incomplete, instead of reaching the network.
  4. The orchestration flow (create instance -> wait for running -> SSH ->
     upload -> run steps -> always delete, even on failure) against fakes
     for the Nebius SDK's InstanceServiceClient and for paramiko's
     SSHClient/Channel — proving compute_sandbox.py's OWN control flow,
     not the real Nebius API or a real network connection.

A live smoke test (provision one real VM, run a command, tear it down) is
intentionally NOT claimed here — see test_compute_sandbox_smoke.py,
skipped until NEBIUS_COMPUTE_CREDENTIALS_FILE is available, mirroring
test_sandbox_smoke.py's existing pattern for the Token Factory backend.
"""

from __future__ import annotations

import io

import paramiko
import pytest
import yaml

from nebius.api.nebius.compute.v1 import InstanceStatus

from app.services.compute_sandbox import (
    ComputeSandboxCredentialsError,
    ComputeSandboxError,
    _build_cloud_init_user_data,
    _generate_ephemeral_keypair,
    _shell_quote,
    _wait_for_running_instance,
    run_build_and_execute,
)


# --- Ephemeral keypair + cloud-init rendering -------------------------------


def test_generate_ephemeral_keypair_produces_a_paramiko_parseable_key():
    keypair = _generate_ephemeral_keypair()
    parsed = paramiko.RSAKey.from_private_key(io.StringIO(keypair.private_key_pem))
    assert parsed.get_bits() == 2048
    assert keypair.public_key_openssh.startswith("ssh-rsa ")


def test_generate_ephemeral_keypair_is_different_each_call():
    a = _generate_ephemeral_keypair()
    b = _generate_ephemeral_keypair()
    assert a.private_key_pem != b.private_key_pem


def test_build_cloud_init_user_data_is_valid_yaml_with_the_ssh_key_and_docker_install():
    user_data = _build_cloud_init_user_data(ssh_username="ubuntu", public_key_openssh="ssh-rsa AAAAB3NzaC1 test@x")
    assert user_data.startswith("#cloud-config\n")
    parsed = yaml.safe_load(user_data)
    assert parsed["users"][0]["name"] == "ubuntu"
    assert parsed["users"][0]["ssh_authorized_keys"] == ["ssh-rsa AAAAB3NzaC1 test@x"]
    assert any("get.docker.com" in cmd for cmd in parsed["runcmd"])


# --- _shell_quote: the real command-injection boundary ----------------------


def test_shell_quote_wraps_a_plain_command_in_single_quotes():
    assert _shell_quote("python train.py") == "'python train.py'"


def test_shell_quote_escapes_embedded_single_quotes():
    quoted = _shell_quote("echo 'hi'; rm -rf /")
    # Round-trip through POSIX sh semantics: closing the quote, escaping the
    # literal quote, then reopening — never a bare unescaped quote.
    assert quoted == "'echo '\\''hi'\\''; rm -rf /'"


# --- Fail-fast credential check (no network call should happen) ------------


def test_run_build_and_execute_fails_fast_without_credentials():
    with pytest.raises(ComputeSandboxCredentialsError):
        run_build_and_execute(
            credentials_file="",
            project_id="",
            subnet_id="",
            platform="cpu-e2",
            preset="4vcpu-16gb",
            image_family="",
            ssh_username="ubuntu",
            boot_disk_gib=20,
            base_image="python:3.11-slim",
            install_commands=[],
            execute_command="python train.py",
            wall_clock_seconds=60,
        )


# --- _wait_for_running_instance: real InstanceState enum, fake polling ----


class _FakeIp:
    def __init__(self, address):
        self.address = address


class _FakeNic:
    def __init__(self, address):
        self.public_ip_address = _FakeIp(address)


class _FakeStatusMsg:
    def __init__(self, state, address=None):
        self.state = state
        self.network_interfaces = [_FakeNic(address)] if address else []


class _FakeInstanceMsg:
    def __init__(self, state, address=None):
        self.status = _FakeStatusMsg(state, address)


class _ScriptedGetClient:
    """Returns a scripted sequence of real InstanceStatus.InstanceState
    values from `.get(...).wait()` — proves _wait_for_running_instance's
    own state/IP comparisons against the actual protobuf enum, not a
    lookalike."""

    def __init__(self, states_and_ips):
        self._script = list(states_and_ips)

    def get(self, request):
        state, address = self._script.pop(0) if len(self._script) > 1 else self._script[0]
        return _Waitable(_FakeInstanceMsg(state, address))


class _Waitable:
    def __init__(self, value):
        self._value = value

    def wait(self):
        return self._value


def test_wait_for_running_instance_returns_ip_once_running(monkeypatch):
    import app.services.compute_sandbox as compute_sandbox_module

    monkeypatch.setattr(compute_sandbox_module.time, "sleep", lambda _seconds: None)
    client = _ScriptedGetClient(
        [
            (InstanceStatus.InstanceState.STARTING, None),
            (InstanceStatus.InstanceState.RUNNING, "203.0.113.9"),
        ]
    )
    ip = _wait_for_running_instance(client, "instance-1", timeout_seconds=30)
    assert ip == "203.0.113.9"


def test_wait_for_running_instance_raises_on_error_state(monkeypatch):
    import app.services.compute_sandbox as compute_sandbox_module

    monkeypatch.setattr(compute_sandbox_module.time, "sleep", lambda _seconds: None)
    client = _ScriptedGetClient([(InstanceStatus.InstanceState.ERROR, None)])
    with pytest.raises(ComputeSandboxError):
        _wait_for_running_instance(client, "instance-1", timeout_seconds=30)


def test_wait_for_running_instance_raises_on_timeout(monkeypatch):
    import app.services.compute_sandbox as compute_sandbox_module

    fake_clock = [0.0]
    monkeypatch.setattr(compute_sandbox_module.time, "sleep", lambda _seconds: fake_clock.__setitem__(0, fake_clock[0] + 100))
    monkeypatch.setattr(compute_sandbox_module.time, "monotonic", lambda: fake_clock[0])
    client = _ScriptedGetClient([(InstanceStatus.InstanceState.STARTING, None)])
    with pytest.raises(ComputeSandboxError):
        _wait_for_running_instance(client, "instance-1", timeout_seconds=30)


# --- Orchestration flow: fakes for the Nebius SDK and for paramiko ---------


class _FakeStatus:
    def __init__(self, ok=True):
        self._ok = ok

    def __bool__(self):
        return self._ok


class _FakeOperation:
    def __init__(self, resource_id="instance-123", ok=True):
        self._resource_id = resource_id
        self._ok = ok

    def wait(self):
        return self

    def sync_wait(self):
        return None

    def successful(self):
        return self._ok

    def status(self):
        return _FakeStatus(self._ok)

    @property
    def resource_id(self):
        return self._resource_id


class _FakeInstanceServiceClient:
    """Records create/delete calls. `_wait_for_running_instance` itself is
    monkeypatched out in these tests (its own polling loop is exercised via
    real enum comparisons better tested directly against the installed SDK,
    not worth re-faking the exact protobuf enum values here) — this fake
    only needs to satisfy `.create()`/`.delete()`."""

    instances_created: list = []
    instances_deleted: list = []

    def __init__(self, sdk):
        pass

    def create(self, request):
        _FakeInstanceServiceClient.instances_created.append(request)
        return _FakeOperation(resource_id="instance-123")

    def delete(self, request):
        _FakeInstanceServiceClient.instances_deleted.append(request.id)
        return _FakeOperation()


class _FakeChannel:
    def __init__(self, exit_code, stdout=b"ok\n", stderr=b""):
        self._exit_code = exit_code
        self._stdout = stdout
        self._stderr = stderr
        self._stdout_sent = False
        self._stderr_sent = False

    def settimeout(self, timeout):
        pass

    def exec_command(self, command):
        self.command = command

    def exit_status_ready(self):
        return True

    def recv_ready(self):
        return not self._stdout_sent

    def recv(self, n):
        self._stdout_sent = True
        return self._stdout

    def recv_stderr_ready(self):
        return not self._stderr_sent

    def recv_stderr(self, n):
        self._stderr_sent = True
        return self._stderr

    def recv_exit_status(self):
        return self._exit_code

    def close(self):
        pass


class _FakeTransport:
    def __init__(self, channels):
        self._channels = list(channels)

    def open_session(self, timeout=None):
        return self._channels.pop(0)


class _FakeSftp:
    def __init__(self):
        self.uploaded: dict[str, bytes] = {}

    def put(self, local_path, remote_path):
        self.uploaded[remote_path] = b"<file>"

    def open(self, remote_path, mode):
        return _FakeSftpFile(self, remote_path)

    def close(self):
        pass


class _FakeSftpFile:
    def __init__(self, sftp, remote_path):
        self._sftp = sftp
        self._remote_path = remote_path

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def write(self, data):
        self._sftp.uploaded[self._remote_path] = data


class _FakeSSHClient:
    def __init__(self, channels):
        self._transport = _FakeTransport(channels)
        self.closed = False
        self.sftp = _FakeSftp()

    def get_transport(self):
        return self._transport

    def open_sftp(self):
        return self.sftp

    def exec_command(self, command):
        # used for the plain `mkdir -p` calls — a channel-like tuple whose
        # [1] has a .channel.recv_exit_status() no-op.
        class _Immediate:
            class channel:
                @staticmethod
                def recv_exit_status():
                    return 0

        return (None, _Immediate(), None)

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_fake_instance_service_client():
    _FakeInstanceServiceClient.instances_created = []
    _FakeInstanceServiceClient.instances_deleted = []
    yield


def _base_kwargs(**overrides):
    kwargs = dict(
        credentials_file="creds.json",
        project_id="proj-1",
        subnet_id="subnet-1",
        platform="cpu-e2",
        preset="4vcpu-16gb",
        image_family="ubuntu22.04",
        ssh_username="ubuntu",
        boot_disk_gib=20,
        base_image="python:3.11-slim",
        install_commands=["pip install numpy"],
        execute_command="python train.py",
        wall_clock_seconds=120,
    )
    kwargs.update(overrides)
    return kwargs


def test_run_build_and_execute_runs_steps_and_always_deletes_the_instance(monkeypatch):
    import app.services.compute_sandbox as compute_sandbox_module

    monkeypatch.setattr(compute_sandbox_module, "SDK", lambda credentials_file_name: object())
    monkeypatch.setattr(compute_sandbox_module, "InstanceServiceClient", _FakeInstanceServiceClient)
    monkeypatch.setattr(compute_sandbox_module, "_wait_for_running_instance", lambda *a, **k: "203.0.113.5")
    fake_ssh = _FakeSSHClient([_FakeChannel(0), _FakeChannel(0)])
    monkeypatch.setattr(compute_sandbox_module, "_wait_for_ssh", lambda *a, **k: fake_ssh)

    result = run_build_and_execute(**_base_kwargs())

    assert len(result.steps) == 2
    assert result.succeeded
    assert result.sandbox_id == "instance-123"
    assert len(_FakeInstanceServiceClient.instances_created) == 1
    assert _FakeInstanceServiceClient.instances_deleted == ["instance-123"]
    assert fake_ssh.closed is True


def test_run_build_and_execute_stops_at_first_failure_but_still_deletes(monkeypatch):
    import app.services.compute_sandbox as compute_sandbox_module

    monkeypatch.setattr(compute_sandbox_module, "SDK", lambda credentials_file_name: object())
    monkeypatch.setattr(compute_sandbox_module, "InstanceServiceClient", _FakeInstanceServiceClient)
    monkeypatch.setattr(compute_sandbox_module, "_wait_for_running_instance", lambda *a, **k: "203.0.113.5")
    fake_ssh = _FakeSSHClient([_FakeChannel(1, stderr=b"boom")])
    monkeypatch.setattr(compute_sandbox_module, "_wait_for_ssh", lambda *a, **k: fake_ssh)

    result = run_build_and_execute(**_base_kwargs(install_commands=["pip install numpy"]))

    assert len(result.steps) == 1  # execute_command never ran
    assert result.succeeded is False
    assert _FakeInstanceServiceClient.instances_deleted == ["instance-123"]


def test_run_build_and_execute_deletes_the_instance_even_when_ssh_never_becomes_ready(monkeypatch):
    import app.services.compute_sandbox as compute_sandbox_module

    monkeypatch.setattr(compute_sandbox_module, "SDK", lambda credentials_file_name: object())
    monkeypatch.setattr(compute_sandbox_module, "InstanceServiceClient", _FakeInstanceServiceClient)
    monkeypatch.setattr(compute_sandbox_module, "_wait_for_running_instance", lambda *a, **k: "203.0.113.5")

    def _raise_ssh_timeout(*a, **k):
        raise ComputeSandboxError("could not SSH: simulated timeout")

    monkeypatch.setattr(compute_sandbox_module, "_wait_for_ssh", _raise_ssh_timeout)

    with pytest.raises(ComputeSandboxError):
        run_build_and_execute(**_base_kwargs())

    # §2.6's guarantee must hold even when the VM never became reachable —
    # a half-provisioned instance must never be left running.
    assert _FakeInstanceServiceClient.instances_deleted == ["instance-123"]
