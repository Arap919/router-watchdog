# Graph Report - router-watchdog  (2026-10-27)

## Corpus Check
- 39 files · ~29,246 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 4 file(s) not represented in the graph (top: (none) 4)

## Summary
- 702 nodes · 1250 edges · 49 communities (31 shown, 18 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 81 edges (avg confidence: 0.9)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `584773b7`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- router_watchdog.py
- with
- Controller
- steps
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
- Approved Mihomo failover design
- README.md
- Project map
- TestPackageBuilder
- Repository agent instructions
- План реализации failover
- Быстрая упаковка и обновление watchdog
- install.sh
- update_service.py
- republish-feed
- contents
- publish-feed
- with
- release

## God Nodes (most connected - your core abstractions)
1. `Controller` - 30 edges
2. `Mihomo` - 28 edges
3. `TestFailover` - 26 edges
4. `manual_speed()` - 20 edges
5. `choose_and_apply()` - 19 edges
6. `TestManualSpeed` - 19 edges
7. `log()` - 18 edges
8. `main()` - 16 edges
9. `TestMCPBridge` - 16 edges
10. `measure_speed()` - 15 edges

## Surprising Connections (you probably didn't know these)
- `1. Конфигурация и изоляция замеров` --references--> `measure_speed()`  [INFERRED]
  docs/implementation-plan.md → net/router-watchdog/files/opt/libexec/router-watchdog/router_watchdog.py
- `Поведение` --references--> `choose_winner()`  [INFERRED]
  tools/README.md → net/router-watchdog/files/opt/libexec/router-watchdog/router_watchdog.py
- `Ограничения` --references--> `choose_and_apply()`  [INFERRED]
  docs/superpowers/plans/2026-10-27-mcp-node-choice.md → net/router-watchdog/files/opt/libexec/router-watchdog/router_watchdog.py
- `Configurable speed service and config MCP tools` --references--> `cron_entries()`  [INFERRED]
  docs/project-map.md → net/router-watchdog/files/opt/libexec/router-watchdog/router_watchdog.py
- `Configurable speed service and config MCP tools` --references--> `download_url()`  [INFERRED]
  docs/project-map.md → net/router-watchdog/files/opt/libexec/router-watchdog/router_watchdog.py

## Import Cycles
- None detected.

## Communities (49 total, 18 thin omitted)

### Community 0 - "router_watchdog.py"
Cohesion: 0.08
Nodes (48): Manual speed operations and local MCP, Runtime boundaries, benchmark_candidates(), check_candidates(), check_current(), check_group_nodes(), choose_and_apply(), choose_winner() (+40 more)

### Community 1 - "with"
Cohesion: 0.08
Nodes (4): Controller, TestFailover, read(), TestMCPStdio

### Community 2 - "Controller"
Cohesion: 0.09
Nodes (18): atomic_write(), install(), merge(), download(), update_config(), archive(), build_feed(), compressed() (+10 more)

### Community 3 - "steps"
Cohesion: 0.27
Nodes (13): steps, GH_TOKEN, GITHUB_TOKEN, RELEASE_TAG, SOURCE_DATE_EPOCH, steps, steps, steps (+5 more)

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
Nodes (31): Configurable speed service and config MCP tools, Задача 1: безопасное отдельное переключение в runtime, Задача 2: разделить MCP-инструменты и обновить документацию, Ограничения, План разделения замера и выбора ноды MCP, Проверки рисков, Codex, MCP для замеров Mihomo (+23 more)

### Community 29 - "План реализации MCP для Mihomo"
Cohesion: 0.40
Nodes (4): Начальная синхронизация BENCHMARK, План реализации MCP для Mihomo, Расширение: сервис замеров и конфигурация, Результат

### Community 35 - "Approved Mihomo failover design"
Cohesion: 0.20
Nodes (10): Approved Mihomo failover design, Benchmark isolation, Implementation rulings and evidence, Log cleanup, Normal run, Primary references, Scope and invariants, Subscription recovery (+2 more)

### Community 37 - "Project map"
Cohesion: 0.22
Nodes (9): Existing defaults, Fast script package and update integration (1.0.11), Implemented behavior and validation limits, Installed paths and cron, Local verification, MCP quick measurement profile, Project map, Release artifact promotion (1.0.10) (+1 more)

### Community 39 - "Repository agent instructions"
Cohesion: 0.29
Nodes (6): Context entry point, graphify, Language and scope, Repository agent instructions, Security and external actions, Test execution approval

### Community 40 - "План реализации failover"
Cohesion: 0.33
Nodes (6): 1. Конфигурация и изоляция замеров, 2. Аварийное восстановление и выбор, 3. Логи, блокировка и cron, 4. Документация и итоговая проверка, План реализации failover, Результат проверки

### Community 41 - "Быстрая упаковка и обновление watchdog"
Cohesion: 0.29
Nodes (6): 1. Быстрый пакет и feed, 2. Установка и CLI обновлений, 3. Проверка и интеграция, Быстрая упаковка и обновление watchdog, Подготовка публикации, Результат локальной проверки

### Community 43 - "update_service.py"
Cohesion: 0.14
Nodes (18): main(), get(), pages(), select_build(), check_update(), download_package(), fetch_manifest(), install_update() (+10 more)

### Community 44 - "republish-feed"
Cohesion: 0.22
Nodes (8): if, runs-on, jobs, build, republish-feed, name, if, runs-on

### Community 45 - "contents"
Cohesion: 0.31
Nodes (9): permissions, permissions, actions, contents, id-token, pages, permissions, permissions (+1 more)

### Community 46 - "publish-feed"
Cohesion: 0.29
Nodes (8): name, url, publish-feed, environment, if, needs, runs-on, environment

### Community 47 - "with"
Cohesion: 0.25
Nodes (8): with, artifact-ids, files, github-token, if-no-files-found, name, path, run-id

### Community 48 - "release"
Cohesion: 0.33
Nodes (6): release, feed_artifact_id, source_run_id, if, outputs, runs-on

## Knowledge Gaps
- **18 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Project map` connect `Project map` to `router_watchdog.py`, `call_watchdog`, `README.md`?**
  _High betweenness centrality (0.065) - this node is a cross-community bridge._
- **Should `router_watchdog.py` be split into smaller, more focused modules?**
  _Cohesion score 0.08438818565400844 - nodes in this community are weakly interconnected._
- **Why does `Configurable speed service and config MCP tools` connect `call_watchdog` to `router_watchdog.py`, `Controller`, `Project map`?**
  _High betweenness centrality (0.052) - this node is a cross-community bridge._
- **Should `with` be split into smaller, more focused modules?**
  _Cohesion score 0.07536231884057971 - nodes in this community are weakly interconnected._
- **Why does `update_config()` connect `Controller` to `router_watchdog.py`, `call_watchdog`?**
  _High betweenness centrality (0.049) - this node is a cross-community bridge._
- **Should `Controller` be split into smaller, more focused modules?**
  _Cohesion score 0.09307244843997885 - nodes in this community are weakly interconnected._
- **Should `Approved Mihomo failover design` be split into smaller, more focused modules?**
  _Cohesion score 0.11688311688311688 - nodes in this community are weakly interconnected._