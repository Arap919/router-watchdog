# Graph Report - router-watchdog  (2026-10-26)

## Corpus Check
- 31 files · ~22,118 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 4 file(s) not represented in the graph (top: (none) 4)

## Summary
- 567 nodes · 962 edges · 34 communities (20 shown, 14 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 71 edges (avg confidence: 0.9)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `49070c84`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- router_watchdog.py
- with
- Controller
- mihomo-example.yml
- Approved Mihomo failover design
- BlancVPN
- TestProviderResolution
- test_cli.py
- lint.yml
- dns
- TestCronSchedule
- TestConfigMerge
- ads
- release_tag
- sniffer
- TestCleanup
- router-watchdog
- bin/router-watchdog
- cron.1min/router-watchdog
- test.sh
- listeners
- proxy-groups
- geox-url
- profile
- TestReleaseSelection
- call_watchdog
- TestManualCLI
- select_release_build.py
- TestReleasePayload
- План реализации MCP для Mihomo
- test.sh
- release-1.0.10-plan.md

## God Nodes (most connected - your core abstractions)
1. `Controller` - 30 edges
2. `Mihomo` - 27 edges
3. `TestFailover` - 26 edges
4. `choose_and_apply()` - 18 edges
5. `manual_speed()` - 18 edges
6. `TestManualSpeed` - 18 edges
7. `log()` - 17 edges
8. `measure_speed()` - 15 edges
9. `main()` - 15 edges
10. `dns` - 14 edges

## Surprising Connections (you probably didn't know these)
- `1. Конфигурация и изоляция замеров` --references--> `measure_speed()`  [INFERRED]
  docs/implementation-plan.md → net/router-watchdog/files/opt/libexec/router-watchdog/router_watchdog.py
- `Поведение` --references--> `choose_winner()`  [INFERRED]
  tools/README.md → net/router-watchdog/files/opt/libexec/router-watchdog/router_watchdog.py
- `Configurable speed service and config MCP tools` --references--> `update_config()`  [INFERRED]
  docs/project-map.md → net/router-watchdog/files/opt/libexec/router-watchdog/router_watchdog.py
- `Manual speed operations and local MCP` --references--> `measure_selected_node()`  [INFERRED]
  docs/project-map.md → tools/xkeen_mcp.py
- `Manual speed operations and local MCP` --references--> `find_faster_node()`  [INFERRED]
  docs/project-map.md → tools/xkeen_mcp.py

## Import Cycles
- None detected.

## Communities (34 total, 14 thin omitted)

### Community 0 - "router_watchdog.py"
Cohesion: 0.09
Nodes (46): Configurable speed service and config MCP tools, Manual speed operations and local MCP, Runtime boundaries, benchmark_candidates(), check_candidates(), check_current(), check_group_nodes(), choose_and_apply() (+38 more)

### Community 1 - "with"
Cohesion: 0.08
Nodes (4): Controller, TestFailover, read(), TestMCPStdio

### Community 2 - "Controller"
Cohesion: 0.13
Nodes (5): atomic_write(), install(), merge(), update_config(), TestRouterWatchdogCli

### Community 3 - "mihomo-example.yml"
Cohesion: 0.05
Nodes (54): if, permissions, runs-on, steps, GH_TOKEN, GITHUB_TOKEN, RELEASE_TAG, name (+46 more)

### Community 4 - "Approved Mihomo failover design"
Cohesion: 0.12
Nodes (22): header, health-check, interval, override, type, url, User-Agent, x-hwid (+14 more)

### Community 5 - "BlancVPN"
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

### Community 15 - "TestCleanup"
Cohesion: 0.05
Nodes (42): Context entry point, graphify, Language and scope, Repository agent instructions, Security and external actions, Router watchdog context, Approved Mihomo failover design, Benchmark isolation (+34 more)

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

### Community 24 - "TestReleaseSelection"
Cohesion: 0.35
Nodes (5): artifacts(), run_record(), TestReleaseSelection, get(), get()

### Community 25 - "call_watchdog"
Cohesion: 0.17
Nodes (13): MCP для замеров Mihomo, Изменение конфигурации через MCP, Поведение, Подготовка, Подключение, Проверки без роутера, Сервис проверки скорости, build_server() (+5 more)

### Community 27 - "select_release_build.py"
Cohesion: 0.31
Nodes (4): main(), get(), pages(), select_build()

### Community 29 - "План реализации MCP для Mihomo"
Cohesion: 0.40
Nodes (4): Начальная синхронизация BENCHMARK, План реализации MCP для Mihomo, Расширение: сервис замеров и конфигурация, Результат

## Knowledge Gaps
- **14 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Project map` connect `TestCleanup` to `router_watchdog.py`?**
  _High betweenness centrality (0.057) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `choose_and_apply()` (e.g. with `Runtime boundaries` and `.provider()`) actually correct?**
  _`choose_and_apply()` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Should `router_watchdog.py` be split into smaller, more focused modules?**
  _Cohesion score 0.08736842105263158 - nodes in this community are weakly interconnected._
- **Why does `Controller` connect `with` to `Controller`, `test_cli.py`?**
  _High betweenness centrality (0.054) - this node is a cross-community bridge._
- **Should `with` be split into smaller, more focused modules?**
  _Cohesion score 0.07676767676767676 - nodes in this community are weakly interconnected._
- **Why does `TestProviderResolution` connect `TestProviderResolution` to `Controller`?**
  _High betweenness centrality (0.045) - this node is a cross-community bridge._
- **Should `Controller` be split into smaller, more focused modules?**
  _Cohesion score 0.1337126600284495 - nodes in this community are weakly interconnected._