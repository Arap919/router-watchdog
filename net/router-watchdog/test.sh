#!/bin/sh

case "$1" in
  router-watchdog)
    /opt/bin/router-watchdog --help >/dev/null 2>&1 || true
    test -x /opt/bin/router-watchdog
    test -f /opt/etc/router-watchdog.json
    test -f /opt/libexec/router-watchdog/router_watchdog.py
    ;;
  *)
    echo "Unknown package: $1" >&2
    exit 1
    ;;
esac
