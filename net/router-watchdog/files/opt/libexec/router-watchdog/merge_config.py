#!/usr/bin/env python3
"""Merge installed user configuration into the current package defaults."""

import json
import os
import sys
import tempfile
from pathlib import Path


def merge(defaults, user):
    result = {}
    for key, default in defaults.items():
        value = user.get(key)
        if value is None or value == '' or value == [] or value == {}:
            result[key] = default
        elif isinstance(default, dict) and isinstance(value, dict):
            result[key] = merge(default, value)
        else:
            result[key] = value
    return result


def atomic_write(path, contents):
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def install(defaults_path, config_path):
    defaults = json.loads(defaults_path.read_text(encoding='utf-8'))
    staged = config_path.with_name(config_path.name + '-upgrade')
    source = staged if staged.exists() else config_path
    original = source.read_bytes() if source.exists() else None
    user = json.loads(original) if original is not None else {}
    if not isinstance(defaults, dict) or not isinstance(user, dict):
        raise ValueError('Configuration must be a JSON object')
    contents = (json.dumps(merge(defaults, user), ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if original is not None:
        atomic_write(config_path.with_name(config_path.name + '-old'), original)
    atomic_write(config_path, contents)
    if staged.exists():
        staged.unlink()


if __name__ == '__main__':
    try:
        install(Path('/opt/share/router-watchdog/defaults.json'),
                Path('/opt/etc/router-watchdog.json'))
    except (OSError, ValueError):
        # Configuration and parser diagnostics may contain secrets.
        print('Failed to merge watchdog configuration; existing config retained.', file=sys.stderr)
        sys.exit(1)
