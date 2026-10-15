# Approved Mihomo failover design

Approved by the user on 2026-10-15. Status: implemented and locally tested. This document records the approved behavior; deployment and native Mihomo validation have not been performed.

## Scope and invariants

- Refactor `myMihomoCongif.yml` into readable sections without changing routing policy or existing group names used by rules.
- Make `ПОДПИСКА PAPER` the first visible selector, including explicit built-in `GLOBAL` ordering where needed by dashboards.
- Preserve existing CLI actions, configuration-file checks, installed paths, cron paths and scheduling behavior.
- Use one nonblocking file lock to prevent overlapping normal watchdog runs, whether manual or scheduled.
- Log execution stages, decisions, healthcheck outcomes, refresh/measurement failures, fallback selection and final status. Do not log credentials or subscription URLs.
- Keep current-node and candidate healthchecks fresh and provider-owned.
- Never use the production selector for intermediate throughput tests.
- Exclude nodes whose names contain `Россия` or `Украина` from automatic fallback and winner selection.

The exclusion concerns selection: the healthy-current-node fast exit remains the first normal branch, as requested. A stale history failure must not prevent a fresh emergency healthcheck.

## Benchmark isolation

Use a hidden `BENCHMARK` selector backed by `Paper` and `Paper-запасной-ключ`. Add a dedicated HTTP listener:

```yaml
listeners:
  - name: benchmark-in
    type: http
    port: 17890
    listen: 127.0.0.1
    proxy: BENCHMARK
    users: []

proxy-groups:
  # Keep the existing subscription selector first.
  - name: BENCHMARK
    type: select
    use:
      - Paper
      - Paper-запасной-ключ
    hidden: true
```

This is a fragment to merge into existing sections, not a replacement configuration. The approved listener binds to loopback because the watchdog runs locally. Set watchdog `benchmark_group` to `BENCHMARK` and `benchmark_proxy` to `http://127.0.0.1:17890`; the production `target_group` remains separate. Reject identical target/benchmark group configuration. A candidate must belong to the production group and be selectable in the benchmark group before measuring it.

The main selector may change only for emergency restoration or final winner application. An API failure cannot guarantee that a switch took effect; record the failure instead of reporting restored service. Benchmark errors must not intentionally leave the main group on an unverified candidate.

## Normal run

1. Preserve configuration existence/loading checks; acquire the existing normal-run lock and validate relevant settings before selection side effects.
2. Read the current concrete node from `target_group`, resolve its provider and perform a fresh provider-owned healthcheck.
3. If successful, log the result and exit without switching nodes, refreshing subscriptions or measuring speed.
4. If unsuccessful, begin emergency restoration before throughput measurements.
5. Read only concrete provider-backed members of `target_group`; apply country-name exclusions. Nodes elsewhere in the same provider are outside the candidate set.
6. Fresh-check eligible nodes until the first working node is found and immediately select it in `target_group`. Do not require positive historical delay for this restoration step. If none is working, proceed to subscription recovery; do not start benchmarks without a working candidate.
7. Rank eligible candidates by their last positive historical `history.delay`. Do not search earlier history entries for a replacement positive delay.
8. Take `top_n`, perform fresh healthchecks, and speed-test the responding candidates through `BENCHMARK`. Preserve existing stream/round measurement controls.
9. Choose the winner by the latency/speed policy below and apply it to `target_group` only after all candidate measurements finish.

## Subscription recovery

Trigger recovery if history yields no usable candidates, all shortlisted fresh healthchecks fail, all speed tests fail, or no emergency fallback can be confirmed.

1. Update all proxy providers, then perform fresh healthchecks for eligible production-group nodes and rebuild the current candidate data. Provider updates must invalidate cached details, and membership must be re-read because subscription contents can change.
2. If service is still unconfirmed, immediately apply the first freshly confirmed working eligible node before benchmarking.
3. Rank by the latest delay after the fresh checks, take `top_n`, and perform the same candidate checks, isolated speed measurements and winner selection.
4. If no eligible nodes work after refresh and fresh checks, exit with an error and a clear log entry.
5. If all speed tests fail after recovery, report an error and preserve an already selected emergency working node. Do not retry refresh indefinitely.

The normal path avoids unconditional subscription updates. Recovery is one bounded pass; existing per-provider refresh retries may remain. A provider that fails to update must be logged; partial provider-update failure is not proof that every node is unavailable.

The original request says to update **all** proxy providers during recovery, while normal candidate discovery and all selections remain restricted to `target_group`. This distinction must remain explicit in implementation and tests.

## Winner policy

Use only candidates with a successful fresh healthcheck and successful positive throughput result. Let `minimum_delay` be the lowest fresh delay among those measured candidates. Among candidates with `delay <= minimum_delay + 50 ms`, choose the greatest throughput. Equal speeds prefer lower delay; exact ties should have stable ordering.

Examples:

| Candidate results | Winner |
| --- | --- |
| A: 30 ms / 80 Mbps; B: 80 ms / 120 Mbps | B: 50 ms difference is included. |
| A: 30 ms / 80 Mbps; B: 81 ms / 120 Mbps | A: B exceeds the latency window. |
| A: 30 ms / failed speed; B: 90 ms / 50 Mbps | B: A has no successful speed result. |

The former `close_result_percent` winner policy must no longer determine selection. Legacy `fresh_top_n` and `close_result_percent` fields are accepted but ignored with a log message; they are removed from package defaults. All responding top_n candidates are measured.

## Log cleanup

Add `log_cleanup_days` to watchdog configuration, default `3`. Retain the log path and the existing `--clear-log` action. Cron runs a daily due check, using persisted last-cleanup time, so cleanup occurs every configured number of days across month/year boundaries. A day-of-month expression such as `*/3` alone does not implement elapsed three-day intervals.

Preserve explicit manual log truncation. State is stored at `/opt/share/router-watchdog.log.cleanup` (or next to an overridden log path). First due check initializes the timestamp without truncation. Manual `--clear-log` truncates immediately and resets the timestamp; cron uses `--clear-log --if-due`. Invalid state returns an error without truncation, and failed truncation does not update state. All actions except help hold the existing common lock. Configuration permits integer intervals from 1 through 3650 days. Do not add a second periodic cleanup mechanism outside the existing managed cron setup. The daily check uses elapsed seconds (`days * 86400`); a skipped cron run delays cleanup until the next successful check.

## Validation and delivery

Use mocked runtime tests to cover healthy-current exit, current failure, stale/zero history, group-only membership, country exclusions, immediate restoration before measurement, failed shortlist checks, all speed tests failing, refresh recovery, partial refresh failures, all nodes unavailable after recovery, winner boundary at 50/51 ms, and production-group isolation.

Check configuration validation, existing actions, lock contention/release, cron idempotence, unrelated-job preservation and cleanup interval boundaries. Parse the refactored YAML, inspect references/order and, if a Mihomo binary is available, validate it with the native config checker without launching traffic. Update CI key validation with configuration changes.

Keep local checks distinct from production verification. Do not deploy, push, publish, reload a router or contact a live controller as part of documentation or local tests.

## Primary references

- [Listener common fields](https://wiki.metacubex.one/en/config/inbound/listeners/): `proxy` routes directly through a named outbound/group.
- [HTTP listener](https://wiki.metacubex.one/en/config/inbound/listeners/http/): `users: []` skips listener authentication.
- [Built-in GLOBAL](https://wiki.metacubex.one/config/proxy-groups/built-in/): some dashboards use its group ordering.

## Implementation rulings and evidence

- Ruling: use the existing common lock for cron management and log cleanup as well as selection, and add a timestamp sidecar next to the existing log — serializes file mutations without changing installed paths — a busy daily cleanup retries at the next daily cron run.
- Ruling: preserve legacy tuning keys as ignored inputs — existing conffiles remain usable while the approved ranking takes effect — old tuning values no longer affect results.
- Ruling: keep the case-sensitive `Global` routing selector and add a separate built-in `GLOBAL` display selector — existing rules retain their target names — its previously undefined `Proxy` choice is replaced by the existing subscription/DIRECT list.
- Ruling: retain the pre-existing `MATCH,Other` versus `other` mismatch — changing routing is outside the agreed refactor — this unresolved reference requires a separate correction before assuming native config validity.
- Verification: 50 standard-library unit tests passed during implementation; the independent read-only reviewer reported no actionable implementation defects. YAML parsing/alias expansion and before/after semantic comparison passed with Ruby Psych. No Mihomo binary, controller integration, router execution, IPK build or publication was used.
