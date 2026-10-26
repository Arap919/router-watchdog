# Graph Report - router-watchdog  (2026-10-26)

## Corpus Check
- 28 files · ~20,028 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 4 file(s) not represented in the graph (top: (none) 4)

## Summary
- 515 nodes · 865 edges · 31 communities (19 shown, 12 thin omitted)
- Extraction: 92% EXTRACTED · 8% INFERRED · 0% AMBIGUOUS · INFERRED: 69 edges (avg confidence: 0.9)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `a7e6a50c`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- router_watchdog.py
- Controller
- test_cli.py
- with
- BlancVPN
- mihomo-example.yml
- TestProviderResolution
- TestManualSpeed
- lint.yml
- dns
- TestCronSchedule
- TestConfigMerge
- ads
- release_tag
- sniffer
- router-watchdog
- TestCleanup
- TestMCPBridge
- TestConfigTools
- TestSpeedService
- listeners
- proxy-groups
- geox-url
- profile
- replace_text_file
- call_watchdog
- TestManualCLI
- План реализации MCP для Mihomo
- test.sh

## God Nodes (most connected - your core abstractions)
1. `Controller` - 30 edges
2. `Mihomo` - 27 edges
3. `TestFailover` - 26 edges
4. `choose_and_apply()` - 18 edges
5. `manual_speed()` - 18 edges
6. `TestManualSpeed` - 18 edges
7. `log()` - 17 edges
8. `main()` - 16 edges
9. `measure_speed()` - 15 edges
10. `Runtime boundaries` - 15 edges

## Surprising Connections (you probably didn't know these)
- `1. Конфигурация и изоляция замеров` --references--> `measure_speed()`  [INFERRED]
  docs/implementation-plan.md → net/router-watchdog/files/opt/libexec/router-watchdog/router_watchdog.py
- `Поведение` --references--> `choose_winner()`  [INFERRED]
  tools/README.md → net/router-watchdog/files/opt/libexec/router-watchdog/router_watchdog.py
- `Configurable speed service and config MCP tools` --references--> `cron_entries()`  [INFERRED]
  docs/project-map.md → net/router-watchdog/files/opt/libexec/router-watchdog/router_watchdog.py
- `Configurable speed service and config MCP tools` --references--> `download_url()`  [INFERRED]
  docs/project-map.md → net/router-watchdog/files/opt/libexec/router-watchdog/router_watchdog.py
- `Configurable speed service and config MCP tools` --references--> `measure_speed()`  [INFERRED]
  docs/project-map.md → net/router-watchdog/files/opt/libexec/router-watchdog/router_watchdog.py

## Import Cycles
- None detected.

## Communities (31 total, 12 thin omitted)

### Community 0 - "router_watchdog.py"
Cohesion: 0.09
Nodes (39): Manual speed operations and local MCP, Runtime boundaries, benchmark_candidates(), check_candidates(), check_current(), check_group_nodes(), choose_and_apply(), choose_winner() (+31 more)

### Community 1 - "Controller"
Cohesion: 0.08
Nodes (4): Controller, TestFailover, read(), TestMCPStdio

### Community 2 - "test_cli.py"
Cohesion: 0.18
Nodes (5): atomic_write(), install(), merge(), update_config(), TestRouterWatchdogCli

### Community 3 - "with"
Cohesion: 0.07
Nodes (41): if, permissions, runs-on, steps, GH_TOKEN, RELEASE_TAG, name, url (+33 more)

### Community 4 - "BlancVPN"
Cohesion: 0.12
Nodes (22): header, health-check, interval, override, type, url, User-Agent, x-hwid (+14 more)

### Community 5 - "mihomo-example.yml"
Cohesion: 0.10
Nodes (20): allow-lan, bind-address, external-controller, external-ui, external-ui-url, find-process-mode, geo-auto-update, geo-update-interval (+12 more)

### Community 8 - "lint.yml"
Cohesion: 0.13
Nodes (14): runs-on, steps, jobs, check, name, permissions, contents, branches (+6 more)

### Community 9 - "dns"
Cohesion: 0.14
Nodes (14): dns, cache-algorithm, default-nameserver, enable, enhanced-mode, fake-ip-filter, fake-ip-filter-mode, fake-ip-range (+6 more)

### Community 12 - "ads"
Cohesion: 0.15
Nodes (13): behavior, format, interval, path, type, url, behavior, format (+5 more)

### Community 13 - "release_tag"
Cohesion: 0.17
Nodes (12): release_tag, branches, tags, default, description, required, type, True (+4 more)

### Community 14 - "sniffer"
Cohesion: 0.18
Nodes (11): override-destination, ports, ports, HTTP, QUIC, TLS, sniffer, enable (+3 more)

### Community 15 - "router-watchdog"
Cohesion: 0.05
Nodes (34): Context entry point, graphify, Language and scope, Repository agent instructions, Security and external actions, Router watchdog context, Approved Mihomo failover design, Benchmark isolation (+26 more)

### Community 20 - "listeners"
Cohesion: 0.29
Nodes (7): listeners, listen, name, port, proxy, type, users

### Community 21 - "proxy-groups"
Cohesion: 0.29
Nodes (7): proxy-groups, hidden, icon, name, proxies, type, use

### Community 22 - "geox-url"
Cohesion: 0.67
Nodes (3): geox-url, geoip, geosite

### Community 23 - "profile"
Cohesion: 0.67
Nodes (3): profile, store-fake-ip, store-selected

### Community 24 - "replace_text_file"
Cohesion: 0.53
Nodes (5): is_watchdog_cron_entry(), remove_legacy_watchdog_entries(), replace_text_file(), sync_cron(), update_managed_crontab()

### Community 25 - "call_watchdog"
Cohesion: 0.09
Nodes (21): Configurable speed service and config MCP tools, Existing defaults, Implemented behavior and validation limits, Installed paths and cron, Local verification, Project map, Repository layout, restart_cron() (+13 more)

### Community 29 - "План реализации MCP для Mihomo"
Cohesion: 0.40
Nodes (4): Начальная синхронизация BENCHMARK, План реализации MCP для Mihomo, Расширение: сервис замеров и конфигурация, Результат

## Knowledge Gaps
- **12 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Project map` connect `call_watchdog` to `router_watchdog.py`, `router-watchdog`?**
  _High betweenness centrality (0.064) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `choose_and_apply()` (e.g. with `Runtime boundaries` and `.provider()`) actually correct?**
  _`choose_and_apply()` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Should `router_watchdog.py` be split into smaller, more focused modules?**
  _Cohesion score 0.09336016096579478 - nodes in this community are weakly interconnected._
- **Why does `Controller` connect `Controller` to `test_cli.py`, `TestManualSpeed`?**
  _High betweenness centrality (0.059) - this node is a cross-community bridge._
- **Should `Controller` be split into smaller, more focused modules?**
  _Cohesion score 0.07676767676767676 - nodes in this community are weakly interconnected._
- **Why does `TestProviderResolution` connect `TestProviderResolution` to `test_cli.py`?**
  _High betweenness centrality (0.049) - this node is a cross-community bridge._
- **Should `with` be split into smaller, more focused modules?**
  _Cohesion score 0.06620209059233449 - nodes in this community are weakly interconnected._