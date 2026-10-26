# Graph Report - router-watchdog  (2026-10-26)

## Corpus Check
- 21 files · ~15,681 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 4 file(s) not represented in the graph (top: (none) 4)

## Summary
- 416 nodes · 659 edges · 20 communities (12 shown, 8 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 42 edges (avg confidence: 0.89)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `b97e9a05`
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
- test.sh

## God Nodes (most connected - your core abstractions)
1. `Controller` - 27 edges
2. `Mihomo` - 26 edges
3. `TestFailover` - 26 edges
4. `choose_and_apply()` - 18 edges
5. `log()` - 17 edges
6. `Runtime boundaries` - 15 edges
7. `dns` - 14 edges
8. `TestCronSchedule` - 14 edges
9. `TestConfigMerge` - 13 edges
10. `measure_speed()` - 12 edges

## Surprising Connections (you probably didn't know these)
- `1. Конфигурация и изоляция замеров` --references--> `measure_speed()`  [INFERRED]
  docs/implementation-plan.md → net/router-watchdog/files/opt/libexec/router-watchdog/router_watchdog.py
- `Runtime boundaries` --references--> `Mihomo`  [INFERRED]
  docs/project-map.md → net/router-watchdog/files/opt/libexec/router-watchdog/router_watchdog.py
- `Runtime boundaries` --references--> `latest_history_delay()`  [INFERRED]
  docs/project-map.md → net/router-watchdog/files/opt/libexec/router-watchdog/router_watchdog.py
- `Runtime boundaries` --references--> `providers_from_target_group()`  [INFERRED]
  docs/project-map.md → net/router-watchdog/files/opt/libexec/router-watchdog/router_watchdog.py
- `Runtime boundaries` --references--> `check_group_nodes()`  [INFERRED]
  docs/project-map.md → net/router-watchdog/files/opt/libexec/router-watchdog/router_watchdog.py

## Import Cycles
- None detected.

## Communities (20 total, 8 thin omitted)

### Community 0 - "router_watchdog.py"
Cohesion: 0.09
Nodes (40): Runtime boundaries, benchmark_candidates(), check_candidates(), check_current(), check_group_nodes(), choose_and_apply(), choose_winner(), cleanup_days() (+32 more)

### Community 1 - "with"
Cohesion: 0.07
Nodes (41): if, permissions, runs-on, steps, GH_TOKEN, RELEASE_TAG, name, url (+33 more)

### Community 3 - "mihomo-example.yml"
Cohesion: 0.05
Nodes (40): allow-lan, bind-address, external-controller, external-ui, external-ui-url, find-process-mode, geo-auto-update, geo-update-interval (+32 more)

### Community 4 - "Approved Mihomo failover design"
Cohesion: 0.06
Nodes (29): Context entry point, graphify, Language and scope, Repository agent instructions, Security and external actions, Router watchdog context, Approved Mihomo failover design, Benchmark isolation (+21 more)

### Community 5 - "BlancVPN"
Cohesion: 0.12
Nodes (22): header, health-check, interval, override, type, url, User-Agent, x-hwid (+14 more)

### Community 7 - "test_cli.py"
Cohesion: 0.20
Nodes (4): atomic_write(), install(), merge(), TestRouterWatchdogCli

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

### Community 16 - "router-watchdog"
Cohesion: 0.20
Nodes (10): Cron и пути, router-watchdog, Алгоритм, Команды, лог и блокировка, Конфигурация watchdog, Лицензия, Настройка Mihomo, Разработка и сборка (+2 more)

## Knowledge Gaps
- **8 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Runtime boundaries` connect `router_watchdog.py` to `Approved Mihomo failover design`?**
  _High betweenness centrality (0.071) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `choose_and_apply()` (e.g. with `Runtime boundaries` and `.provider()`) actually correct?**
  _`choose_and_apply()` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Should `router_watchdog.py` be split into smaller, more focused modules?**
  _Cohesion score 0.08724569640062597 - nodes in this community are weakly interconnected._
- **Why does `Project map` connect `Approved Mihomo failover design` to `router_watchdog.py`?**
  _High betweenness centrality (0.071) - this node is a cross-community bridge._
- **Should `with` be split into smaller, more focused modules?**
  _Cohesion score 0.06620209059233449 - nodes in this community are weakly interconnected._
- **Why does `TestProviderResolution` connect `TestProviderResolution` to `test_cli.py`?**
  _High betweenness centrality (0.053) - this node is a cross-community bridge._
- **Should `Controller` be split into smaller, more focused modules?**
  _Cohesion score 0.08478513356562137 - nodes in this community are weakly interconnected._