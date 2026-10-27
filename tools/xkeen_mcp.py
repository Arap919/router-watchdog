#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.20,<2"]
# ///
"""Local stdio MCP bridge to fixed router-watchdog operations over SSH."""
from __future__ import annotations

import json
import math
import threading
import os
import re
import subprocess
from typing import Any


def call_watchdog(
    operation: str, *, changes: dict[str, Any] | None = None,
    selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute one fixed command; never expose SSH stderr or raw router errors."""
    flags = {"measure": "--measure-selected --mcp-speed-profile",
             "find": "--find-faster --mcp-speed-profile",
             "get": "--get-config", "update": "--update-config", "select": "--select-node"}
    if operation not in flags:
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
    if operation == "select":
        if (not isinstance(selection, dict) or set(selection) != {"node", "expected_current"}
                or not all(isinstance(value, str) and value.strip() for value in selection.values())):
            raise ValueError("Selection requires nonempty node and expected_current strings")
        options["input"] = json.dumps(selection, ensure_ascii=False, allow_nan=False)
        if len(options["input"]) > 65536:
            raise ValueError("Selection request exceeds 64 KiB")
    elif selection is not None:
        raise ValueError("selection is supported only for node selection")
    if operation == "select" and os.environ.get("XKEEN_ALLOW_APPLY") != "1":
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
    command = "/opt/bin/router-watchdog " + flags[operation]
    argv = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=3", "-p", str(port), host, command]
    try:
        response = subprocess.run(argv, capture_output=True, text=True, timeout=None if operation in {"measure", "find"} else 1800,
                                  check=False, **options)
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
    safe_errors = {
        "download_timeout": "Speed-test download exceeded its time limit",
        "download_http_error": "Speed-test service returned an HTTP error",
        "download_network_error": "Speed-test connection failed",
        "download_incomplete": "Speed-test service returned insufficient data",
        "download_failed": "Speed-test download worker failed",
    }
    if (isinstance(payload, dict) and isinstance(payload.get("error"), str)
            and payload["error"] in safe_errors):
        code = payload["error"]
        raise RuntimeError(f"{code}: {safe_errors[code]}")
    if response.returncode != 0:
        raise RuntimeError("Router operation failed. Check SSH access, the installed watchdog version, "
                           "BENCHMARK configuration and router logs locally")
    valid = isinstance(payload, dict) and "error" not in payload
    if valid and operation in {"measure", "find"}:
        valid = type(payload.get("applied")) is bool
    elif valid and operation == "select":
        valid = (type(payload.get("applied")) is bool
                 and payload.get("selected_after") == selection["node"]
                 and isinstance(payload.get("group"), str))
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
    comparison: dict[str, Any] | None = None
    choice_lock = threading.Lock()

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                            idempotentHint=False, openWorldHint=True))
    def measure_selected_node() -> dict[str, Any]:
        """Measure download throughput (Mbps) and fresh delay of the selected concrete node.

        Uses real router traffic through BENCHMARK and the watchdog lock. This is
        an active download test, not current traffic monitoring. Production selection
        is preserved. Uses a fixed quick profile: 10 MB per stream, 4 streams,
        1 round (40 MB per node). Does not change saved watchdog settings.
        Return the result with its measurement timestamp to the user.
        """
        return call_watchdog("measure")

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                            idempotentHint=False, openWorldHint=True))
    def find_faster_node() -> dict[str, Any]:
        """Benchmark current node and eligible alternatives WITHOUT switching production.

        Consumes traffic through BENCHMARK. Uses configured target-group providers,
        existing healthchecks and minimum-delay +50 ms ranking. Uses a fixed quick
        profile: 10 MB per stream, 4 streams, 1 round (40 MB per node), without
        changing saved watchdog settings. Short tests are noisier; small throughput
        differences may be measurement noise.
        Show the user a comparative table of ALL successful results: exact node name,
        Mbps, fresh delay, difference from current, and mark the current node.
        Include measured_at and failed_speed_nodes; explain this is an active test.
        Then STOP and ask the user which measured node to select or whether to keep
        the current one. Never select automatically, even if the initial request
        asked for a faster node. Call select_measured_node only AFTER the user has
        seen the comparison and explicitly chosen a node. Any successful measured
        node may be chosen, including slower ones. Restart requires a new comparison.
        """
        nonlocal comparison
        with choice_lock:
            comparison = None
            result = call_watchdog("find")
            rows = result.get("results")
            current = result.get("current", {}).get("node")
            if (result.get("applied") is not False or not isinstance(current, str)
                    or not current or not isinstance(rows, list) or not rows):
                raise RuntimeError("Invalid comparison response; run a new comparison")
            measured = set()
            for row in rows:
                if (not isinstance(row, dict) or not isinstance(row.get("node"), str)
                        or not row["node"] or type(row.get("mbps")) not in (int, float)
                        or not math.isfinite(row["mbps"]) or row["mbps"] <= 0):
                    raise RuntimeError("Invalid comparison result; run a new comparison")
                measured.add(row["node"])
            if current not in measured:
                raise RuntimeError("Comparison baseline is missing; run a new comparison")
            comparison = {"current": current, "nodes": measured}
            return result

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                                            idempotentHint=False, openWorldHint=True))
    def select_measured_node(node: str) -> dict[str, Any]:
        """Switch to the exact node explicitly chosen AFTER showing a speed comparison.

        Only nodes successfully measured by the latest find_faster_node call in
        this MCP process are allowed. Requires local XKEEN_ALLOW_APPLY=1. Never
        infer user choice from the fastest result or an earlier general request.
        Router rechecks membership, availability and unchanged baseline under its
        shared lock; no repeat download test. Return verified selected_after and
        applied. A successful selection consumes the comparison, including a no-op.
        MCP cannot prove human consent; the client must enforce this conversation.
        """
        nonlocal comparison
        with choice_lock:
            if comparison is None or node not in comparison["nodes"]:
                raise ValueError("Choose a successfully measured node from a new comparison")
            result = call_watchdog("select", selection={
                "node": node, "expected_current": comparison["current"],
            })
            comparison = None
            return result

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
        nonlocal comparison
        with choice_lock:
            comparison = None
            return call_watchdog("update", changes=changes)

    return server


if __name__ == "__main__":
    build_server().run(transport="stdio")
