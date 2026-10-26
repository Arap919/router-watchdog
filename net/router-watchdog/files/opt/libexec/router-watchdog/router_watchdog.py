#!/usr/bin/env python3
"""Cron-friendly Mihomo failover watchdog for provider-backed selector groups."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import math
import os
import re
import subprocess
import string
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get("ROUTER_WATCHDOG_CONFIG", "/opt/etc/router-watchdog.json"))
LOG_PATH = Path(os.environ.get("ROUTER_WATCHDOG_LOG", "/opt/share/router-watchdog.log"))
LOCK_PATH = Path("/tmp/router_watchdog.lock")
MIHOMO_CONFIG_PATH = Path("/opt/etc/mihomo/config.yaml")
DEFAULT_CRONTAB_PATH = Path("/opt/etc/crontab")
LEGACY_CRONTAB_PATH = Path("/opt/var/spool/cron/crontabs/root")
OLD_LEGACY_CRONTAB_PATH = Path("/opt/etc/crontabs/root")
CRONTAB_PATH = Path(os.environ.get("ROUTER_WATCHDOG_CRONTAB", DEFAULT_CRONTAB_PATH))
CRON_INIT_SCRIPT = Path("/opt/etc/init.d/S10cron")
CRON_BEGIN = "# BEGIN router-watchdog managed entries"
CRON_END = "# END router-watchdog managed entries"
LOCKED_WATCHDOG_COMMAND = (
    "/opt/bin/router-watchdog"
)
DEFAULT_SCHEDULE = {
    "windows": [
        {"start": "07:00", "end": "01:00", "every_minutes": 1},
        {"start": "01:00", "end": "07:00", "every_minutes": 30},
    ]
}


DEFAULT_SPEED_TEST_URL = "https://speed.cloudflare.com/__down?bytes={bytes}&cacheBust={cache_bust}"
CONFIG_FIELDS = frozenset({
    "controller", "secret", "target_group", "benchmark_group", "benchmark_proxy",
    "top_n", "healthcheck_parallelism", "healthcheck_timeout_ms",
    "speed_connect_timeout_seconds", "switch_wait_seconds", "speed_test_url",
    "download_bytes", "parallel_streams", "multi_rounds", "log_cleanup_days", "schedule",
})


class MihomoAPIError(RuntimeError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"Mihomo API: HTTP {status_code}: {detail}")
        self.status_code = status_code

def log(message: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    print(line, flush=True)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError as exc:
        print(f"Failed to write log file {LOG_PATH}: {exc}", file=sys.stderr)


def clear_log() -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOG_PATH.write_text("", encoding="utf-8")
    except OSError as exc:
        print(f"Failed to clear log file {LOG_PATH}: {exc}", file=sys.stderr)
        raise
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} Cleared log file {LOG_PATH}.")


def cleanup_days(cfg: dict[str, Any]) -> int:
    value = cfg.get("log_cleanup_days", 3)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 3650:
        raise ValueError("log_cleanup_days must be an integer between 1 and 3650")
    return value


def cleanup_log(days: int | None = None) -> None:
    """Called under the common watchdog lock; None means unconditional clear."""
    state = LOG_PATH.with_name(LOG_PATH.name + ".cleanup")
    now = time.time()
    if state.is_symlink():
        raise ValueError("Refusing symlinked log-cleanup state")
    if days is not None:
        if not state.exists():
            replace_text_file(state, f"{now}\n")
            print("Initialized log-cleanup interval; existing log retained.", flush=True)
            return
        try:
            last = float(state.read_text(encoding="utf-8").strip())
        except (ValueError, OSError) as exc:
            raise ValueError("Cannot read log-cleanup timestamp") from exc
        if not math.isfinite(last) or last < 0:
            raise ValueError("Invalid log-cleanup timestamp")
        if now - last < days * 86400:
            print("Log cleanup is not due.", flush=True)
            return
    clear_log()
    replace_text_file(state, f"{now}\n")


def number(cfg: dict[str, Any], key: str, low: int, high: int) -> int:
    try:
        value = int(cfg[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid configuration {key}") from exc
    if not low <= value <= high:
        raise ValueError(f"{key}: must be between {low} and {high}")
    return value


def minute_of_day(value: Any, field: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(
        r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value
    ):
        raise ValueError(f"schedule window {field} must use HH:MM (00:00-23:59)")
    hour, minute = (int(part) for part in value.split(":"))
    return hour * 60 + minute


def cron_field(values: set[int], maximum: int) -> str:
    if len(values) == maximum + 1:
        return "*"

    ordered = sorted(values)
    ranges: list[str] = []
    start = previous = ordered[0]
    for value in ordered[1:]:
        if value == previous + 1:
            previous = value
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = value
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(ranges)


def cron_entries(schedule: Any) -> list[str]:
    if not isinstance(schedule, dict) or set(schedule) != {"windows"}:
        raise ValueError("schedule must contain only a windows array")
    windows = schedule["windows"]
    if not isinstance(windows, list):
        raise ValueError("schedule.windows must be an array")

    scheduled_minutes: set[int] = set()
    for index, window in enumerate(windows):
        if not isinstance(window, dict) or set(window) != {
            "start",
            "end",
            "every_minutes",
        }:
            raise ValueError(
                f"schedule.windows[{index}] must contain start, end, and every_minutes"
            )
        start = minute_of_day(window["start"], f"windows[{index}].start")
        end = minute_of_day(window["end"], f"windows[{index}].end")
        interval = window["every_minutes"]
        if isinstance(interval, bool) or not isinstance(interval, int):
            raise ValueError(
                f"schedule.windows[{index}].every_minutes must be an integer"
            )
        if not 1 <= interval <= 1440:
            raise ValueError(
                f"schedule.windows[{index}].every_minutes must be between 1 and 1440"
            )
        duration = (end - start) % 1440 or 1440
        scheduled_minutes.update(
            (start + offset) % 1440 for offset in range(0, duration, interval)
        )

    minutes_by_hour: dict[int, set[int]] = {}
    for value in scheduled_minutes:
        hour, minute = divmod(value, 60)
        minutes_by_hour.setdefault(hour, set()).add(minute)

    hours_by_minutes: dict[tuple[int, ...], set[int]] = {}
    for hour, minutes in minutes_by_hour.items():
        hours_by_minutes.setdefault(tuple(sorted(minutes)), set()).add(hour)

    entries = [
        f"{cron_field(set(minutes), 59)} "
        f"{cron_field(hours, 23)} * * * root {LOCKED_WATCHDOG_COMMAND}"
        for minutes, hours in sorted(hours_by_minutes.items())
    ]
    entries.append("59 6 * * * root /opt/bin/router-watchdog --clear-log --if-due")
    return entries


def replace_text_file(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            temporary_path = handle.name
            handle.write(contents)
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)


def update_managed_crontab(path: Path, entries: list[str]) -> bool:
    if path.is_symlink():
        raise ValueError(f"Refusing to modify symlinked crontab: {path}")
    if not path.exists() and not entries:
        return False

    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = existing.splitlines(keepends=True)
    begin_indexes = [
        index for index, line in enumerate(lines) if line.rstrip("\r\n") == CRON_BEGIN
    ]
    end_indexes = [
        index for index, line in enumerate(lines) if line.rstrip("\r\n") == CRON_END
    ]
    if len(begin_indexes) != len(end_indexes) or len(begin_indexes) > 1:
        raise ValueError(f"Invalid router-watchdog markers in {path}")

    managed = [
        f"{CRON_BEGIN}\n",
        *(f"{entry}\n" for entry in entries),
        f"{CRON_END}\n",
    ]
    if begin_indexes:
        begin, end = begin_indexes[0], end_indexes[0]
        if end < begin:
            raise ValueError(f"Invalid router-watchdog markers in {path}")
        replacement = managed if entries else []
        updated = "".join(lines[:begin] + replacement + lines[end + 1 :])
    elif entries:
        prefix = existing
        if prefix and not prefix.endswith("\n"):
            prefix += "\n"
        updated = prefix + "".join(managed)
    else:
        return False

    if updated == existing:
        return False

    replace_text_file(path, updated)
    return True


def is_watchdog_cron_entry(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return False
    return (
        "/opt/bin/router-watchdog" in stripped
        or "/opt/libexec/router-watchdog/router_watchdog.py" in stripped
    )


def remove_legacy_watchdog_entries(path: Path) -> bool:
    if path.is_symlink():
        raise ValueError(f"Refusing to modify symlinked crontab: {path}")
    if not path.exists():
        return False
    existing = path.read_text(encoding="utf-8")
    lines = existing.splitlines(keepends=True)
    updated_lines: list[str] = []
    in_managed_block = False
    for line in lines:
        marker = line.rstrip("\r\n")
        if marker == CRON_BEGIN:
            in_managed_block = True
        elif marker == CRON_END:
            in_managed_block = False
        if not in_managed_block and marker not in {CRON_BEGIN, CRON_END}:
            if is_watchdog_cron_entry(line):
                continue
        updated_lines.append(line)
    updated = "".join(updated_lines)
    if updated == existing:
        return False
    replace_text_file(path, updated)
    return True


def restart_cron() -> None:
    subprocess.run([str(CRON_INIT_SCRIPT), "restart"], check=True)


class Mihomo:
    def __init__(self, base_url: str, secret: str = "") -> None:
        self.base = base_url.rstrip("/")
        self.secret = secret
        parsed = urllib.parse.urlparse(self.base)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("controller must start with http:// or https://")
        # API requests must bypass any system proxy.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self._provider_names: list[str] | None = None
        self._provider_cache: dict[str, dict[str, Any]] = {}
        log(f"Mihomo controller: {self.base}")

    def request(
        self,
        method: str,
        path: str,
        data: dict[str, Any] | None = None,
        timeout: float = 10,
    ) -> Any:
        headers = {"Accept": "application/json"}
        if self.secret:
            headers["Authorization"] = f"Bearer {self.secret}"
        body = None if data is None else json.dumps(data, ensure_ascii=False).encode()
        if data is not None:
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            self.base + path,
            data=body,
            headers=headers,
            method=method,
        )
        log(f"Request: {method} {path}")
        try:
            with self.opener.open(request, timeout=timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            # Provider refresh errors can contain private subscription URLs.
            exc.close()
            raise MihomoAPIError(exc.code, "controller request failed") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Mihomo API is unavailable: {exc.reason}") from exc

        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw.decode("utf-8", "replace")

    def proxy_group(self, group: str) -> dict[str, Any]:
        path = "/proxies/" + urllib.parse.quote(group, safe="")
        value = self.request("GET", path)
        if not isinstance(value, dict):
            raise RuntimeError(f"Unexpected response for group {group}")
        return value

    def proxy(self, node: str) -> dict[str, Any]:
        path = "/proxies/" + urllib.parse.quote(node, safe="")
        value = self.request("GET", path)
        if not isinstance(value, dict):
            raise RuntimeError(f"Unexpected response for proxy {node}")
        return value

    def provider(self, name: str) -> dict[str, Any]:
        if name in self._provider_cache:
            return self._provider_cache[name]
        path = "/providers/proxies/" + urllib.parse.quote(name, safe="")
        value = self.request("GET", path)
        if not isinstance(value, dict):
            raise RuntimeError(f"Unexpected response for proxy provider {name}")
        self._provider_cache[name] = value
        return value

    def provider_names(self) -> list[str]:
        if self._provider_names is None:
            value = self.request("GET", "/providers/proxies")
            providers = value.get("providers") if isinstance(value, dict) else None
            if not isinstance(providers, dict):
                raise RuntimeError("Unexpected response for proxy providers")
            self._provider_names = [
                name for name in providers if isinstance(name, str) and name
            ]
        return self._provider_names

    def providers_for_nodes(self, nodes: set[str]) -> dict[str, str]:
        unresolved = set(nodes)
        resolved: dict[str, str] = {}
        for provider_name in self.provider_names():
            if not unresolved:
                break
            data = self.provider(provider_name)
            proxies = data.get("proxies")
            if not isinstance(proxies, list):
                raise RuntimeError(
                    f"Provider {provider_name!r} does not contain a proxies list"
                )
            for proxy in proxies:
                if not isinstance(proxy, dict):
                    continue
                name = proxy.get("name")
                if isinstance(name, str) and name in unresolved:
                    resolved[name] = provider_name
                    unresolved.remove(name)
        return resolved

    def update_provider(self, name: str) -> None:
        path = "/providers/proxies/" + urllib.parse.quote(name, safe="")
        self.request("PUT", path, timeout=30)
        self._provider_cache.pop(name, None)

    def select(self, group: str, node: str, timeout: float = 5) -> None:
        path = "/proxies/" + urllib.parse.quote(group, safe="")
        self.request("PUT", path, {"name": node}, timeout)

    def provider_healthcheck(
        self,
        provider: str,
        node: str,
        url: str,
        timeout_ms: int,
        expected_status: int | None = None,
    ) -> int:
        query: dict[str, Any] = {"url": url, "timeout": timeout_ms}
        if expected_status is not None:
            query["expected"] = expected_status
        path = (
            "/providers/proxies/"
            + urllib.parse.quote(provider, safe="")
            + "/"
            + urllib.parse.quote(node, safe="")
            + "/healthcheck?"
            + urllib.parse.urlencode(query)
        )
        result = self.request("GET", path, timeout=timeout_ms / 1000 + 1)
        delay = result.get("delay") if isinstance(result, dict) else None
        if isinstance(delay, int) and delay > 0:
            return delay
        raise RuntimeError(f"Healthcheck did not confirm availability: {result!r}")


def latest_history_delay(item: dict[str, Any]) -> int | None:
    """Use exactly the last history latency; 0 means failed check, not 0 ms."""
    history = item.get("history")
    if not isinstance(history, list) or not history:
        return None
    last = history[-1]
    if not isinstance(last, dict):
        return None
    delay = last.get("delay")
    return delay if isinstance(delay, int) and delay > 0 else None


def provider_nodes(data: dict[str, Any], provider_name: str) -> list[dict[str, Any]]:
    items = data.get("proxies")
    if not isinstance(items, list):
        return []

    result: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        # Each entry in providers[].proxies is already a concrete node.
        result.append(
            {
                "name": name,
                "provider": provider_name,
                "alive": bool(item.get("alive")),
                "last_delay": latest_history_delay(item),
                "raw": item,
            }
        )
    return result


def provider_test_config(data: dict[str, Any]) -> tuple[str, int | None]:
    url = data.get("testUrl")
    if not isinstance(url, str) or not url:
        raise RuntimeError("Provider is missing testUrl")

    expected = data.get("expectedStatus")
    if expected is None:
        return url, None
    try:
        return url, int(expected)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Invalid provider expectedStatus: {expected!r}") from exc


def refresh(client: Mihomo, providers: list[str]) -> list[str]:
    refreshed: list[str] = []
    for provider in providers:
        for attempt in range(1, 6):
            try:
                client.update_provider(provider)
                log(f"Provider {provider} refreshed (attempt {attempt}/5).")
                refreshed.append(provider)
                break
            except Exception as exc:
                if attempt == 5:
                    log(
                        f"Skipping provider {provider} after 5 refresh attempts: {exc}"
                    )
                    break
                log(f"Failed to refresh provider {provider}: {exc}; retrying in 2 seconds ({attempt}/5).")
                time.sleep(2)
    if not refreshed:
        raise RuntimeError(
            "Failed to refresh any proxy provider; cannot select fresh candidates"
        )
    return refreshed


def current_node(client: Mihomo, group: str) -> str:
    value = client.proxy_group(group)
    now = value.get("now")
    if not isinstance(now, str) or not now:
        raise RuntimeError(f"Group {group} does not contain a current node")
    return now


def resolve_provider(client: Mihomo, node: str) -> str:
    try:
        value = client.proxy(node)
    except MihomoAPIError as exc:
        if exc.status_code != 404:
            raise
    else:
        provider = value.get("provider-name")
        if isinstance(provider, str) and provider:
            return provider

    providers = client.providers_for_nodes({node})
    if node in providers:
        return providers[node]
    raise RuntimeError(f"Provider not found for node {node!r}")


def providers_from_target_group(client: Mihomo, group: str) -> list[str]:
    """Resolve target-group nodes against provider data without per-node proxy requests."""
    value = client.proxy_group(group)
    all_nodes = value.get("all")
    if not isinstance(all_nodes, list):
        raise RuntimeError(f"Group {group} does not contain an all list")

    nodes = {name for name in all_nodes if isinstance(name, str) and name}
    resolved = client.providers_for_nodes(nodes)
    providers = set(resolved.values())
    unresolved = nodes - resolved.keys()
    if unresolved:
        log(
            f"Nodes in target_group {group!r} not found in any proxy provider: "
            + ", ".join(sorted(unresolved))
        )

    result = sorted(providers)
    if not result:
        raise RuntimeError(f"Failed to determine providers from target_group {group!r}")

    log(f"Providers from target_group {group}: {', '.join(result)}")
    return result


def check_current(
    client: Mihomo,
    node: str,
    provider: str,
    providers_data: dict[str, dict[str, Any]],
    timeout_ms: int,
) -> bool:
    data = providers_data[provider]
    url, expected = provider_test_config(data)
    try:
        delay = client.provider_healthcheck(provider, node, url, timeout_ms, expected)
        log(f"Current node {node}: healthcheck OK, {delay} ms.")
        return True
    except Exception as exc:
        log(f"Current node {node}: healthcheck FAIL: {exc}")
        return False


def fresh_check(
    client: Mihomo,
    item: dict[str, Any],
    provider_data: dict[str, Any],
    timeout_ms: int,
) -> tuple[str, int | None]:
    provider = str(item["provider"])
    name = str(item["name"])
    url, expected = provider_test_config(provider_data)
    try:
        delay = client.provider_healthcheck(provider, name, url, timeout_ms, expected)
        return name, delay
    except Exception as exc:
        log(f"Fresh healthcheck FAIL: {name}: {exc}")
        return name, None


def check_group_nodes(
    client: Mihomo, group: str, providers: list[str], timeout_ms: int, workers: int
) -> None:
    group_nodes = set(client.proxy_group(group)["all"])
    failed = 0
    total = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = []
        for provider in providers:
            data = client.provider(provider)
            for item in provider_nodes(data, provider):
                if item["name"] in group_nodes:
                    futures.append(pool.submit(fresh_check, client, item, data, timeout_ms))
        total = len(futures)
        for future in as_completed(futures):
            _, delay = future.result()
            if delay is None:
                failed += 1

    # Reload provider history after all healthchecks have completed.
    for provider in providers:
        client._provider_cache.pop(provider, None)
    log(f"Fresh healthcheck for group {group}: OK={total - failed}, FAIL={failed}, total={total}.")


def download_url(template: str, size: int) -> str:
    """Render only supported placeholders and validate the HTTP(S) service URL."""
    try:
        if not isinstance(template, str) or not template or any(ch.isspace() for ch in template):
            raise ValueError
        for _, field, spec, conversion in string.Formatter().parse(template):
            if field is not None and (field not in {"bytes", "cache_bust"} or spec or conversion):
                raise ValueError
        url = template.format(bytes=size, cache_bust=time.time_ns())
        parsed = urllib.parse.urlparse(url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.fragment):
            raise ValueError
        parsed.port
    except (ValueError, TypeError, KeyError, IndexError):
        raise ValueError("speed_test_url must be an HTTP(S) URL using only {bytes} and {cache_bust}") from None
    return url


def download(
    proxy: str, bytes_to_get: int, connect_timeout: int,
    url_template: str = DEFAULT_SPEED_TEST_URL,
) -> int:
    url = download_url(url_template, bytes_to_get)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    )
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "router-watchdog/4.0", "Cache-Control": "no-cache"},
    )
    received = 0
    with opener.open(request, timeout=connect_timeout) as response:
        # Keep the socket timeout: a stalled download must not hold the lock forever.
        while received < bytes_to_get:
            chunk = response.read(min(128 * 1024, bytes_to_get - received))
            if not chunk:
                break
            received += len(chunk)
    if received < bytes_to_get * 0.8:
        raise RuntimeError(f"Speed test received only {received / 1_000_000:.1f} MB")
    return received


def median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def measure_speed(client: Mihomo, cfg: dict[str, Any], node: str) -> float:
    timeout = number(cfg, "speed_connect_timeout_seconds", 1, 30)
    group = str(cfg.get("benchmark_group", "BENCHMARK"))
    if group == cfg["target_group"]:
        raise ValueError("benchmark_group must differ from target_group")
    client.select(group, node, timeout)
    log(f"Benchmark selector {group}: selected {node}.")
    time.sleep(float(cfg.get("switch_wait_seconds", 0.7)))

    proxy = str(cfg["benchmark_proxy"])
    size = number(cfg, "download_bytes", 1_000_000, 200_000_000)
    streams = number(cfg, "parallel_streams", 1, 8)
    rounds = number(cfg, "multi_rounds", 1, 4)
    values: list[float] = []

    for round_index in range(rounds):
        log(f"Speed-test round {round_index + 1}/{rounds}: {node}, {streams} streams.")
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=streams) as pool:
            received = sum(
                pool.map(lambda _: download(proxy, size, timeout, cfg.get("speed_test_url", DEFAULT_SPEED_TEST_URL)), range(streams))
            )
        elapsed = time.monotonic() - started
        speed = received * 8 / elapsed / 1_000_000
        values.append(speed)
        log(f"Speed-test round {round_index + 1}/{rounds}: {node}, {speed:.2f} Mbps.")

    return median(values)


def collect_nodes(
    client: Mihomo,
    providers: list[str],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    nodes: list[dict[str, Any]] = []
    provider_data: dict[str, dict[str, Any]] = {}

    for provider in providers:
        data = client.provider(provider)
        provider_data[provider] = data
        url, expected = provider_test_config(data)
        log(f"Provider {provider}: testUrl={url}, expectedStatus={expected}")
        nodes.extend(provider_nodes(data, provider))

    # A node name should be unique inside the group. If a subscription ever
    # produces duplicates, keep the first occurrence.
    unique: dict[str, dict[str, Any]] = {}
    for item in nodes:
        unique.setdefault(str(item["name"]), item)
    return list(unique.values()), provider_data


def validate_config(cfg: dict[str, Any]) -> dict[str, Any]:
    defaults = {
        "benchmark_group": "BENCHMARK", "benchmark_proxy": "http://127.0.0.1:17890",
        "top_n": 7, "healthcheck_parallelism": 6, "healthcheck_timeout_ms": 5000,
        "speed_connect_timeout_seconds": 5, "switch_wait_seconds": 0.7,
        "download_bytes": 25000000, "parallel_streams": 4, "multi_rounds": 2,
        "log_cleanup_days": 3, "speed_test_url": DEFAULT_SPEED_TEST_URL,
    }
    result = {**defaults, **cfg}
    download_url(result["speed_test_url"], 1_000_000)
    for key in ("controller", "target_group", "benchmark_group", "benchmark_proxy"):
        value = result.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must be a nonempty string")
    for key in ("controller", "benchmark_proxy"):
        parsed = urllib.parse.urlparse(result[key])
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError(f"{key} must be an HTTP(S) URL with a host")
        if parsed.username or parsed.password:
            raise ValueError(f"{key} must not contain URL credentials")
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError(f"{key} has an invalid port") from exc
    if result["target_group"] == result["benchmark_group"]:
        raise ValueError("benchmark_group must differ from target_group")
    if not isinstance(result.get("secret", ""), str):
        raise ValueError("secret must be a string")
    for key, low, high in (
        ("top_n", 1, 50), ("healthcheck_parallelism", 1, 32),
        ("healthcheck_timeout_ms", 250, 10000), ("speed_connect_timeout_seconds", 1, 30),
        ("download_bytes", 1000000, 200000000), ("parallel_streams", 1, 8),
        ("multi_rounds", 1, 4), ("log_cleanup_days", 1, 3650),
    ):
        if isinstance(result[key], bool) or not isinstance(result[key], int):
            raise ValueError(f"{key} must be an integer")
        number(result, key, low, high)
    wait = result["switch_wait_seconds"]
    if isinstance(wait, bool) or not isinstance(wait, (int, float)) or not math.isfinite(wait) or wait < 0:
        raise ValueError("switch_wait_seconds must be a finite nonnegative number")
    cron_entries(result.get("schedule", DEFAULT_SCHEDULE))
    return result


def configured_providers(group: str) -> list[str]:
    """Read the target selector's explicit provider references, never subscriptions."""
    try:
        import yaml
    except ImportError:
        raise RuntimeError("YAML support is missing; install python3-yaml") from None
    try:
        with MIHOMO_CONFIG_PATH.open(encoding="utf-8") as handle:
            config = yaml.safe_load(handle)
    except yaml.YAMLError:
        # Parser diagnostics can contain private subscription URLs.
        raise RuntimeError(f"Invalid YAML in {MIHOMO_CONFIG_PATH}") from None
    if not isinstance(config, dict):
        raise RuntimeError("Mihomo configuration must be a mapping")
    groups = config.get("proxy-groups")
    definitions = config.get("proxy-providers")
    if not isinstance(groups, list) or not isinstance(definitions, dict):
        raise RuntimeError("Mihomo configuration requires proxy-groups and proxy-providers")
    matches = [item for item in groups if isinstance(item, dict) and item.get("name") == group]
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one target_group {group!r} in Mihomo YAML")
    providers = matches[0].get("use")
    if (not isinstance(providers, list) or not providers
            or any(not isinstance(name, str) or not name for name in providers)):
        raise RuntimeError(f"target_group {group!r} requires a nonempty use list")
    if any(name not in definitions or not isinstance(definitions[name], dict)
           for name in providers):
        raise RuntimeError("Every target_group use entry must exist in proxy-providers")
    return list(dict.fromkeys(providers))


def target_candidates(
    client: Mihomo, group: str, providers: list[str],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    value = client.proxy_group(group)
    if value.get("type") != "Selector":
        raise RuntimeError(f"target_group {group!r} must be a Selector")
    members = value.get("all")
    if not isinstance(members, list):
        raise RuntimeError(f"Group {group!r} does not contain an all list")
    # Unicode escapes keep technical source ASCII without changing name matching.
    excluded = ("\u0440\u043e\u0441\u0441\u0438\u044f", "\u0443\u043a\u0440\u0430\u0438\u043d\u0430")
    allowed = []
    for name in members:
        if not isinstance(name, str) or not name:
            continue
        if any(word in name.casefold() for word in excluded):
            log(f"Excluded node by country name: {name}")
        else:
            allowed.append(name)
    wanted = set(allowed)
    found: dict[str, dict[str, Any]] = {}
    data_map: dict[str, dict[str, Any]] = {}
    for provider in providers:
        try:
            data = client.provider(provider)
            items = [item for item in provider_nodes(data, provider) if item["name"] in wanted]
            if items:
                provider_test_config(data)
                data_map[provider] = data
                for item in items:
                    found.setdefault(item["name"], item)
        except Exception as exc:
            log(f"Cannot read eligible nodes from provider {provider}: {exc}")
    nodes = [found[name] for name in dict.fromkeys(allowed) if name in found]
    log(f"Eligible provider-backed members of {group}: {len(nodes)}.")
    return nodes, data_map


def restore_service(
    client: Mihomo, cfg: dict[str, Any], nodes: list[dict[str, Any]],
    data: dict[str, dict[str, Any]],
) -> str | None:
    log("Looking for the first freshly confirmed emergency fallback.")
    for item in nodes:
        name, delay = fresh_check(client, item, data[item["provider"]], cfg["healthcheck_timeout_ms"])
        if delay is not None:
            client.select(cfg["target_group"], name)
            log(f"Emergency fallback selected: {name}, {delay} ms.")
            return name
    log("No working emergency fallback found; subscription recovery is required.")
    return None


def check_candidates(
    client: Mihomo, cfg: dict[str, Any], nodes: list[dict[str, Any]],
    data: dict[str, dict[str, Any]], restore: bool = False,
) -> list[tuple[dict[str, Any], int]]:
    checked = []
    restored = False
    with ThreadPoolExecutor(max_workers=cfg["healthcheck_parallelism"]) as pool:
        futures = {
            pool.submit(fresh_check, client, item, data[item["provider"]],
                        cfg["healthcheck_timeout_ms"]): item for item in nodes
        }
        for future in as_completed(futures):
            item = futures[future]
            name, delay = future.result()
            if delay is not None:
                checked.append((item, delay))
                log(f"Fresh healthcheck OK: {name}, {delay} ms.")
                if restore and not restored:
                    client.select(cfg["target_group"], name)
                    log(f"Emergency fallback selected after refresh: {name}, {delay} ms.")
                    restored = True
    checked.sort(key=lambda entry: (entry[1], str(entry[0]["name"])))
    log(f"Fresh healthchecks: OK={len(checked)}, FAIL={len(nodes) - len(checked)}.")
    return checked


def choose_winner(results: list[tuple[str, int, float]]) -> tuple[str, int, float]:
    valid = [r for r in results if r[1] > 0 and math.isfinite(r[2]) and r[2] > 0]
    if not valid:
        raise RuntimeError("Failed to measure speed for any candidate")
    minimum_delay = min(r[1] for r in valid)
    eligible = [r for r in valid if r[1] <= minimum_delay + 50]
    return min(eligible, key=lambda r: (-r[2], r[1], r[0]))


def benchmark_candidates(
    client: Mihomo, cfg: dict[str, Any], checked: list[tuple[dict[str, Any], int]],
) -> tuple[str, int, float] | None:
    benchmark = client.proxy_group(cfg["benchmark_group"])
    if benchmark.get("type") != "Selector" or not isinstance(benchmark.get("all"), list):
        raise RuntimeError("benchmark_group must be a Selector with an all list")
    members = set(benchmark["all"])
    results = []
    for item, delay in checked:
        name = str(item["name"])
        if name not in members:
            log(f"Skipping speed test: {name} is missing from benchmark_group.")
            continue
        try:
            speed = measure_speed(client, cfg, name)
            if not math.isfinite(speed) or speed <= 0:
                raise RuntimeError("Nonpositive or nonfinite throughput")
            results.append((name, delay, speed))
            log(f"Speed {name}: {speed:.2f} Mbps, fresh delay {delay} ms.")
        except Exception as exc:
            log(f"Speed-test failed for {name}: {exc}")
    return choose_winner(results) if results else None


def choose_and_apply(cfg: dict[str, Any]) -> None:
    cfg = validate_config(cfg)
    log("Configuration validated; starting watchdog.")
    if "fresh_top_n" in cfg or "close_result_percent" in cfg:
        log("Legacy fresh_top_n/close_result_percent are ignored; top_n and the 50 ms window apply.")
    client = Mihomo(cfg["controller"], cfg.get("secret", ""))
    group = cfg["target_group"]
    providers = configured_providers(group)
    log(f"Providers from target_group {group}: {', '.join(providers)}")
    try:
        node = current_node(client, group)
        log(f"Current node in group {group}: {node}")
        provider = None
        for name in providers:
            try:
                items = provider_nodes(client.provider(name), name)
            except Exception as exc:
                log(f"Cannot read current-node provider {name}: {exc}")
                continue
            if any(item["name"] == node for item in items):
                provider = name
                break
        if provider is None:
            raise RuntimeError("Current node not found in target_group providers")
        if check_current(client, node, provider, {provider: client.provider(provider)},
                         cfg["healthcheck_timeout_ms"]):
            log("Current node is healthy. No switch is required.")
            return
    except Exception as exc:
        log(f"Cannot confirm current node availability: {exc}")

    nodes, data = target_candidates(client, group, providers)
    fallback = restore_service(client, cfg, nodes, data)
    winner = None
    if fallback:
        historical = sorted((item for item in nodes if item["last_delay"] is not None),
                            key=lambda item: (item["last_delay"], item["name"]))
        shortlist = historical[:cfg["top_n"]]
        log("Historical shortlist: " + (", ".join(
            f"{item['name']} ({item['last_delay']} ms)" for item in shortlist) or "empty"))
        if shortlist:
            checked = check_candidates(client, cfg, shortlist, data)
            if checked:
                winner = benchmark_candidates(client, cfg, checked)
    if winner is None:
        log("No usable historical/fresh/speed result; starting one subscription recovery pass.")
        # Refresh only providers explicitly used by the production selector.
        try:
            refresh(client, providers)
        except RuntimeError as exc:
            log(f"Provider refresh failed; checking existing provider data anyway: {exc}")
        client._provider_cache.clear()
        nodes, data = target_candidates(client, group, providers)
        # Apply a fallback at the first positive fresh result, before waiting for
        # the remaining checks or starting any throughput measurements.
        checked = check_candidates(client, cfg, nodes, data, restore=True)
        if not checked:
            raise RuntimeError("No available eligible nodes after provider refresh and fresh healthchecks")
        winner = benchmark_candidates(client, cfg, checked[:cfg["top_n"]])
        if winner is None:
            raise RuntimeError("Failed to measure speed after provider recovery; emergency fallback retained")
    client.select(group, winner[0])
    log(f"Selected winner: {winner[0]} - {winner[2]:.2f} Mbps, {winner[1]} ms.")


def manual_speed(
    cfg: dict[str, Any], *, find_faster: bool = False, apply: bool = False,
) -> dict[str, Any]:
    """Measure a concrete selected member; callers must hold the shared lock."""
    if apply and not find_faster:
        raise ValueError("apply requires find_faster")
    cfg = validate_config(cfg)
    client = Mihomo(cfg["controller"], cfg.get("secret", ""))
    group = cfg["target_group"]
    selected = current_node(client, group)
    providers = configured_providers(group)
    nodes, data = target_candidates(client, group, providers)
    baseline = next((item for item in nodes if item["name"] == selected), None)
    if baseline is None:
        raise RuntimeError("Current selection must be a concrete eligible provider-backed member")
    benchmark = client.proxy_group(cfg["benchmark_group"])
    members = benchmark.get("all")
    if (benchmark.get("type") != "Selector" or not isinstance(members, list)
            or selected not in members):
        raise RuntimeError("Current node must belong to a Selector benchmark_group")
    # Synchronize before healthchecks, not only when the first download starts.
    client.select(cfg["benchmark_group"], selected, cfg["speed_connect_timeout_seconds"])
    if current_node(client, cfg["benchmark_group"]) != selected:
        raise RuntimeError("Failed to synchronize benchmark_group with the current target node")

    def measure(item: dict[str, Any], delay: int) -> tuple[str, int, float]:
        speed = measure_speed(client, cfg, item["name"])
        if not math.isfinite(speed) or speed <= 0:
            raise RuntimeError("Invalid measured throughput speed")
        return item["name"], delay, speed

    _, delay = fresh_check(client, baseline, data[baseline["provider"]],
                           cfg["healthcheck_timeout_ms"])
    if delay is None:
        raise RuntimeError("Current node failed fresh healthcheck; speed comparison unavailable")
    current = measure(baseline, delay)
    results = [current]
    failed = []
    if find_faster:
        others = [item for item in nodes if item["name"] != selected and item["name"] in members]
        checked = check_candidates(client, cfg, others, data)
        checked.sort(key=lambda pair: (pair[1], pair[0]["name"]))
        for item, delay in checked[:cfg["top_n"]]:
            try:
                results.append(measure(item, delay))
            except Exception:
                # Never return controller/download exception text to MCP clients.
                failed.append(item["name"])
    winner = choose_winner(results)
    faster = winner[2] > current[2]
    if current_node(client, group) != selected:
        raise RuntimeError("Target selection changed during measurement; no automatic switch performed")
    applied = False
    if apply and faster:
        live = client.proxy_group(group)
        if live.get("type") != "Selector" or winner[0] not in live.get("all", []):
            raise RuntimeError("Winner is no longer an eligible target member")
        client.select(group, winner[0])
        if current_node(client, group) != winner[0]:
            raise RuntimeError("Selection verification failed after switch; inspect current group state")
        applied = True

    def record(value: tuple[str, int, float]) -> dict[str, Any]:
        return {"node": value[0], "delay_ms": value[1], "mbps": value[2]}

    return {
        "group": group, "measurement": "download_throughput", "unit": "Mbps",
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "current": record(current), "winner": record(winner),
        "results": [record(value) for value in results], "failed_speed_nodes": failed,
        "faster": faster, "improvement_percent": (winner[2] / current[2] - 1) * 100,
        "applied": applied, "selected_after": winner[0] if applied else selected,
        "latency_window_ms": 50,
    }


def sync_cron(entries: list[str]) -> bool:
    changed = remove_legacy_watchdog_entries(CRONTAB_PATH)
    changed = update_managed_crontab(CRONTAB_PATH, entries) or changed

    for path in (LEGACY_CRONTAB_PATH, OLD_LEGACY_CRONTAB_PATH):
        if path == CRONTAB_PATH:
            continue
        path_changed = remove_legacy_watchdog_entries(path)
        path_changed = update_managed_crontab(path, []) or path_changed
        changed = path_changed or changed

    if changed:
        restart_cron()
    return changed


def config_view(cfg: dict[str, Any]) -> dict[str, Any]:
    """Expose only recognized settings; never return the controller secret."""
    return {
        "config": {key: value for key, value in cfg.items() if key in CONFIG_FIELDS and key != "secret"},
        "editable_fields": sorted(CONFIG_FIELDS),
        "secret_configured": bool(cfg.get("secret")),
    }


def update_config(cfg: dict[str, Any], changes: Any) -> dict[str, Any]:
    """Validate a partial patch and atomically write it; caller holds shared lock."""
    if not isinstance(changes, dict) or not changes or not set(changes) <= CONFIG_FIELDS:
        raise ValueError("Patch must be a nonempty object containing only supported settings")
    merged = {**cfg, **changes}
    validate_config(merged)
    updated = sorted(key for key in changes if key not in cfg or changes[key] != cfg[key])
    result = {"updated_fields": updated,
              "cron_sync_required": "schedule" in updated}
    if not updated:
        return result
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=CONFIG_PATH.parent,
                                         prefix=".router-watchdog-config.", delete=False) as handle:
            temporary_path = handle.name
            os.chmod(temporary_path, 0o600)
            json.dump(merged, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, CONFIG_PATH)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--sync-cron",
        action="store_true",
        help="synchronize this package's entries in /opt/etc/crontab",
    )
    action.add_argument(
        "--remove-cron",
        action="store_true",
        help="remove this package's cron entries",
    )
    action.add_argument(
        "--clear-log",
        action="store_true",
        help="truncate the watchdog log file",
    )
    action.add_argument("--measure-selected", action="store_true",
                        help="measure selected node through BENCHMARK and return JSON")
    action.add_argument("--find-faster", action="store_true",
                        help="compare selected node with freshly checked candidates; return JSON")
    action.add_argument("--get-config", action="store_true",
                        help="return recognized configuration without the secret as JSON")
    action.add_argument("--update-config", action="store_true",
                        help="apply a validated partial JSON patch from stdin")
    parser.add_argument("--apply", action="store_true",
                        help="with --find-faster, apply only a faster winner")
    if any(value in {"-h", "--help"} for value in sys.argv[1:]):
        parser.print_help()
        return 0
    parser.add_argument(
        "--if-due", action="store_true",
        help="with --clear-log, clear only after configured log_cleanup_days",
    )
    args = parser.parse_args()
    machine = args.measure_selected or args.find_faster or args.get_config or args.update_config
    if args.apply and not args.find_faster:
        parser.error("--apply requires --find-faster")
    if args.if_due and not args.clear_log:
        parser.error("--if-due requires --clear-log")

    needs_config = args.sync_cron or args.if_due or not (args.clear_log or args.remove_cron)
    if needs_config and not CONFIG_PATH.exists():
        if machine:
            print(json.dumps({"error": "configuration_missing"}))
            return 2
        log(f"Configuration file not found: {CONFIG_PATH}")
        return 2
    try:
        lock_fd = os.open(LOCK_PATH, os.O_CREAT | os.O_WRONLY, 0o600)
    except OSError as exc:
        if machine:
            print(json.dumps({"error": "lock_unavailable"}))
            return 1
        log(f"Failed to create watchdog lock {LOCK_PATH}: {exc}")
        return 1

    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if machine:
                print(json.dumps({"error": "busy"}))
                return 1
            log("Previous run is still in progress; skipping.")
            return 0
        if not args.clear_log and not machine:
            log(f"Lock acquired: {LOCK_PATH}, PID={os.getpid()}")
        cfg: dict[str, Any] = {}
        if needs_config:
            with CONFIG_PATH.open(encoding="utf-8") as handle:
                cfg = json.load(handle)
            if not isinstance(cfg, dict):
                raise ValueError("Configuration must be a JSON object")
        if args.clear_log:
            cleanup_log(cleanup_days(cfg) if args.if_due else None)
            return 0
        if args.remove_cron:
            changed = sync_cron([])
            log("Removed router-watchdog cron entries." if changed
                else "No router-watchdog cron entries found.")
            return 0
        if args.sync_cron:
            cleanup_days(cfg)
            entries = cron_entries(cfg.get("schedule", DEFAULT_SCHEDULE))
            changed = sync_cron(entries)
            if changed:
                log("Updated router-watchdog cron schedule.")
            return 0
        if args.get_config:
            print(json.dumps(config_view(cfg), ensure_ascii=False, allow_nan=False))
            return 0
        if args.update_config:
            patch_text = sys.stdin.read(65537)
            if len(patch_text) > 65536:
                raise ValueError("Configuration patch exceeds 64 KiB")
            result = update_config(cfg, json.loads(patch_text))
            print(json.dumps(result, ensure_ascii=False, allow_nan=False))
            return 0
        if machine:
            with contextlib.redirect_stdout(sys.stderr):
                result = manual_speed(cfg, find_faster=args.find_faster, apply=args.apply)
            print(json.dumps(result, ensure_ascii=False, allow_nan=False))
            return 0
        choose_and_apply(cfg)
        log("Watchdog completed successfully.")
        return 0
    except Exception as exc:
        if machine:
            # Raw exceptions can include private URLs or tokens.
            print(json.dumps({"error": "operation_failed",
                              "message": "Operation failed; check settings and router state locally"}))
            return 1
        if args.sync_cron:
            log(f"Failed to synchronize cron schedule: {exc}")
        elif args.remove_cron:
            log(f"Failed to remove cron entries: {exc}")
        else:
            log(f"Error: {exc}")
        return 1
    finally:
        os.close(lock_fd)


if __name__ == "__main__":
    raise SystemExit(main())
