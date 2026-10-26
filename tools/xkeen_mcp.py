#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.20,<2"]
# ///
"""Local stdio MCP bridge to fixed router-watchdog operations over SSH."""
from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any


def call_watchdog(
    operation: str, *, apply: bool = False, changes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute one fixed command; never expose SSH stderr or raw router errors."""
    flags = {"measure": "--measure-selected", "find": "--find-faster",
             "get": "--get-config", "update": "--update-config"}
    if operation not in flags or (apply and operation != "find"):
        raise ValueError("Unsupported watchdog operation")
    options: dict[str, Any] = {}
    if operation == "update":
        if not isinstance(changes, dict) or not changes:
            raise ValueError("changes must be a nonempty settings object")
        options["input"] = json.dumps(changes, ensure_ascii=False, allow_nan=False)
        if len(options["input"]) > 65536:
            raise ValueError("Configuration patch exceeds 64 KiB")
    elif changes is not None:
        raise ValueError("changes is supported only for configuration updates")
    if apply and os.environ.get("XKEEN_ALLOW_APPLY") != "1":
        raise ValueError("Switching is disabled; set XKEEN_ALLOW_APPLY=1 locally to enable it")
    host = os.environ.get("XKEEN_SSH_HOST", "")
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@:-]*", host):
        raise ValueError("Set XKEEN_SSH_HOST to a hostname or SSH config alias")
    try:
        port = int(os.environ.get("XKEEN_SSH_PORT", "222"))
    except ValueError:
        raise ValueError("XKEEN_SSH_PORT must be an integer from 1 to 65535") from None
    if not 1 <= port <= 65535:
        raise ValueError("XKEEN_SSH_PORT must be an integer from 1 to 65535")
    command = "/opt/bin/router-watchdog " + flags[operation] + (" --apply" if apply else "")
    argv = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=3", "-p", str(port), host, command]
    try:
        response = subprocess.run(argv, capture_output=True, text=True, timeout=1800, check=False, **options)
    except subprocess.TimeoutExpired:
        raise RuntimeError("SSH timed out; the router operation may continue holding the shared lock. "
                           "Inspect router state before retrying; do not remove its lock file") from None
    except OSError:
        raise RuntimeError("Cannot start SSH; install OpenSSH and check the local SSH configuration") from None
    try:
        payload = json.loads(response.stdout)
    except (ValueError, TypeError):
        payload = None
    if isinstance(payload, dict) and payload.get("error") == "busy":
        raise RuntimeError("Router watchdog is busy; retry after the current operation completes")
    if response.returncode != 0:
        raise RuntimeError("Router operation failed. Check SSH access, the installed watchdog version, "
                           "BENCHMARK configuration and router logs locally")
    valid = isinstance(payload, dict) and "error" not in payload
    if valid and operation in {"measure", "find"}:
        valid = type(payload.get("applied")) is bool
    elif valid and operation == "get":
        valid = (isinstance(payload.get("config"), dict)
                 and isinstance(payload.get("editable_fields"), list)
                 and type(payload.get("secret_configured")) is bool
                 and "secret" not in payload["config"])
    elif valid and operation == "update":
        valid = (isinstance(payload.get("updated_fields"), list)
                 and type(payload.get("cron_sync_required")) is bool)
    if not valid:
        raise RuntimeError("Invalid router response; install a watchdog version supporting JSON MCP operations")
    return payload


def build_server():
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations

    server = FastMCP("xkeen-mihomo")

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                            idempotentHint=False, openWorldHint=True))
    def measure_selected_node() -> dict[str, Any]:
        """Measure download throughput (Mbps) and fresh delay of the selected concrete node.

        Uses real router traffic through BENCHMARK and the watchdog lock. This is
        an active download test, not current traffic monitoring. Production selection
        is preserved. Return the result with its measurement timestamp to the user.
        """
        return call_watchdog("measure")

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                                            idempotentHint=False, openWorldHint=True))
    def find_faster_node(apply: bool = False) -> dict[str, Any]:
        """Benchmark current node and eligible alternatives, returning a comparison.

        Consumes traffic. Uses existing watchdog healthchecks, download settings and
        minimum-delay +50 ms window. Only configured target-group providers are used.
        Default apply=False only reports results. Set apply=True only when the user
        explicitly requests switching AND local XKEEN_ALLOW_APPLY=1 permits it.
        A switch occurs only if the measured winner is faster than the current node.
        Report current/winner Mbps, delay, timestamp and whether a switch was applied.
        """
        return call_watchdog("find", apply=apply)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                            idempotentHint=True, openWorldHint=True))
    def get_watchdog_config() -> dict[str, Any]:
        """Read router-watchdog settings and editable field names; secret is omitted.

        Read this before proposing changes. Unknown legacy fields are not editable.
        Never ask the user to provide secrets in chat; manage secrets locally.
        """
        return call_watchdog("get")

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                                            idempotentHint=True, openWorldHint=True))
    def update_watchdog_config(changes: dict[str, Any]) -> dict[str, Any]:
        """Apply only user-requested settings in router-watchdog.json as a partial patch.

        Use field names from get_watchdog_config.editable_fields. The router rejects
        unknown fields, invalid types, ranges, URLs and nested schedule keys before
        any write. Unspecified settings are preserved. No arbitrary path is accepted.
        speed_test_url accepts HTTP(S) with optional {bytes} and {cache_bust} tokens.
        schedule replaces the complete schedule object: windows with start/end in
        HH:MM and integer every_minutes 1..1440. cron_sync_required means the JSON
        was saved but cron still needs separate synchronization. Uses shared lock.
        Secret values must be managed locally rather than requested through chat.
        """
        return call_watchdog("update", changes=changes)

    return server


if __name__ == "__main__":
    build_server().run(transport="stdio")
