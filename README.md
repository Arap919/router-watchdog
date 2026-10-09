# router-watchdog

A Mihomo failover watchdog packaged for Entware.

The watchdog monitors the currently selected proxy in a Mihomo selector group.
It always performs a fresh provider-owned healthcheck for the current node. If
the current node fails, the watchdog refreshes the providers used by the target
group, ranks candidates using the latest provider history latency, performs fresh
healthchecks, benchmarks the best candidates through the local HTTP proxy, and
selects the best result.


## Building the package

The repository contains a standard Entware/OpenWrt package definition at
`net/router-watchdog/Makefile`. Entware packages are built with the OpenWrt
SDK/build system. The GitHub Actions workflow uses the official
`Entware/docker` build environment, creates an `x64-3.2` build configuration,
and compiles the package as an architecture-independent (`all`) package.

On every push to `main` and every pull request, the workflow builds and uploads
the `.ipk` as a GitHub Actions artifact. When a tag matching `v*.*.*` is pushed,
the same package is also attached to the corresponding GitHub Release.

Create a release with:

```sh
git tag vX.Y.Z
git push origin vX.Y.Z
```

The resulting package is attached to the GitHub Release. For example, release
`v1.0.2` provides:

```sh
wget -O /tmp/router-watchdog_1.0.2-1_all.ipk \
  https://github.com/Arap919/router-watchdog/releases/download/v1.0.2/router-watchdog_1.0.2-1_all.ipk
opkg install /tmp/router-watchdog_1.0.2-1_all.ipk
```

The package itself contains only Python and shell files, so it is architecture
independent. Its runtime dependencies (`python3` and `ca-bundle`) are resolved
by `opkg` for the target Entware architecture.

## Entware feed

Tagged releases are published as a static Entware feed through GitHub Pages. The
feed contains the architecture-independent `router-watchdog` package under
`all/`, together with `Packages` and `Packages.gz` metadata.

After the first tagged release, configure an Entware device with the feed URL
shown by the GitHub Pages deployment. For a repository named
`OWNER/router-watchdog`, the expected feed URL is:

```text
https://OWNER.github.io/router-watchdog/all
```

Add the feed on the router as described in [Installation](#installation). The
feed index stores the package filename relative to this `/all` directory; the
correct package URL has one `all` path component, not `/all/all/`.

To upgrade an installed package:

```sh
opkg update
opkg upgrade router-watchdog
```

The package is declared as `Architecture: all`, so the same feed entry can be
used on supported Entware architectures. The runtime dependencies (`python3`
and `ca-bundle`) are resolved from the normal Entware feeds.

The feed is published only for version tags (`vX.Y.Z`). The workflow verifies
that the tag version matches `PKG_VERSION` in the package Makefile. Pull requests
and normal `main` pushes still build and validate the package, but do not change
the public feed.

## Requirements

- Entware with Python 3 available as `/opt/bin/python3`.
- Mihomo with its external controller API enabled.
- A selector group containing provider-backed concrete proxy nodes.
- A local HTTP proxy used for speed tests, normally Mihomo's mixed/http proxy.

The package is architecture-independent because it contains Python and shell
code only.

## Installation

### Other Entware architectures

On Entware architectures where the configured `opkg` downloader already
supports HTTPS, add the feed and install the package:

```sh
FEED='src/gz router-watchdog https://arap919.github.io/router-watchdog/all'
grep -qF "$FEED" /opt/etc/opkg.conf || echo "$FEED" >> /opt/etc/opkg.conf

opkg update
opkg install router-watchdog
```

If `opkg update` reports `wget: not an http or ftp url: https://...`, follow
the [MIPSel HTTPS downloader instructions](#keenetic-with-mipsel-entware) to
install Entware's `wget-ssl`, then retry `opkg update`.

### Keenetic with MIPSel Entware

The package is architecture-independent (`Architecture: all`), but its
dependencies must still be available for the router's Entware architecture.
For example, Keenetic systems using the `mipselsf-k3.4` feed resolve Python 3,
CA certificates, and the HTTPS downloader from that architecture's Entware
feeds.

The default Entware `wget` on this MIPSel setup may not support HTTPS. If
`opkg update` reports:

```text
wget: not an http or ftp url: https://...
```

first update the Entware feeds and install its HTTPS-capable downloader. The
Entware repository URL uses HTTP, so this step does not require HTTPS support:

```sh
opkg update
opkg install wget-ssl
```

If the router-watchdog feed was already configured, this first `opkg update`
may still report the HTTPS download error for that feed. The Entware HTTP
indexes are updated independently, so continue with `opkg install wget-ssl`.

Then add the router-watchdog feed and install the package:

```sh
FEED='src/gz router-watchdog https://arap919.github.io/router-watchdog/all'
grep -qF "$FEED" /opt/etc/opkg.conf || echo "$FEED" >> /opt/etc/opkg.conf

opkg update
opkg install router-watchdog
```

If `opkg` tries to fetch a URL containing
`/router-watchdog/all/all/router-watchdog_...ipk`, refresh the package index:
an earlier feed index had an extra `all/` prefix in `Filename`. The published
index has been corrected; after `opkg update`, the package URL should contain
only one `/all/`.

The watchdog package is architecture-independent, while `wget-ssl`, Python 3,
and other runtime dependencies are installed as matching MIPSel packages by
Entware.

### After installation

These steps apply to all supported Entware architectures. Edit the
configuration and apply its cron schedule:

```sh
vi /opt/etc/router-watchdog.json
/opt/bin/router-watchdog --sync-cron
```

Set at least `target_group` to the name of a Mihomo selector group. The full
configuration example and schedule options are documented below. Ensure
Entware's `crond` is running and reads `/opt/etc/crontabs/root`; otherwise the
scheduled watchdog runs will not execute.

Execution logs are appended to `/opt/var/log/router-watchdog.log`. The managed
crontab also truncates this file every Sunday at 06:59 router-local time. To
inspect the log:

```sh
tail -f /opt/var/log/router-watchdog.log
```

The package installs:

```text
/opt/bin/router-watchdog
/opt/libexec/router-watchdog/router_watchdog.py
/opt/etc/router-watchdog.json
/opt/etc/cron.1min/router-watchdog
```

The package also updates its managed entries in `/opt/etc/crontabs/root`.
Entware `crond` must be running with that crontab directory.

The configuration file is registered as a package conffile, so package
upgrades do not silently replace a modified `/opt/etc/router-watchdog.json`.

## Manual run

```sh
/opt/bin/router-watchdog
```

The watchdog also prevents overlapping runs with:

```text
/opt/tmp/router-watchdog.lock
```

## Configuration

Configuration file:

```text
/opt/etc/router-watchdog.json
```

Change the configuration
```text
vi /opt/etc/router-watchdog.json
```

You can also prepare the file elsewhere and copy it to the router.

Example:

```json
{
  "controller": "http://127.0.0.1:9090",
  "secret": "",
  "target_group": "MY_SELECTOR_GROUP",
  "benchmark_proxy": "http://127.0.0.1:7890",
  "top_n": 7,
  "fresh_top_n": 7,
  "healthcheck_parallelism": 6,
  "healthcheck_timeout_ms": 5000,
  "speed_connect_timeout_seconds": 5,
  "switch_wait_seconds": 0.7,
  "download_bytes": 25000000,
  "parallel_streams": 4,
  "multi_rounds": 2,
  "close_result_percent": 10,
  "schedule": {
    "windows": [
      {
        "start": "07:00",
        "end": "01:00",
        "every_minutes": 1
      },
      {
        "start": "01:00",
        "end": "07:00",
        "every_minutes": 30
      }
    ]
  }
}
```

### `schedule`

**Type:** object
**Required:** no; defaults to the package's current schedule for existing configs

`schedule.windows` contains daily time windows. Each window has `start` and
`end` in the router's local time (`HH:MM`) and an `every_minutes` interval from
1 to 1440. The start is included and the end is excluded; windows may cross
midnight. Matching start and end times mean a full-day window. Overlapping
windows are combined. An empty `windows` array disables scheduled runs.

For example, to run every five minutes from 07:00 until 01:00 and every
30 minutes overnight:

```json
"schedule": {
  "windows": [
    { "start": "07:00", "end": "01:00", "every_minutes": 5 },
    { "start": "01:00", "end": "07:00", "every_minutes": 30 }
  ]
}
```

The package writes only its marked block in `/opt/etc/crontabs/root`; other
crontab entries are left unchanged. The package's `cron.1min` hook synchronizes
the managed entries after a configuration edit, normally within one minute.
To apply the schedule immediately after editing the JSON, run:

```sh
/opt/bin/router-watchdog --sync-cron
```

### `controller`

**Type:** string  
**Required:** yes

Base URL of the Mihomo external controller API.

Example:

```json
"controller": "http://127.0.0.1:9090"
```

The value must use `http://` or `https://` and include a host.

### `secret`

**Type:** string  
**Required:** no  
**Default:** `""`

Mihomo controller API secret.

When non-empty, the watchdog sends it as a Bearer token:

```text
Authorization: Bearer <secret>
```

Leave it empty when the controller does not require authentication.

### `target_group`

**Type:** string  
**Required:** yes

Name of the Mihomo selector group that the watchdog controls.

The watchdog reads the currently selected node from this group and changes the
selection only when the current node fails the fresh healthcheck.

The package does **not** have a separate `providers` configuration field.
Provider names are discovered automatically from the concrete nodes exposed by
`target_group`. This means that adding another provider to the selector group
does not require changing the watchdog configuration.

### `benchmark_proxy`

**Type:** string  
**Required:** yes

Local HTTP proxy used for throughput measurements.

Example:

```json
"benchmark_proxy": "http://127.0.0.1:7890"
```

Each speed test downloads data through this proxy after the candidate node has
been selected in `target_group`.

### `top_n`

**Type:** integer  
**Range:** `1..50`  
**Default:** `7`

Number of candidates taken from the historical ranking before fresh
healthchecks.

Historical ranking uses exactly the latest `history.delay` entry reported by
the provider. A latest delay of `0` is treated as a failed check and is not
interpreted as zero milliseconds.

### `fresh_top_n`

**Type:** integer  
**Range:** `1..30`  
**Default:** `7`

Number of candidates that remain after the fresh healthcheck and are sent to
the speed-test stage.

This is separate from `top_n`:

```text
all provider nodes
      ↓
latest history ranking
      ↓
top_n
      ↓
fresh healthcheck
      ↓
fresh latency ranking
      ↓
fresh_top_n
      ↓
speed test
```

### `healthcheck_parallelism`

**Type:** integer  
**Range:** `1..32`  
**Default:** `6`

Maximum number of fresh provider healthchecks performed concurrently.

A higher value can reduce the total healthcheck time but creates more
simultaneous requests to the Mihomo controller and provider infrastructure.

### `healthcheck_timeout_ms`

**Type:** integer  
**Range:** `250..10000`  
**Default:** `5000`

Timeout for each provider-owned fresh healthcheck, in milliseconds.

The healthcheck uses the provider's own `testUrl` and `expectedStatus` values.
The watchdog does not replace those values with a global URL or status code.

### `speed_connect_timeout_seconds`

**Type:** integer  
**Range:** `1..30`  
**Default:** `5`

Connection timeout for each speed-test download, in seconds.

The speed test uses the configured `benchmark_proxy` and downloads from
Cloudflare Speed Test.

### `switch_wait_seconds`

**Type:** number  
**Default:** `0.7`

Delay after selecting a candidate and before starting its speed test.

This gives Mihomo time to apply the new selector state and establish the
selected route.

Example:

```json
"switch_wait_seconds": 0.7
```

### `download_bytes`

**Type:** integer  
**Range:** `1,000,000..200,000,000`  
**Default:** `25,000,000`

Amount of data requested by each speed-test stream, in bytes.

Larger values make the measurement less sensitive to short-lived fluctuations
but increase test duration and traffic consumption.

### `parallel_streams`

**Type:** integer  
**Range:** `1..8`  
**Default:** `4`

Number of simultaneous HTTP download streams used during each speed-test
round.

The total amount downloaded in one round is approximately:

```text
parallel_streams × download_bytes
```

### `multi_rounds`

**Type:** integer  
**Range:** `1..4`  
**Default:** `2`

Number of speed-test rounds performed for each finalist.

The watchdog calculates the median throughput across all rounds, which reduces
the influence of one unusually slow or fast measurement.

### `close_result_percent`

**Type:** integer  
**Range:** `0..50`  
**Default:** `10`

Defines how close two speed-test results must be before latency becomes the
tie-breaker.

The fastest candidate is selected first. Other candidates whose speed is within
this percentage of the fastest result form the close-results set. The candidate
with the lowest fresh healthcheck latency wins within that set.

Example with `10`:

```text
Fastest candidate: 100 Mbps
Close-results threshold: 90 Mbps

100 Mbps, 80 ms  -> eligible
95 Mbps, 50 ms   -> eligible and can win
85 Mbps, 30 ms   -> not eligible
```

## Provider configuration

Provider names are intentionally not stored in `router-watchdog.json`.

For each provider discovered from `target_group`, the watchdog reads:

- `testUrl` — URL used by the provider healthcheck.
- `expectedStatus` — expected HTTP status, when provided.
- `proxies` — concrete nodes belonging to the provider.
- each node's `history` — used to obtain the latest historical latency.

The current node is always checked using the provider-owned endpoint:

```text
GET /providers/proxies/{provider}/{proxyName}/healthcheck
```

The watchdog does not use stale `alive` or `history` data to decide whether the
currently selected node is healthy.

## Failover algorithm

1. Read the current node from `target_group`.
2. Resolve its provider.
3. Read the provider's current healthcheck configuration.
4. Perform a fresh healthcheck of the current node.
5. If it succeeds, stop without changing the selector.
6. If it fails, discover all providers used by `target_group`.
7. Refresh those providers.
8. Collect all concrete nodes and their latest provider history.
9. Take the best `top_n` historical candidates.
10. Fresh-check those candidates concurrently.
11. If three or more candidates fail the fresh healthcheck, fresh-check all
    concrete nodes.
12. Keep the best `fresh_top_n` candidates by fresh latency.
13. Speed-test each finalist sequentially by selecting it in `target_group` and
    downloading through `benchmark_proxy`.
14. Select the fastest candidate.
15. If several results are within `close_result_percent` of the best speed,
    select the one with the lowest fresh latency.

## Cron

The package keeps using the existing Entware/Keenetic `cron.1min` hook, but it
now uses that hook only to synchronize the configured schedule. The actual
watchdog runs are native entries in `/opt/etc/crontabs/root`, generated from
`schedule.windows`. Entware `crond` must be enabled and configured to read
`/opt/etc/crontabs`.

The hook is:

```text
/opt/etc/cron.1min/router-watchdog
```

It is expected that Entware already runs `run-parts` for this directory every
minute. Package installation creates the initial crontab entries, and later
configuration edits are synchronized by the hook. Removing the package removes
only its marked entries from the root crontab. A separate managed cron entry
clears `/opt/var/log/router-watchdog.log` every Sunday at 06:59 router-local
time.

## License

MIT
