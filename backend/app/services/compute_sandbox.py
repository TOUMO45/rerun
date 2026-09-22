"""Sandbox lifecycle on real Nebius AI Cloud Compute VMs — an alternative
backend to sandbox.py's Token Factory Sandboxes, added per this session's
Nebius integration audit (see DECISIONS.md).

**Why this module exists.** sandbox.py's `ContreeSync` reaches Nebius Token
Factory's "Sandboxes" product (`https://api.tokenfactory.nebius.com/sandboxes/`,
confirmed by reading the installed contree_sdk source — see sandbox.py's own
docstring). Nebius's docs (docs.tokenfactory.nebius.com) describe that as
VM-level isolated, secure code execution — but it is a distinct product from
Nebius AI Cloud "Compute" (docs.nebius.com/compute: standalone, SSH-connectable
VMs with disks/volumes, authenticated via Nebius's general Cloud IAM
service-account model), with its own separate credential. Confirmed directly
by the user during this audit: their real "Compute" credential is separate
from their Token Factory API key. This module reaches genuine Compute VMs.

**Ground truth this was built against** — read directly from the installed
`nebius` package (v0.6.11), not guessed:

  - Auth: a service-account JSON key file (the standard "authorized key"
    downloaded from the Nebius console) consumed via
    `SDK(credentials_file_name=...)` — documented in `nebius/sdk.py`'s own
    docstring, and traced through `nebius/base/service_account/credentials_file.py`
    (the exact JSON shape: `{"subject-credentials": {"alg": "RS256",
    "private-key": ..., "kid": ..., "iss": ..., "sub": ...}}`).
  - VM lifecycle: `nebius.api.nebius.compute.v1.InstanceServiceClient`
    (`.create`/`.get`/`.delete`, each returning a long-running `Operation`
    with `.wait()` to send the RPC and `.sync_wait()` to block for
    completion, `.resource_id` for the created instance's id) — field names
    for `InstanceSpec`/`ResourcesSpec`/`AttachedDiskSpec`/`DiskSpec`/
    `SourceImageFamily`/`NetworkInterfaceSpec`/`PublicIPAddress` all read
    from the package's own `.pyi` stubs.
  - SSH key injection: `InstanceSpec.cloud_init_user_data` (a real
    cloud-init user-data string) — there is no "run this command and give
    me stdout" RPC on `InstanceServiceClient`, so SSH is the only path to
    execute anything once the VM is up. Docker is installed via cloud-init
    so `base_image` keeps the exact same meaning as it does for the Token
    Factory backend (a container image reference), rather than requiring
    each Nebius image family to already have the right Python version.
  - Teardown: `InstanceServiceClient.delete` "Also deletes all the managed
    disks, declared in the instance spec" per its own docstring — one call
    covers both instance and boot disk, matching §2.6's "always destroy
    after use", the same guarantee sandbox.py gives via try/finally.

**Not yet live-verified — flagged honestly, same standard as runner.py's
NebiusJobsClient.** There is no real Nebius AI Cloud Compute credential,
subnet, or image family available in this environment. Unverified:

  - The exact valid strings for `platform`/`preset`/image family in a real
    account (`nebius_compute_platform`/`nebius_compute_preset`/
    `nebius_compute_image_family` are left for the operator to fill in from
    their own console — see .env.example).
  - That the chosen image family's cloud-init implementation accepts this
    exact `#cloud-config` shape and that the VM has outbound internet
    access for `get.docker.com` (needed to install Docker on first boot).
  - Real per-run cost: unlike `ContreeResult.cost` (Token Factory Sandboxes),
    this API does not return per-instance billing inline, so `cost_usd` is
    reported as 0.0 for every step here — a known, documented gap, not a
    fabricated number. A real figure would need platform/preset hourly
    rates multiplied by wall-clock instance lifetime, tracked separately.
  - SSH/Docker readiness timing under real cloud-init boot times.

Treat this as a real-shaped, real-API scaffold that needs a live smoke test
(provision one VM, run a command, tear it down, inspect logs) before it is
trusted the way sandbox.py's Token Factory path is.
"""

from __future__ import annotations

import io
import socket
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from nebius.api.nebius.common.v1 import ResourceMetadata
from nebius.api.nebius.compute.v1 import (
    AttachedDiskSpec,
    CreateInstanceRequest,
    DeleteInstanceRequest,
    DiskSpec,
    GetInstanceRequest,
    InstanceServiceClient,
    InstanceSpec,
    InstanceStatus,
    ManagedDisk,
    NetworkInterfaceSpec,
    PublicIPAddress,
    ResourcesSpec,
    SourceImageFamily,
)
from nebius.sdk import SDK

from app.services.sandbox import SandboxCredentialsError, SandboxError, SandboxRunResult, StepResult

try:
    import paramiko
except ImportError as exc:  # pragma: no cover - dependency is declared in pyproject.toml
    raise ImportError(
        "compute_sandbox.py requires paramiko (pip install paramiko) to execute "
        "commands over SSH once a Compute VM is up."
    ) from exc


class ComputeSandboxCredentialsError(SandboxCredentialsError):
    pass


class ComputeSandboxError(SandboxError):
    pass


@dataclass(frozen=True)
class _EphemeralKeypair:
    private_key_pem: str
    public_key_openssh: str


def _generate_ephemeral_keypair() -> _EphemeralKeypair:
    """A fresh SSH keypair per sandbox run — never reused across runs, never
    written to disk. Private key in PKCS1 PEM (the format paramiko's
    RSAKey.from_private_key reads directly); public key in OpenSSH format
    (what cloud-init's ssh_authorized_keys expects)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    public_openssh = (
        key.public_key()
        .public_bytes(encoding=serialization.Encoding.OpenSSH, format=serialization.PublicFormat.OpenSSH)
        .decode("ascii")
    )
    return _EphemeralKeypair(private_key_pem=private_pem, public_key_openssh=public_openssh)


def _build_cloud_init_user_data(*, ssh_username: str, public_key_openssh: str) -> str:
    """Real cloud-init #cloud-config: creates the SSH login user and installs
    Docker, so `base_image` means the same thing here as it does for the
    Token Factory backend (see module docstring)."""
    cloud_config = {
        "users": [
            {
                "name": ssh_username,
                "sudo": "ALL=(ALL) NOPASSWD:ALL",
                "shell": "/bin/bash",
                "ssh_authorized_keys": [public_key_openssh],
            }
        ],
        "package_update": True,
        "runcmd": [
            "curl -fsSL https://get.docker.com | sh",
            f"usermod -aG docker {ssh_username}",
            "systemctl enable --now docker",
        ],
    }
    return "#cloud-config\n" + yaml.safe_dump(cloud_config, sort_keys=False)


def _wait_for_running_instance(
    client: InstanceServiceClient,
    instance_id: str,
    *,
    timeout_seconds: float,
    poll_interval_seconds: float = 5.0,
) -> str:
    """Poll until the instance is RUNNING and has a public IP; return that
    IP. Raises ComputeSandboxError on ERROR state or timeout."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        instance = client.get(GetInstanceRequest(id=instance_id)).wait()
        state = instance.status.state
        if state == InstanceStatus.InstanceState.ERROR:
            raise ComputeSandboxError(f"instance {instance_id} entered ERROR state while booting")
        if state == InstanceStatus.InstanceState.RUNNING:
            for iface in instance.status.network_interfaces:
                address = iface.public_ip_address.address
                if address:
                    return address
        if time.monotonic() >= deadline:
            raise ComputeSandboxError(
                f"instance {instance_id} did not reach RUNNING with a public IP within "
                f"{timeout_seconds:.0f}s (last state: {state})"
            )
        time.sleep(poll_interval_seconds)


def _wait_for_ssh(
    host: str,
    *,
    username: str,
    private_key_pem: str,
    timeout_seconds: float,
    poll_interval_seconds: float = 5.0,
) -> "paramiko.SSHClient":
    """cloud-init (create user, install Docker) takes time after the VM
    reports RUNNING — retry the SSH connection until it succeeds or the
    timeout elapses."""
    pkey = paramiko.RSAKey.from_private_key(io.StringIO(private_key_pem))
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(host, username=username, pkey=pkey, timeout=10, banner_timeout=10, auth_timeout=10)
            return client
        except (paramiko.SSHException, OSError, socket.timeout) as exc:
            last_error = exc
            client.close()
            time.sleep(poll_interval_seconds)
    raise ComputeSandboxError(f"could not SSH to {host} within {timeout_seconds:.0f}s: {last_error}")


def _upload_files(ssh: "paramiko.SSHClient", remote_dir: str, files: dict[str, str | Path | bytes]) -> None:
    sftp = ssh.open_sftp()
    try:
        ssh.exec_command(f"mkdir -p {remote_dir}")[1].channel.recv_exit_status()
        for rel_path, content in files.items():
            remote_path = f"{remote_dir}/{rel_path}"
            parent = remote_path.rsplit("/", 1)[0]
            ssh.exec_command(f"mkdir -p {parent}")[1].channel.recv_exit_status()
            if isinstance(content, (str, Path)):
                sftp.put(str(content), remote_path)
            else:
                with sftp.open(remote_path, "wb") as fh:
                    fh.write(content)
    finally:
        sftp.close()


def _run_command_over_ssh(
    ssh: "paramiko.SSHClient", command: str, *, timeout_seconds: float
) -> tuple[int, str, str, float]:
    """Run one command, enforcing `timeout_seconds` on the whole call.
    Returns (exit_code, stdout, stderr, elapsed_seconds)."""
    started = time.monotonic()
    transport = ssh.get_transport()
    if transport is None:
        raise ComputeSandboxError("SSH transport is not open")
    channel = transport.open_session(timeout=timeout_seconds)
    channel.settimeout(timeout_seconds)
    try:
        channel.exec_command(command)
        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []
        while not channel.exit_status_ready():
            if channel.recv_ready():
                stdout_chunks.append(channel.recv(65536))
            if channel.recv_stderr_ready():
                stderr_chunks.append(channel.recv_stderr(65536))
            if time.monotonic() - started > timeout_seconds:
                channel.close()
                raise socket.timeout(f"command exceeded {timeout_seconds:.0f}s: {command!r}")
            time.sleep(0.2)
        while channel.recv_ready():
            stdout_chunks.append(channel.recv(65536))
        while channel.recv_stderr_ready():
            stderr_chunks.append(channel.recv_stderr(65536))
        exit_code = channel.recv_exit_status()
        stdout = b"".join(stdout_chunks).decode("utf-8", errors="replace")
        stderr = b"".join(stderr_chunks).decode("utf-8", errors="replace")
        return exit_code, stdout, stderr, time.monotonic() - started
    finally:
        channel.close()


def run_build_and_execute(
    *,
    credentials_file: str,
    project_id: str,
    subnet_id: str,
    platform: str,
    preset: str,
    image_family: str,
    ssh_username: str,
    boot_disk_gib: int,
    base_image: str,
    install_commands: Iterable[str],
    execute_command: str,
    wall_clock_seconds: float,
    upload_files: dict[str, str | Path | bytes] | None = None,
    instance_boot_timeout_seconds: float = 300.0,
    ssh_ready_timeout_seconds: float = 240.0,
) -> SandboxRunResult:
    """Provision one Nebius Compute VM, run the build-plan pipeline inside a
    Docker container on it (so `base_image` means the same thing it does for
    sandbox.py's Token Factory backend), then always delete the VM — success
    or failure. See module docstring for what is and isn't verified.
    """
    if not credentials_file or not project_id or not subnet_id or not image_family:
        raise ComputeSandboxCredentialsError(
            "Nebius Compute is not fully configured — NEBIUS_COMPUTE_CREDENTIALS_FILE, "
            "NEBIUS_COMPUTE_PROJECT_ID, NEBIUS_COMPUTE_SUBNET_ID and NEBIUS_COMPUTE_IMAGE_FAMILY "
            "must all be set (see .env.example). This is a separate credential from "
            "NEBIUS_API_KEY/NEBIUS_PROJECT_ID, which are Token Factory's."
        )

    keypair = _generate_ephemeral_keypair()
    cloud_init = _build_cloud_init_user_data(ssh_username=ssh_username, public_key_openssh=keypair.public_key_openssh)

    sdk = SDK(credentials_file_name=credentials_file)
    instances = InstanceServiceClient(sdk)
    instance_id: str | None = None
    ssh: "paramiko.SSHClient" | None = None

    try:
        create_request = CreateInstanceRequest(
            metadata=ResourceMetadata(parent_id=project_id, name=f"rerun-sandbox-{uuid.uuid4().hex[:10]}"),
            spec=InstanceSpec(
                resources=ResourcesSpec(platform=platform, preset=preset),
                boot_disk=AttachedDiskSpec(
                    attach_mode=AttachedDiskSpec.AttachMode.READ_WRITE,
                    managed_disk=ManagedDisk(
                        spec=DiskSpec(
                            size_gibibytes=boot_disk_gib,
                            source_image_family=SourceImageFamily(image_family=image_family),
                        )
                    ),
                ),
                network_interfaces=[
                    NetworkInterfaceSpec(subnet_id=subnet_id, name="eth0", public_ip_address=PublicIPAddress())
                ],
                cloud_init_user_data=cloud_init,
            ),
        )
        operation = instances.create(create_request).wait()
        operation.sync_wait()
        if not operation.successful():
            raise ComputeSandboxError(f"Compute instance creation failed: {operation.status()}")
        instance_id = operation.resource_id

        public_ip = _wait_for_running_instance(instances, instance_id, timeout_seconds=instance_boot_timeout_seconds)
        ssh = _wait_for_ssh(
            public_ip,
            username=ssh_username,
            private_key_pem=keypair.private_key_pem,
            timeout_seconds=ssh_ready_timeout_seconds,
        )

        remote_workdir = "/tmp/rerun-workspace"
        if upload_files:
            _upload_files(ssh, remote_workdir, upload_files)
        else:
            ssh.exec_command(f"mkdir -p {remote_workdir}")[1].channel.recv_exit_status()

        steps: list[StepResult] = []
        commands = [*install_commands, execute_command]
        if not commands:
            raise ComputeSandboxError("no commands to run: install_commands and execute_command are both empty")

        deadline = time.monotonic() + wall_clock_seconds
        for i, cmd in enumerate(commands):
            is_last = i == len(commands) - 1
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ComputeSandboxError(
                    f"sandbox execution exceeded {wall_clock_seconds}s wall clock "
                    f"for the whole attempt (stopped before running '{cmd}')"
                )
            docker_cmd = (
                f"docker run --rm -v {remote_workdir}:/workspace -w /workspace "
                f"{base_image} bash -lc {_shell_quote(cmd)}"
            )
            exit_code, stdout, stderr, elapsed = _run_command_over_ssh(ssh, docker_cmd, timeout_seconds=remaining)
            # cost_usd=0.0: Nebius Compute's InstanceService does not return
            # per-run billing the way Token Factory Sandboxes' ContreeResult
            # does — see module docstring. Not fabricated; genuinely unknown
            # from this API alone.
            steps.append(StepResult(command=cmd, exit_code=exit_code, stdout=stdout, stderr=stderr,
                                     elapsed_seconds=elapsed, cost_usd=0.0))
            if exit_code != 0:
                break

        return SandboxRunResult(steps=tuple(steps), sandbox_id=instance_id)

    finally:
        if ssh is not None:
            try:
                ssh.close()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass
        if instance_id is not None:
            try:
                instances.delete(DeleteInstanceRequest(id=instance_id)).wait().sync_wait()
            except Exception:  # noqa: BLE001 - best-effort cleanup, matches sandbox.py's pattern
                pass


def _shell_quote(command: str) -> str:
    """POSIX single-quote a command for embedding in `bash -lc '...'` over
    SSH — commands come from planner.py (Nemotron-generated), not directly
    from repo content, but this is the actual command boundary and must not
    be built with naive string interpolation."""
    return "'" + command.replace("'", "'\\''") + "'"
