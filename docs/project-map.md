# Project map

Status: failover redesign implemented and locally verified on 2026-10-15; no router deployment or package release performed.

## Repository layout

| Path | Responsibility |
| --- | --- |
| `net/router-watchdog/files/opt/libexec/router-watchdog/router_watchdog.py` | Runtime, CLI, Mihomo HTTP API client, healthchecks, throughput measurement, selection, logging, lock, cron management. Uses the Python standard library and PyYAML for target-group provider references. |
| `net/router-watchdog/files/opt/bin/router-watchdog` | Shell entry point; replaces itself with `/opt/bin/python3` running the runtime and forwards arguments. |
| `net/router-watchdog/files/opt/libexec/router-watchdog/merge_config.py` | Installation-time recursive defaults merge, exact `-old` backup and atomic writes with private permissions. Pre-install stages the exact original as `router-watchdog.json-upgrade` before opkg unpacking; post-install merges it before cron synchronization and removes staging only after success. |
| `net/router-watchdog/files/opt/etc/router-watchdog.json` | Package default configuration, installed as `/opt/share/router-watchdog/defaults.json` and as a private seed at `/opt/etc/router-watchdog.json`. The seed remains a regular payload file, never a registered conffile: retaining ownership prevents obsolete-file deletion followed by legacy conffile hashing of a missing file. Pre-install stages exact user bytes without overwriting a pending staging file on retry; post-install replaces the seed with the merged JSON. `INSTALL_CONF` sets permissions only, not conffile registration. Filled user fields survive only within the new schema; lists are replaced wholesale. |
| `net/router-watchdog/files/opt/etc/cron.1min/router-watchdog` | Existing Entware hook; executes `--sync-cron`, not the selection algorithm. |
| `net/router-watchdog/Makefile` | Entware/OpenWrt package definition, dependencies, installation, post-install cron synchronization, pre-removal cron cleanup. Inspected version: `1.0.6-1`; architecture `all`. |
| `net/router-watchdog/test.sh` | Installed-package smoke check; requires router paths and is not a host-side unit-test runner. |
| `net/router-watchdog/LICENSE` | MIT license. |
| `tests/test_cli.py` | Existing CLI, provider API, logging, lock and cron tests; imports runtime directly by path. |
| `tests/test_failover.py` | Stateful controller fixture tests failover sequencing, selector isolation, membership, exclusions, recovery, validation and winner ranking. |
| `tests/test_cleanup.py` | Temporary-file tests for cleanup intervals, timestamps, manual cleanup, invalid input and shared-lock contention. |
| `.github/workflows/lint.yml` | Python compilation, unit tests, Cyrillic restriction on technical runtime source, exact default-config key check. |
| `.github/workflows/build-package.yml` | Entware Docker build, package artifacts, tagged releases and Pages feed publishing. |
| `myMihomoCongif.yml` | User-supplied Mihomo configuration reference; exact spelling is intentional. Not installed by the package. Initially untracked. May contain private subscription URLs; do not reproduce them in documentation or logs. |
| `README.md` | Russian installation, configuration, migration, operation and local verification guide. |
| `docs/` | Approved design, this map, user-facing implementation plan and documentation index. |
| `.agents/skills/router-watchdog-context/SKILL.md` | Repository-local reference skill. |
| `AGENTS.md` | Agent entry point and repository constraints. |

## Runtime boundaries

`main()` handles `--help`, `--sync-cron`, `--remove-cron`, `--clear-log` (optionally `--if-due`), configuration loading, shared action locking and exit codes. `choose_and_apply()` owns the failover flow. `validate_config()` checks/defaults settings before controller access. `target_candidates()` filters actual production-group members, `restore_service()` applies the first freshly confirmed fallback, `check_candidates()` performs parallel checks (with immediate fallback during recovery), `benchmark_candidates()` isolates testing, and `choose_winner()` applies the latency window. `measure_speed()` selects a node then performs parallel download streams and takes the median across rounds.

Normal runs read `/opt/etc/mihomo/config.yaml` with PyYAML and validate target-group `use` entries against `proxy-providers`; current-node lookup, discovery and recovery are restricted to that list. Unrelated providers are never enumerated during normal runs.

`Mihomo` bypasses system proxies for controller requests. Provider data and provider names are cached within the client. `update_provider()` invalidates provider details. Fresh healthchecks use provider-owned `testUrl` and `expectedStatus` through `/providers/proxies/{provider}/{node}/healthcheck`; positive integer delay confirms availability. `latest_history_delay()` considers only the last history entry; zero/absent delay is unavailable history.

`target_candidates()` reads fresh group membership and retains only provider-backed concrete members, with country-name exclusions. Older helpers `providers_from_target_group()`, `collect_nodes()` and `check_group_nodes()` remain covered by existing tests but no longer drive normal failover; `collect_nodes()` alone is provider-wide, not group-filtered.

## Installed paths and cron

| Resource | Existing path |
| --- | --- |
| CLI | `/opt/bin/router-watchdog` |
| Python runtime | `/opt/libexec/router-watchdog/router_watchdog.py` |
| JSON configuration | `/opt/etc/router-watchdog.json` |
| Log | `/opt/share/router-watchdog.log` |
| Last successful cleanup timestamp | `/opt/share/router-watchdog.log.cleanup` |
| Lock | `/tmp/router_watchdog.lock` |
| Managed system crontab | `/opt/etc/crontab` |
| Legacy per-user crontab | `/opt/var/spool/cron/crontabs/root` |
| Older legacy crontab | `/opt/etc/crontabs/root` |
| Cron synchronization hook | `/opt/etc/cron.1min/router-watchdog` |
| Cron restart script | `/opt/etc/init.d/S10cron` |

System-crontab entries include `root`; legacy per-user entries do not. Managed entries are delimited by `# BEGIN router-watchdog managed entries` and `# END router-watchdog managed entries`. Unrelated jobs must survive synchronization/removal. Synchronization restarts cron only when entries change.

Environment overrides exist for config, log and managed crontab: `ROUTER_WATCHDOG_CONFIG`, `ROUTER_WATCHDOG_LOG`, `ROUTER_WATCHDOG_CRONTAB`. All actions except help use nonblocking `fcntl.flock`; the lock file remains in place, and closing its descriptor releases the lock. Missing configuration returns 2; operational errors return 1; successful/skipped normal runs return 0.

## Existing defaults

`controller=http://127.0.0.1:9090`, empty `secret` and `target_group`, `benchmark_group=BENCHMARK`, `benchmark_proxy=http://127.0.0.1:17890`, `top_n=7`, `healthcheck_parallelism=6`, `healthcheck_timeout_ms=5000`, `speed_connect_timeout_seconds=5`, `switch_wait_seconds=0.7`, `download_bytes=25000000`, `parallel_streams=4`, `multi_rounds=2`, `log_cleanup_days=3`. Old `fresh_top_n` and `close_result_percent` keys are accepted but ignored and logged.

The schedule runs every minute from 07:00 to 01:00 and every 30 minutes from 01:00 to 07:00, in router-local time. Windows are start-inclusive/end-exclusive; midnight crossing is supported. Log cleanup is checked daily at 06:59; the timestamp sidecar enforces elapsed days, default 3. First check initializes the timer without truncation. Manual cleanup resets it; failed truncation never advances it. All cleanup actions hold the same lock as watchdog runs.

## Implemented behavior and validation limits

A healthy current node exits immediately after its provider-owned fresh check. On failure, the first working eligible group member is selected before benchmarks. Last positive history ranks top_n candidates; fresh checks confirm availability and all responding shortlisted nodes are measured only through BENCHMARK. Among successful measurements within +50 ms of the minimum fresh delay, greatest speed wins. Failure of history, checks, speed tests or initial restoration triggers one refresh of providers referenced by the target group's YAML `use` list and a new fresh-check/rank/benchmark pass. A successful recovery check applies an emergency fallback immediately; failed measurements retain it and report an error.

The reference YAML uses shared list anchors, the existing subscription selector first, an explicit built-in GLOBAL display order, and a hidden benchmark selector with a loopback listener. Existing `Global` remains because routing rules reference it; its undefined `Proxy` member was replaced with the existing subscription/DIRECT choices. Provider settings, DNS and routing rules were compared structurally before/after and preserved.

Known pre-existing YAML issue: final `MATCH,Other` references `Other`, while the defined group is `other`. The routing rule was preserved rather than expanding scope to change routing. Native Mihomo validation is unavailable on this host (no binary); YAML syntax/aliases and selector references were checked using Ruby Psych. Local unit tests do not validate a real controller or router.

## Local verification

Run from the repository root:

```sh
python3 -m unittest discover -s tests -v
python3 -m py_compile net/router-watchdog/files/opt/libexec/router-watchdog/router_watchdog.py
sh -n net/router-watchdog/files/opt/bin/router-watchdog
sh -n net/router-watchdog/files/opt/etc/cron.1min/router-watchdog
git diff --check
```

Do not run the normal watchdog, `--sync-cron` or `--remove-cron` against production during local verification. Unit tests mock controller calls and redirect filesystem effects. Package builds require the Entware build environment; Python compilation/unit tests do not prove router execution or an IPK build.

When adding config fields, update defaults, runtime validation, tests, root README and `.github/workflows/lint.yml`'s exact key set together. The CI Cyrillic check now covers runtime source only; the user-facing README is Russian and technical runtime logs remain English.

## Manual speed operations and local MCP

`manual_speed()` reuses `target_candidates`, `fresh_check`, `check_candidates`, `measure_speed` and `choose_winner`. CLI actions `--measure-selected` and `--find-faster` return JSON under the existing shared lock; `--apply` is valid only with `--find-faster`. Machine-mode logs go to stderr; busy and operation failures return nonzero status and sanitized JSON. Automatic failover is unchanged.

`tools/xkeen_mcp.py` is a local stdio MCP server using the Python SDK 1.x. It executes fixed SSH commands on port 222 by default. `measure_selected_node` measures the baseline; `find_faster_node` compares up to top_n fresh lowest-latency alternatives plus baseline, using the existing 50 ms winner window. Applying requires both `apply=true` and local `XKEEN_ALLOW_APPLY=1`; only a strictly faster measured winner can be applied. The server does not deploy itself or the router package.

Tests: `tests/test_manual_speed.py` covers selection isolation, baseline errors, comparison, switching and CLI locking/output; `tests/test_mcp_server.py` covers SSH boundaries; `tests/test_mcp_stdio.py` uses a real SDK client/server with fake SSH. See `tools/README.md` for setup and validation boundaries.

## Configurable speed service and config MCP tools

`speed_test_url` defaults to the previous Cloudflare download endpoint. `download_url()` accepts HTTP(S) templates with only `{bytes}` and `{cache_bust}`, or a static file URL; `measure_speed()` forwards it to every download stream. Existing configs without the field retain the default. Package defaults, runtime validation and CI key checks include the new field.

`CONFIG_FIELDS` matches the packaged schema. `config_view()` exposes recognized saved fields excluding `secret`; `update_config()` rejects unknown patch keys and validates the merged config before an atomic mode-0600 replacement. Existing unspecified and legacy fields remain unchanged. Nested schedule keys are validated by `cron_entries()`. The caller holds the shared lock. A changed schedule returns `cron_sync_required=true`; no implicit crontab update occurs.

CLI `--get-config` and `--update-config` return JSON; the latter accepts a partial JSON object (up to 64 KiB) on stdin. MCP tools `get_watchdog_config` and `update_watchdog_config` use these fixed commands; patch values never enter shell command text. `tests/test_config_tools.py` checks URL handling, schema matching, validation, preservation, private permissions, atomic failure and CLI locking/redaction. Extended SSH and stdio tests cover the new tools.

Manual speed operations synchronize `benchmark_group` with the concrete current `target_group` member before the first healthcheck. The selection is verified; failed synchronization aborts before measurements. Both CLI and MCP share this path; automatic failover is unchanged.

## Release artifact promotion (1.0.10)

`.github/workflows/build-package.yml` builds IPK/feed for PRs and main pushes only. Tag pushes run a separate `release` job, never the Entware builder. `.github/scripts/select_release_build.py` resolves the checked-out tag commit to a successful completed `push` run of this workflow on `main`, using full SHA matching and paginated run/artifact APIs. Both artifacts must be available and nonexpired in the same run. No other commit or automatic build fallback is allowed.

Release and Pages jobs download immutable artifacts by ID and run ID with `actions: read`. Before release publication, the tag/Makefile/IPK versions, package identity/architecture and feed bytes/checksum/size/compressed metadata are verified. Pages downloads the same selected feed after release succeeds. Existing manual feed republication is unchanged. `tests/test_release_workflow.py` covers selection, pagination, missing/expired artifacts, tag job wiring and actual payload verification scripts using local IPK fixtures.

## Fast script package and update integration (1.0.11)

`scripts/build_package.py` builds the architecture-independent IPK directly with Python stdlib from Makefile metadata/install directives/hooks, without the Entware SDK. It creates the static feed and published `update.json` (schema 1, full package version, pinned package/release URLs, SHA256, size, optional release notes). The installer script is uploaded with the IPK from the same successful main run. Tag promotion remains exact-SHA and never builds.

`install.sh` bootstraps the existing Entware package manager/feed and invokes normal opkg install/upgrade; package ownership and config migration remain unchanged. `update_service.py` handles manifest validation, numeric version comparison, bounded package download, hash/size/control checks and explicit pinned installation. CLI `--check-update` / `--install-update --expected-version X.Y.Z-N` runs before configuration or controller access. The dedicated update mutex avoids deadlocking opkg postinst's normal `--sync-cron`; no automatic install or notification delivery is added to watchdog. Xkeen-UI owns periodic checks and browser Web Push in its separate repository.

Tests: `test_package_builder.py` for real archives/feed; `test_installer.py` uses fake opkg; `test_update_service.py` covers manifest/version validation, download integrity, pinned install, error/no-op behavior and config-independent CLI routing. Real router opkg lifecycle remains a deployment-side validation requirement.
