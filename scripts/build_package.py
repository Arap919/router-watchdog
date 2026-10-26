#!/usr/bin/env python3
"""Build the architecture-independent script package without an Entware toolchain."""

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile


ROOT = Path(__file__).resolve().parents[1]
FEED_URL = 'https://arap919.github.io/router-watchdog/all/'
RELEASE_URL = 'https://github.com/Arap919/router-watchdog/releases/tag/'
VERSION = re.compile(r'[0-9]+\.[0-9]+\.[0-9]+-[0-9]+')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def safe_path(value):
    path = PurePosixPath(value)
    require(not path.is_absolute() and '..' not in path.parts and
            re.fullmatch(r'[A-Za-z0-9_./-]+', value), 'Unsupported path: ' + value)
    return str(path)


def parse_makefile(path):
    """Accept only the simple package definition this repository currently uses."""
    text = path.read_text(encoding='utf-8')
    definitions = {}
    variables = {}
    current = None
    for line in text.splitlines():
        if current is not None:
            if line == 'endef':
                current = None
            else:
                definitions[current].append(line)
            continue
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if line.startswith('define '):
            current = line[7:]
            require(current not in definitions, 'Duplicate definition: ' + current)
            definitions[current] = []
            continue
        if line in ('include $(TOPDIR)/rules.mk', 'include $(INCLUDE_DIR)/package.mk',
                    '$(eval $(call BuildPackage,router-watchdog))'):
            continue
        match = re.fullmatch(r'(PKG_NAME|PKG_VERSION|PKG_RELEASE|PKG_MAINTAINER|PKG_LICENSE|PKG_LICENSE_FILES):=([^$\n]+)', line)
        require(match is not None, 'Unsupported Makefile statement: ' + line)
        key, value = match.groups()
        require(key not in variables, 'Duplicate variable: ' + key)
        variables[key] = value.strip()
    require(current is None, 'Unclosed Makefile definition')
    name = variables.get('PKG_NAME')
    require(name == 'router-watchdog', 'Unsupported package name')
    allowed = {f'Package/{name}', f'Package/{name}/description', 'Build/Compile',
               f'Package/{name}/install', *(f'Package/{name}/{hook}' for hook in
                                         ('preinst', 'postinst', 'prerm'))}
    require(set(definitions) == allowed, 'Unsupported or missing Makefile definitions')
    metadata = {}
    for line in definitions[f'Package/{name}']:
        match = re.fullmatch(r'\s*(SECTION|CATEGORY|TITLE|DEPENDS|PKGARCH):=([^$\n]+)', line)
        require(match is not None, 'Unsupported package metadata: ' + line)
        key, value = match.groups()
        require(key not in metadata, 'Duplicate package metadata: ' + key)
        metadata[key] = value.strip()
    require(metadata.get('PKGARCH') == 'all', 'Only PKGARCH all is supported')
    require([line.strip() for line in definitions['Build/Compile'] if line.strip()] == ['true'],
            'Compilation is not supported by the script package builder')
    version = variables.get('PKG_VERSION', '') + '-' + variables.get('PKG_RELEASE', '')
    require(VERSION.fullmatch(version), 'Unsupported package version')
    dependencies = metadata.get('DEPENDS', '').split()
    require(dependencies and all(re.fullmatch(r'\+[A-Za-z0-9][A-Za-z0-9+_.-]*', dep)
                                 for dep in dependencies), 'Unsupported dependency expression')
    payload = {}
    for raw in definitions[f'Package/{name}/install']:
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        directory = re.fullmatch(r'\$\(INSTALL_DIR\) \$\(1\)/(\S+)', line)
        if directory:
            destination = safe_path(directory.group(1))
            require(destination not in payload, 'Duplicate installed path')
            payload[destination] = (None, 0o755)
            continue
        match = re.fullmatch(r'\$\(INSTALL_(BIN|DATA|CONF)\) (\./files/\S+) \$\(1\)/(\S+)', line)
        require(match is not None, 'Unsupported installation expression: ' + line)
        kind, source, destination = match.groups()
        source, destination = safe_path(source), safe_path(destination)
        source_path = path.parent / source
        require(source_path.is_file() and not source_path.is_symlink(),
                'Missing or unsupported payload file: ' + source)
        require(destination not in payload, 'Duplicate installed path')
        payload[destination] = (source_path.read_bytes(), {'BIN': 0o755, 'DATA': 0o644, 'CONF': 0o600}[kind])
    description = definitions[f'Package/{name}/description']
    require(description and all('$' not in line for line in description), 'Unsupported description')
    control = [f'Package: {name}', f'Version: {version}',
               'Depends: ' + ', '.join(dep[1:] for dep in dependencies),
               'Section: ' + metadata['SECTION'], 'Architecture: all',
               'Maintainer: ' + variables['PKG_MAINTAINER'],
               'License: ' + variables['PKG_LICENSE'],
               'Description: ' + metadata['TITLE']]
    control.extend(' ' + line for line in description)
    controls = {'control': (('\n'.join(control) + '\n').encode(), 0o644)}
    for hook in ('preinst', 'postinst', 'prerm'):
        body = '\n'.join(definitions[f'Package/{name}/{hook}']) + '\n'
        require('$(' not in body, 'Make expressions in maintainer hooks are unsupported')
        require(not re.search(r'(?<!\$)\$(?!\$)', body.replace('$$', '')),
                'Unescaped make variable in maintainer hook')
        controls[hook] = (body.replace('$$', '$').encode(), 0o755)
    return name, version, controls, payload


def compressed(data, epoch):
    output = io.BytesIO()
    with gzip.GzipFile(filename='', mode='wb', fileobj=output, compresslevel=9, mtime=epoch) as stream:
        stream.write(data)
    return output.getvalue()


def archive(entries, epoch):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w', format=tarfile.USTAR_FORMAT) as target:
        for name, (data, mode) in sorted(entries.items()):
            info = tarfile.TarInfo('./' + name)
            info.mode, info.mtime = mode, epoch
            if data is None:
                info.type = tarfile.DIRTYPE
            else:
                info.size = len(data)
            target.addfile(info, None if data is None else io.BytesIO(data))
    return compressed(buffer.getvalue(), epoch)


def read_control(package):
    def member(source, name):
        entries = [entry for entry in source.getmembers() if entry.name.removeprefix('./') == name]
        require(len(entries) == 1 and entries[0].isfile(), 'Invalid IPK control structure')
        return source.extractfile(entries[0]).read()
    with tarfile.open(fileobj=io.BytesIO(package), mode='r:gz') as outer:
        require(member(outer, 'debian-binary') == b'2.0\n', 'Unsupported IPK format')
        data = member(outer, 'control.tar.gz')
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as inner:
        control = member(inner, 'control').decode('utf-8')
    fields = {}
    for line in control.splitlines():
        if line.startswith((' ', '\t')) or not line:
            continue
        require(': ' in line, 'Invalid IPK control metadata')
        key, value = line.split(': ', 1)
        require(key not in fields, 'Duplicate IPK control field')
        fields[key] = value
    require(fields.get('Package') == 'router-watchdog' and fields.get('Architecture') == 'all',
            'Unsupported package identity or architecture')
    require(VERSION.fullmatch(fields.get('Version', '')), 'Unsupported IPK version')
    return control, fields


def build_feed(package, feed_dir, readme, epoch, release_tag=None):
    data = package.read_bytes()
    control, fields = read_control(data)
    version = fields['Version']
    expected_name = 'router-watchdog_' + version + '_all.ipk'
    require(package.name == expected_name, 'IPK filename/control mismatch')
    tag = 'v' + version.rsplit('-', 1)[0]
    require(release_tag is None or release_tag == tag, 'Release tag/IPK version mismatch')
    digest = hashlib.sha256(data).hexdigest()
    metadata = (control.rstrip('\n') + '\nFilename: ' + package.name + '\nSize: ' + str(len(data)) +
                '\nSHA256sum: ' + digest + '\n\n').encode()
    manifest = {'schema_version': 1, 'latest_version': version,
                'package_url': FEED_URL + package.name, 'sha256': digest, 'size': len(data),
                'release_url': RELEASE_URL + tag, 'release_notes': ''}
    # Fail rather than silently retain packages from a different version.
    require(not feed_dir.exists() or not any(feed_dir.iterdir()), 'Feed directory must be empty')
    readme_data = readme.read_bytes()
    destination = feed_dir / 'all'
    destination.mkdir(parents=True, exist_ok=True)
    (destination / package.name).write_bytes(data)
    (destination / 'Packages').write_bytes(metadata)
    (destination / 'Packages.gz').write_bytes(compressed(metadata, epoch))
    (feed_dir / 'update.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    (feed_dir / 'README.md').write_bytes(readme_data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--makefile', type=Path, default=ROOT / 'net/router-watchdog/Makefile')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'dist')
    parser.add_argument('--feed-dir', type=Path, default=ROOT / 'feed')
    parser.add_argument('--readme', type=Path, default=ROOT / 'README.md')
    parser.add_argument('--feed-only', type=Path, metavar='IPK')
    parser.add_argument('--release-tag')
    args = parser.parse_args()
    try:
        epoch = int(os.environ.get('SOURCE_DATE_EPOCH', '0'))
        require(0 <= epoch <= 0xffffffff, 'Invalid SOURCE_DATE_EPOCH')
        if args.feed_only:
            package = args.feed_only
        else:
            name, version, control, payload = parse_makefile(args.makefile)
            data = archive({'debian-binary': (b'2.0\n', 0o644),
                            'control.tar.gz': (archive(control, epoch), 0o644),
                            'data.tar.gz': (archive(payload, epoch), 0o644)}, epoch)
            args.output_dir.mkdir(parents=True, exist_ok=True)
            package = args.output_dir / f'{name}_{version}_all.ipk'
            package.write_bytes(data)
        build_feed(package, args.feed_dir, args.readme, epoch, args.release_tag)
        print('Package: ' + str(package))
        print('Feed: ' + str(args.feed_dir))
    except (ValueError, OSError, tarfile.TarError, KeyError) as error:
        parser.exit(1, 'Packaging failed: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
