# Graph Report - router-watchdog  (2026-10-27)

## Corpus Check
- 39 files · ~30,086 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 4 file(s) not represented in the graph (top: (none) 4)

## Summary
- 711 nodes · 1262 edges · 44 communities (26 shown, 18 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 80 edges (avg confidence: 0.9)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `7154a9fe`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- router_watchdog.py
- with
- Controller
- with
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
- router-watchdog
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
- TestMCPChoice
- TestReleasePayload
- План реализации MCP для Mihomo
- test.sh
- release-1.0.10-plan.md
- TestUpdateService
- update_service.py
- Approved Mihomo failover design
- Project map
- TestPackageBuilder
- README.md
- Repository agent instructions
- Быстрая упаковка и обновление watchdog
- install.sh
- План реализации failover

## God Nodes (most connected - your core abstractions)
1. `Controller` - 30 edges
2. `Mihomo` - 28 edges
3. `TestFailover` - 26 edges
4. `manual_speed()` - 20 edges
5. `choose_and_apply()` - 19 edges
6. `TestManualSpeed` - 19 edges
7. `log()` - 18 edges
8. `TestMCPBridge` - 18 edges
9. `main()` - 16 edges
10. `measure_speed()` - 15 edges

## Surprising Connections (you probably didn't know these)
- `1. Конфигурация и изоляция замеров` --references--> `measure_speed()`  [INFERRED]
  docs/implementation-plan.md → net/router-watchdog/files/opt/libexec/router-watchdog/router_watchdog.py
- `Поведение` --references--> `choose_winner()`  [INFERRED]
  tools/README.md → net/router-watchdog/files/opt/libexec/router-watchdog/router_watchdog.py
- `Ограничения` --references--> `choose_and_apply()`  [INFERRED]
  docs/superpowers/plans/2026-10-27-mcp-node-choice.md → net/router-watchdog/files/opt/libexec/router-watchdog/router_watchdog.py
- `Manual speed operations and local MCP` --references--> `measure_selected_node()`  [INFERRED]
  docs/project-map.md → tools/xkeen_mcp.py
- `Manual speed operations and local MCP` --references--> `find_faster_node()`  [INFERRED]
  docs/project-map.md → tools/xkeen_mcp.py

## Import Cycles
- None detected.

## Communities (44 total, 18 thin omitted)

### Community 0 - "router_watchdog.py"
Cohesion: 0.08
Nodes (51): Configurable speed service and config MCP tools, Manual speed operations and local MCP, Runtime boundaries, benchmark_candidates(), check_candidates(), check_current(), check_group_nodes(), choose_and_apply() (+43 more)

### Community 1 - "with"
Cohesion: 0.08
Nodes (4): Controller, TestFailover, read(), TestMCPStdio

### Community 2 - "Controller"
Cohesion: 0.10
Nodes (17): atomic_write(), install(), merge(), download(), archive(), build_feed(), compressed(), main() (+9 more)

### Community 3 - "with"
Cohesion: 0.06
Nodes (52): if, permissions, runs-on, steps, GH_TOKEN, GITHUB_TOKEN, RELEASE_TAG, SOURCE_DATE_EPOCH (+44 more)

### Community 4 - "Approved Mihomo failover design"
Cohesion: 0.12
Nodes (22): header, health-check, interval, override, type, url, User-Agent, x-hwid (+14 more)

### Community 5 - "BlancVPN"
Cohesion: 0.10
Nodes (20): allow-lan, bind-address, external-controller, external-ui, external-ui-url, find-process-mode, geo-auto-update, geo-update-interval (+12 more)

### Community 7 - "test_cli.py"
Cohesion: 0.11
Nodes (3): TestManualSpeed, measure(), TestSelectNode

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
Cohesion: 0.15
Nodes (13): Cron и пути, MCP: замер скорости и подбор узла, router-watchdog, Алгоритм, Выпуск из готовой сборки main, Команды, лог и блокировка, Конфигурация watchdog, Лицензия (+5 more)

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
Cohesion: 0.08
Nodes (31): Задача 1: безопасное отдельное переключение в runtime, Задача 2: разделить MCP-инструменты и обновить документацию, Ограничения, План разделения замера и выбора ноды MCP, Проверки рисков, Codex, MCP для замеров Mihomo, `Permission denied (publickey,password)` (+23 more)

### Community 29 - "План реализации MCP для Mihomo"
Cohesion: 0.40
Nodes (4): Начальная синхронизация BENCHMARK, План реализации MCP для Mihomo, Расширение: сервис замеров и конфигурация, Результат

### Community 35 - "update_service.py"
Cohesion: 0.14
Nodes (18): main(), get(), pages(), select_build(), check_update(), download_package(), fetch_manifest(), install_update() (+10 more)

### Community 36 - "Approved Mihomo failover design"
Cohesion: 0.20
Nodes (10): Approved Mihomo failover design, Benchmark isolation, Implementation rulings and evidence, Log cleanup, Normal run, Primary references, Scope and invariants, Subscription recovery (+2 more)

### Community 37 - "Project map"
Cohesion: 0.22
Nodes (9): Existing defaults, Fast script package and update integration (1.0.11), Implemented behavior and validation limits, Installed paths and cron, Local verification, MCP quick measurement profile, Project map, Release artifact promotion (1.0.10) (+1 more)

### Community 40 - "Repository agent instructions"
Cohesion: 0.29
Nodes (6): Context entry point, graphify, Language and scope, Repository agent instructions, Security and external actions, Test execution approval

### Community 41 - "Быстрая упаковка и обновление watchdog"
Cohesion: 0.29
Nodes (6): 1. Быстрый пакет и feed, 2. Установка и CLI обновлений, 3. Проверка и интеграция, Быстрая упаковка и обновление watchdog, Подготовка публикации, Результат локальной проверки

### Community 43 - "План реализации failover"
Cohesion: 0.33
Nodes (6): 1. Конфигурация и изоляция замеров, 2. Аварийное восстановление и выбор, 3. Логи, блокировка и cron, 4. Документация и итоговая проверка, План реализации failover, Результат проверки

## Knowledge Gaps
- **18 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Project map` connect `Project map` to `router_watchdog.py`, `README.md`?**
  _High betweenness centrality (0.065) - this node is a cross-community bridge._
- **Should `router_watchdog.py` be split into smaller, more focused modules?**
  _Cohesion score 0.0783132530120482 - nodes in this community are weakly interconnected._
- **Why does `Configurable speed service and config MCP tools` connect `router_watchdog.py` to `call_watchdog`, `Project map`?**
  _High betweenness centrality (0.053) - this node is a cross-community bridge._
- **Should `with` be split into smaller, more focused modules?**
  _Cohesion score 0.07536231884057971 - nodes in this community are weakly interconnected._
- **Why does `Controller` connect `with` to `Controller`, `test_cli.py`?**
  _High betweenness centrality (0.048) - this node is a cross-community bridge._
- **Should `Controller` be split into smaller, more focused modules?**
  _Cohesion score 0.09672131147540984 - nodes in this community are weakly interconnected._
- **Should `with` be split into smaller, more focused modules?**
  _Cohesion score 0.055152394775036286 - nodes in this community are weakly interconnected._