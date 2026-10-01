"""What is known about the sandbox's resource limits (harness-v1.4.2-rc, D-38 / D-40), stored on every sandbox operation and quoted when an entry ends
RESOURCE_LIMIT.

Not a measurement of this run. The DOCUMENTED figures come from the public Nebius Token Factory / ConTree documentation and the installed SDK, read offline on
2026-10-01 (docs/design/D-40-resources.md): they say there is NO documented memory or CPU figure for a Sandboxes microVM, no way to choose a size, and a disk cap
of 12 GiB for the writable layer. What a particular kill looked like inside the sandbox is the EVIDENCE the harness collects with an evidence run
(runner_hooks.evidence_command) and parses (runner_hooks.parse_evidence). Where a figure is not documented it says so: no number is invented.
"""

from __future__ import annotations

# None = not documented anywhere the research could read.
DOCUMENTED_MEMORY: str | None = None
DOCUMENTED_CPU: str | None = None
DOCUMENTED_DISK_LAYER_BYTES = 12884901888  # api-reference spawn request: resources_limits.max_layer_bytes, default (exactly 12 GiB)
WORDING = ('the only wording is "Automatic cleanup and resource limits help prevent abuse." (docs.tokenfactory.nebius.com/sandboxes/overview) and '
           '"Built-in tracking of CPU time, memory usage, and I/O operations for every execution."')
LARGER_INSTANCE = ("not documented: the spawn request, the SDK, the CLI and the MCP tools have no memory, CPU, size or GPU parameter; Sandboxes is a beta "
                   "(access by request, contree@nebius.com); no price page (the product page says free while in beta, D-36)")
SOURCE = "docs/design/D-40-resources.md (public Nebius Token Factory / ConTree documentation and contree_sdk 0.3.6, read offline 2026-10-01)"


def record() -> dict:
    """The limits as stored on every sandbox operation (`operations[].resource_limits`)."""
    return {
        "memory": DOCUMENTED_MEMORY or f"not documented ({WORDING})",
        "cpu": DOCUMENTED_CPU or "not documented",
        "disk_layer_bytes": DOCUMENTED_DISK_LAYER_BYTES,
        "larger_instance": LARGER_INSTANCE,
        "source": SOURCE,
    }


def quote() -> str:
    """One sentence for a verdict reason when no limit could be read inside the sandbox."""
    memory = DOCUMENTED_MEMORY or "no documented per-operation memory limit"
    cpu = DOCUMENTED_CPU or "no documented CPU limit"
    return f"documented: {memory}, {cpu}, writable layer {DOCUMENTED_DISK_LAYER_BYTES} bytes; see {SOURCE}"
