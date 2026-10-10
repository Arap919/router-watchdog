#!/usr/bin/env python3
"""Cron-friendly Mihomo failover watchdog for provider-backed selector groups."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
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
LOCK_PATH = ROOT / "router-watchdog.lock"
DEFAULT_CRONTAB_PATH = Path("/opt/etc/crontab")
LEGACY_CRONTAB_PATH = Path("/opt/var/spool/cron/crontabs/root")
OLD_LEGACY_CRONTAB_PATH = Path("/opt/etc/crontabs/root")
CRONTAB_PATH = Path(os.environ.get("ROUTER_WATCHDOG_CRONTAB", DEFAULT_CRONTAB_PATH))
CRON_INIT_SCRIPT = Path("/opt/etc/init.d/S10cron")
CRON_BEGIN = "# BEGIN router-watchdog managed entries"
CRON_END = "# END router-watchdog managed entries"
LOCKED_WATCHDOG_COMMAND = (
    "/opt/bin/flock -n /tmp/router_watchdog.lock /opt/bin/router-watchdog"
)
DEFAULT_SCHEDULE = {
    "windows": [
        {"start": "07:00", "end": "01:00", "every_minutes": 1},
        {"start": "01:00", "end": "07:00", "every_minutes": 30},
    ]
}


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
    entries.append("59 6 * * 0 root /opt/bin/router-watchdog --clear-log")
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
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise MihomoAPIError(exc.code, detail) from exc
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


def download(proxy: str, bytes_to_get: int, connect_timeout: int) -> int:
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    )
    url = f"https://speed.cloudflare.com/__down?bytes={bytes_to_get}&cacheBust={time.time_ns()}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "router-watchdog/4.0", "Cache-Control": "no-cache"},
    )
    received = 0
    with opener.open(request, timeout=connect_timeout) as response:
        try:
            response.fp.raw._sock.settimeout(None)
        except (AttributeError, OSError):
            pass
        while chunk := response.read(128 * 1024):
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
    group = str(cfg["target_group"])
    client.select(group, node, timeout)
    time.sleep(float(cfg.get("switch_wait_seconds", 0.7)))

    proxy = str(cfg["benchmark_proxy"])
    size = number(cfg, "download_bytes", 1_000_000, 200_000_000)
    streams = number(cfg, "parallel_streams", 1, 8)
    rounds = number(cfg, "multi_rounds", 1, 4)
    values: list[float] = []

    for _ in range(rounds):
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=streams) as pool:
            received = sum(
                pool.map(lambda _: download(proxy, size, timeout), range(streams))
            )
        elapsed = time.monotonic() - started
        values.append(received * 8 / elapsed / 1_000_000)

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


def choose_and_apply(cfg: dict[str, Any]) -> None:
    client = Mihomo(str(cfg["controller"]), str(cfg.get("secret", "")))
    group = str(cfg["target_group"])
    health_timeout = number(cfg, "healthcheck_timeout_ms", 250, 10000)
    workers = number(cfg, "healthcheck_parallelism", 1, 32)

    node = current_node(client, group)
    log(f"Current node in group {group}: {node}")

    # The current node is ALWAYS checked with a fresh provider healthcheck.
    # Do not use alive/history here: they may be stale because provider healthcheck
    # runs every 5 minutes and lazy providers may not check unused nodes.
    # No /proxies/<node>/delay: provider-owned nodes are checked through
    # /providers/proxies/{provider}/{node}/healthcheck.
    current_provider = resolve_provider(client, node)
    current_provider_data = client.provider(current_provider)
    current_provider_data_map = {current_provider: current_provider_data}
    if check_current(
        client, node, current_provider, current_provider_data_map, health_timeout
    ):
        log("Current node is healthy. No switch is required.")
        return

    log("Current node failed the fresh healthcheck; starting candidate selection.")
    providers = providers_from_target_group(client, group)
    providers = refresh(client, providers)
    nodes, provider_data = collect_nodes(client, providers)

    # Initial ranking: ONLY the last history latency, exactly as requested.
    historical = [
        item for item in nodes
        if item["alive"] and item["last_delay"] is not None
    ]
    historical.sort(key=lambda item: int(item["last_delay"]))
    top_n = number(cfg, "top_n", 1, 50)
    shortlist = historical[:top_n]

    log(
        "Top {} by latest history.delay: {}".format(
            top_n,
            ", ".join(
                f'{item["name"]} ({item["last_delay"]} ms)'
                for item in shortlist
            ) or "no candidates",
        )
    )

    if not shortlist:
        raise RuntimeError("No nodes with a positive latest history.delay")

    # Fresh-check the shortlist. If 3+ of these fail, assume the cached
    # provider health state is unreliable and check every concrete proxy.
    def check(item: dict[str, Any]) -> tuple[str, int | None]:
        return fresh_check(client, item, provider_data[str(item["provider"])], health_timeout)

    checked: list[tuple[dict[str, Any], int]] = []
    failed = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(check, item): item for item in shortlist}
        for future in as_completed(futures):
            item = futures[future]
            name, delay = future.result()
            if delay is None:
                failed += 1
            else:
                checked.append((item, delay))

    log(f"Fresh healthcheck for top-{len(shortlist)}: OK={len(checked)}, FAIL={failed}.")

    if failed >= 3:
        log("3 or more candidates failed the fresh healthcheck; running a full fresh healthcheck for all proxies.")
        checked = []
        failed_all = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(check, item): item for item in nodes}
            for future in as_completed(futures):
                item = futures[future]
                _, delay = future.result()
                if delay is None:
                    failed_all += 1
                else:
                    checked.append((item, delay))
        log(f"Full fresh healthcheck: OK={len(checked)}, FAIL={failed_all}, total={len(nodes)}.")

    if not checked:
        raise RuntimeError("No available nodes remain after the fresh healthcheck")

    checked.sort(key=lambda value: value[1])
    fresh_top_n = number(cfg, "fresh_top_n", 1, 30)
    finalists = checked[:fresh_top_n]
    log(
        "Speed-test candidates: "
        + ", ".join(f"{item['name']} ({delay} ms)" for item, delay in finalists)
    )

    tested: list[tuple[str, int, float]] = []
    for item, delay in finalists:
        name = str(item["name"])
        try:
            speed = measure_speed(client, cfg, name)
            tested.append((name, delay, speed))
            log(f"Speed {name}: {speed:.2f} Mbps, healthcheck {delay} ms")
        except Exception as exc:
            log(f"Speed-test failed for {name}: {exc}")

    if not tested:
        raise RuntimeError("Failed to measure speed for any finalist")

    # Highest speed wins. If speeds are close, lower fresh latency wins.
    tested.sort(key=lambda value: value[2], reverse=True)
    tolerance = number(cfg, "close_result_percent", 0, 50) / 100
    best_speed = tested[0][2]
    close = [value for value in tested if value[2] >= best_speed * (1 - tolerance)]
    winner = min(close, key=lambda value: value[1])

    client.select(group, winner[0])
    log(
        f"Selected winner: {winner[0]} — "
        f"{winner[2]:.2f} Mbps, {winner[1]} ms."
    )


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
    if any(value in {"-h", "--help"} for value in sys.argv[1:]):
        parser.print_help()
        return 0
    args = parser.parse_args()

    if args.clear_log:
        try:
            clear_log()
            return 0
        except OSError:
            return 1

    if args.remove_cron:
        try:
            changed = sync_cron([])
            log(
                "Removed router-watchdog cron entries."
                if changed
                else "No router-watchdog cron entries found."
            )
            return 0
        except Exception as exc:
            log(f"Failed to remove cron entries: {exc}")
            return 1

    if args.sync_cron:
        if not CONFIG_PATH.exists():
            log(f"Configuration file not found: {CONFIG_PATH}")
            return 2
        try:
            with CONFIG_PATH.open(encoding="utf-8") as handle:
                cfg = json.load(handle)
            if not isinstance(cfg, dict):
                raise ValueError("Configuration must be a JSON object")
            entries = cron_entries(cfg.get("schedule", DEFAULT_SCHEDULE))
            changed = sync_cron(entries)
            if changed:
                log(
                    "Updated router-watchdog cron schedule."
                    if entries
                    else "Removed router-watchdog cron schedule."
                )
            return 0
        except Exception as exc:
            log(f"Failed to synchronize cron schedule: {exc}")
            return 1

    if not CONFIG_PATH.exists():
        log(f"Configuration file not found: {CONFIG_PATH}")
        return 2
    try:
        lock_fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        log("Previous run is still in progress; skipping.")
        return 0
    except OSError as exc:
        log(f"Failed to create watchdog lock {LOCK_PATH}: {exc}")
        return 1

    try:
        with CONFIG_PATH.open(encoding="utf-8") as handle:
            cfg = json.load(handle)
        if not isinstance(cfg, dict):
            raise ValueError("Configuration must be a JSON object")

        choose_and_apply(cfg)
        return 0
    except Exception as exc:
        log(f"Error: {exc}")
        return 1
    finally:
        try:
            os.close(lock_fd)
        finally:
            try:
                LOCK_PATH.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                log(f"Failed to remove watchdog lock {LOCK_PATH}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
