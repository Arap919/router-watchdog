#!/bin/sh
# Install or upgrade the managed Entware package; never replace its payload manually.
set -eu
PATH="/opt/bin:/opt/sbin:$PATH"
export PATH

if [ "$#" -ne 0 ]; then
    echo "Usage: sh install.sh" >&2
    exit 2
fi
opkg_bin=$(command -v opkg) || { echo "Entware opkg is required" >&2; exit 1; }
config=${ROUTER_WATCHDOG_OPKG_CONF:-/opt/etc/opkg.conf}
[ -f "$config" ] || { echo "Entware opkg.conf was not found" >&2; exit 1; }

# Bootstrap HTTPS support from the existing architecture feed. The final update
# below must succeed; an old custom HTTPS feed can fail this bootstrap pass.
"$opkg_bin" update || echo "Bootstrap index refresh was incomplete; trying available indexes" >&2
"$opkg_bin" install wget-ssl ca-bundle

umask 077
temporary=$(mktemp "${config}.router-watchdog.XXXXXX")
trap 'rm -f "$temporary"' 0
trap 'exit 1' 1 2 3 15
cp -p "$config" "$temporary"
awk '!(($1 == "src/gz" || $1 == "src") && $2 == "router-watchdog")' "$config" > "$temporary"
printf '%s\n' 'src/gz router-watchdog https://arap919.github.io/router-watchdog/all' >> "$temporary"
if ! cmp -s "$temporary" "$config"; then
    mv "$temporary" "$config"
fi
"$opkg_bin" update
if "$opkg_bin" status router-watchdog | grep -q 'Status:.* installed'; then
    "$opkg_bin" upgrade router-watchdog
else
    "$opkg_bin" install router-watchdog
fi
