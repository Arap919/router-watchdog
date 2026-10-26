#!/usr/bin/env python3
"""Published-feed update checks and explicit version-pinned opkg installation."""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request

OPKG = '/opt/bin/opkg'
MANIFEST_URL = 'https://arap919.github.io/router-watchdog/update.json'
PACKAGE_BASE = 'https://arap919.github.io/router-watchdog/all/'
RELEASE_BASE = 'https://github.com/Arap919/router-watchdog/releases/tag/v'
UPDATE_LOCK_PATH = Path('/tmp/router_watchdog_update.lock')
MAX_PACKAGE_BYTES = 64 * 1024 * 1024


class UpdateError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)-(?:0|[1-9][0-9]*)', value):
        raise UpdateError('invalid_version', 'Expected a package version in X.Y.Z-N format')
    return tuple(int(part) for part in value.replace('-', '.').split('.'))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def _open(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'router-watchdog-updater',
                                                  'Cache-Control': 'no-cache'})
    return urllib.request.build_opener(NoRedirect()).open(request, timeout=15)


def fetch_manifest():
    try:
        with _open(MANIFEST_URL) as response:
            data = response.read(65537)
        if len(data) > 65536:
            raise ValueError
        manifest = json.loads(data)
        if not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int or manifest['schema_version'] != 1:
            raise ValueError
        latest = manifest['latest_version']
        version(latest)
        if manifest['package_url'] != PACKAGE_BASE + f'router-watchdog_{latest}_all.ipk':
            raise ValueError
        if manifest['release_url'] != RELEASE_BASE + latest.rsplit('-', 1)[0]:
            raise ValueError
        if not isinstance(manifest['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', manifest['sha256']):
            raise ValueError
        if type(manifest['size']) is not int or not 0 < manifest['size'] <= MAX_PACKAGE_BYTES:
            raise ValueError
        if not isinstance(manifest.get('release_notes', ''), str):
            raise ValueError
        return manifest
    except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError):
        raise UpdateError('manifest_unavailable', 'Cannot read a valid published update manifest') from None


def opkg_environment():
    return {**os.environ, 'PATH': '/opt/bin:/opt/sbin:' + os.environ.get('PATH', '/usr/bin:/bin')}


def installed_version():
    try:
        response = subprocess.run([OPKG, 'status', 'router-watchdog'], capture_output=True,
                                  text=True, timeout=15, check=False, env=opkg_environment())
    except (OSError, subprocess.TimeoutExpired):
        raise UpdateError('opkg_unavailable', 'Cannot query Entware opkg') from None
    if response.returncode:
        raise UpdateError('opkg_unavailable', 'Cannot query Entware opkg')
    fields = dict(line.split(': ', 1) for line in response.stdout.splitlines() if ': ' in line)
    if fields.get('Package') != 'router-watchdog' or fields.get('Status', '').split()[-1:] != ['installed']:
        return None
    installed = fields.get('Version')
    version(installed)
    return installed


def check_update():
    manifest = fetch_manifest()
    installed = installed_version()
    latest = manifest['latest_version']
    return {'installed_version': installed, 'latest_version': latest,
            'update_available': installed is None or version(latest) > version(installed),
            'release_url': manifest['release_url'], 'release_notes': manifest.get('release_notes', ''),
            'checked_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}


@contextlib.contextmanager
def update_lock():
    try:
        fd = os.open(UPDATE_LOCK_PATH, os.O_CREAT | os.O_WRONLY, 0o600)
    except OSError:
        raise UpdateError('lock_unavailable', 'Cannot open update lock') from None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise UpdateError('busy', 'Another update is already in progress') from None
        yield
    finally:
        os.close(fd)


def download_package(manifest, path):
    received = 0
    started = time.monotonic()
    try:
        with _open(manifest['package_url']) as response, path.open('wb') as output:
            reader = getattr(response, 'read1', response.read)
            while True:
                if time.monotonic() - started > 45:
                    raise UpdateError('download_failed', 'Package download exceeded the time limit')
                chunk = reader(64 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                if received > manifest['size']:
                    raise UpdateError('download_failed', 'Downloaded package exceeds the declared size')
                output.write(chunk)
    except (OSError, urllib.error.URLError):
        raise UpdateError('download_failed', 'Cannot download the published package') from None


def verify_package(path, manifest):
    try:
        if path.stat().st_size != manifest['size']:
            raise ValueError
        digest = hashlib.sha256()
        with path.open('rb') as handle:
            for chunk in iter(lambda: handle.read(65536), b''):
                digest.update(chunk)
        if digest.hexdigest() != manifest['sha256']:
            raise ValueError
        def member(archive, name, limit):
            entries = [item for item in archive.getmembers() if item.name.lstrip('./') == name]
            if len(entries) != 1 or not entries[0].isfile() or entries[0].size > limit:
                raise ValueError
            return archive.extractfile(entries[0]).read()
        with tarfile.open(path, 'r:gz') as outer:
            inner_bytes = member(outer, 'control.tar.gz', 1024 * 1024)
        with tarfile.open(fileobj=io.BytesIO(inner_bytes), mode='r:gz') as inner:
            control = member(inner, 'control', 65536).decode()
        fields = dict(line.split(': ', 1) for line in control.splitlines() if ': ' in line)
        if (fields.get('Package') != 'router-watchdog' or fields.get('Architecture') != 'all'
                or fields.get('Version') != manifest['latest_version']):
            raise ValueError
    except (OSError, ValueError, KeyError, tarfile.TarError, UnicodeError):
        raise UpdateError('invalid_package', 'Package integrity or control metadata verification failed') from None


def run_opkg(arguments):
    try:
        response = subprocess.run([OPKG, *arguments], capture_output=True, text=True,
                                  timeout=60 if arguments[0] == 'update' else 120, check=False, env=opkg_environment())
    except subprocess.TimeoutExpired:
        raise UpdateError('update_timeout', 'Package manager timed out; inspect local opkg state before retrying') from None
    except OSError:
        raise UpdateError('opkg_unavailable', 'Cannot start Entware opkg') from None
    if response.returncode:
        raise UpdateError('opkg_failed', 'Package manager failed; inspect opkg locally before retrying')


def install_update(expected_version):
    version(expected_version)
    with update_lock():
        manifest = fetch_manifest()
        if expected_version != manifest['latest_version']:
            raise UpdateError('stale_version', 'Available release changed; check updates again')
        installed = installed_version()
        if installed is None:
            raise UpdateError('not_installed', 'Use install.sh for the initial managed installation')
        if version(installed) > version(expected_version):
            raise UpdateError('downgrade_refused', 'Installed version is newer than the requested release')
        if installed == expected_version:
            return {'installed_version': installed, 'updated': False}
        with tempfile.TemporaryDirectory(prefix='router-watchdog-update-') as folder:
            path = Path(folder) / f'router-watchdog_{expected_version}_all.ipk'
            download_package(manifest, path)
            verify_package(path, manifest)
            # Do not hold the watchdog action lock: opkg postinst invokes --sync-cron.
            run_opkg(['update'])
            run_opkg(['install', str(path)])
        actual = installed_version()
        if actual != expected_version:
            raise UpdateError('verification_failed', 'Installed package version did not match the requested update')
        return {'installed_version': actual, 'updated': True}


def main(expected_version=None):
    try:
        result = check_update() if expected_version is None else install_update(expected_version)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except UpdateError as exc:
        print(json.dumps({'error': exc.code, 'message': str(exc)}))
        return 1
    except Exception:
        print(json.dumps({'error': 'update_failed', 'message': 'Update operation failed; inspect the router locally'}))
        return 1
