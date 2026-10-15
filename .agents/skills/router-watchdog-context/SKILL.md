---
name: router-watchdog-context
description: Use when working in the router-watchdog repository on Mihomo failover, selector isolation, provider healthchecks, cron, Entware packaging, configuration or tests.
---

# Router watchdog context

Resolve paths from the repository root, three directories above this skill folder.

Read `docs/project-map.md` to locate runtime, defaults, tests, packaging and CI. Read `docs/failover-design.md` when changing failover, benchmark routing or cleanup. Read `docs/implementation-plan.md` for approved task progress; its pending items are not implemented capabilities. Confirm behavior in source and tests.

| Task | Inspect |
| --- | --- |
| Runtime or selector behavior | `net/router-watchdog/files/opt/libexec/router-watchdog/router_watchdog.py`, `tests/test_cli.py` |
| Configuration fields | Runtime, `net/router-watchdog/files/opt/etc/router-watchdog.json`, `.github/workflows/lint.yml`, `README.md` |
| Packaging or installed paths | `net/router-watchdog/Makefile`, shell entry point and `cron.1min` hook under `files/opt/` |
| Mihomo groups/listener/order | `myMihomoCongif.yml`, approved design; preserve rule/group references |

Keep these boundaries visible: provider-owned fresh checks differ from cached history; zero latest delay is failed history; provider membership is broader than target-group membership. Approved benchmarks use a separate hidden selector, with emergency restoration before measurements. The map explicitly identifies differences from existing code.

Run local checks from the root: `python3 -m unittest discover -s tests -v`, Python compilation of the runtime, shell syntax checks and `git diff --check`. Mock controller and cron interactions. `net/router-watchdog/test.sh` requires an installed package and is not the local suite.

Follow root `AGENTS.md` for language, scope and permissions. Keep personal subscription URLs private. Documentation or local testing does not authorize live controller calls, cron edits, router deployment or publishing.
