import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/build_package.py'
MAKEFILE = ROOT / 'net/router-watchdog/Makefile'


def contents(data):
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        return {entry.name.removeprefix('./'): (entry, archive.extractfile(entry).read()
                if entry.isfile() else None) for entry in archive.getmembers()}


class TestPackageBuilder(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def build(self, *args, output='one'):
        destination = self.root / output
        result = subprocess.run([sys.executable, str(SCRIPT), '--output-dir',
                                 str(destination / 'dist'), '--feed-dir',
                                 str(destination / 'feed'), *map(str, args)],
                                cwd=ROOT, env={**os.environ, 'SOURCE_DATE_EPOCH': '1234567890'},
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return destination

    def test_real_package_preserves_payload_hooks_modes_and_config_ownership(self):
        output = self.build()
        package, = (output / 'dist').glob('*.ipk')
        outer = contents(package.read_bytes())
        self.assertEqual(set(outer), {'debian-binary', 'control.tar.gz', 'data.tar.gz'})
        self.assertEqual(outer['debian-binary'][1], b'2.0\n')
        control = contents(outer['control.tar.gz'][1])
        self.assertEqual(set(control), {'control', 'preinst', 'postinst', 'prerm'})
        fields = control['control'][1].decode()
        self.assertIn('Architecture: all\n', fields)
        self.assertIn('Depends: python3, python3-yaml, ca-bundle, wget-ssl\n', fields)
        makefile = MAKEFILE.read_text()
        for hook in ('preinst', 'postinst', 'prerm'):
            expected = re.search(r'define Package/router-watchdog/' + hook + r'\n(.*?)\nendef',
                                 makefile, re.S).group(1).replace('$$', '$') + '\n'
            self.assertEqual(control[hook][1], expected.encode())
            self.assertEqual(control[hook][0].mode, 0o755)
        payload = contents(outer['data.tar.gz'][1])
        files = {name: item for name, item in payload.items() if item[0].isfile()}
        mappings = re.findall(r'\$\(INSTALL_(BIN|DATA|CONF)\) (\S+) \$\(1\)/(\S+)', makefile)
        self.assertEqual(set(files), {destination for _, _, destination in mappings})
        for kind, source, destination in mappings:
            self.assertEqual(files[destination][1], (MAKEFILE.parent / source).read_bytes())
            self.assertEqual(files[destination][0].mode,
                             {'BIN': 0o755, 'DATA': 0o644, 'CONF': 0o600}[kind])
        for entry, _ in payload.values():
            self.assertEqual((entry.uid, entry.gid, entry.mtime), (0, 0, 1234567890))

    def test_feed_and_update_manifest_match_actual_ipk(self):
        output = self.build()
        package, = (output / 'dist').glob('*.ipk')
        feed = output / 'feed'
        self.assertEqual((feed / 'all' / package.name).read_bytes(), package.read_bytes())
        index = (feed / 'all/Packages').read_bytes()
        self.assertEqual(gzip.decompress((feed / 'all/Packages.gz').read_bytes()), index)
        digest = hashlib.sha256(package.read_bytes()).hexdigest()
        self.assertIn(('SHA256sum: ' + digest + '\n').encode(), index)
        self.assertIn(('Size: ' + str(package.stat().st_size) + '\n').encode(), index)
        version = re.search(r'^PKG_VERSION:=(.+)$', MAKEFILE.read_text(), re.M).group(1)
        revision = re.search(r'^PKG_RELEASE:=(.+)$', MAKEFILE.read_text(), re.M).group(1)
        self.assertEqual(json.loads((feed / 'update.json').read_text()), {
            'schema_version': 1, 'latest_version': version + '-' + revision,
            'package_url': 'https://arap919.github.io/router-watchdog/all/' + package.name,
            'sha256': digest, 'size': package.stat().st_size,
            'release_url': 'https://github.com/Arap919/router-watchdog/releases/tag/v' + version,
            'release_notes': ''})
        self.assertEqual((feed / 'README.md').read_bytes(), (ROOT / 'README.md').read_bytes())

    def test_archives_are_reproducible(self):
        one, two = self.build(output='one'), self.build(output='two')
        package, = (one / 'dist').glob('*.ipk')
        self.assertEqual(package.read_bytes(), (two / 'dist' / package.name).read_bytes())
        self.assertEqual((one / 'feed/all/Packages.gz').read_bytes(),
                         (two / 'feed/all/Packages.gz').read_bytes())

    def test_feed_only_uses_downloaded_package_version_and_validates_tag(self):
        makefile = self.root / 'Makefile'
        original = MAKEFILE.read_text()
        makefile.write_text(re.sub(r'^PKG_VERSION:=.+$', 'PKG_VERSION:=0.0.7', original, flags=re.M))
        (self.root / 'files').symlink_to(MAKEFILE.parent / 'files', target_is_directory=True)
        built = self.build('--makefile', makefile)
        package, = (built / 'dist').glob('*.ipk')
        feed_only = self.build('--feed-only', package, output='republish')
        self.assertEqual((built / 'feed/update.json').read_bytes(),
                         (feed_only / 'feed/update.json').read_bytes())
        result = subprocess.run([sys.executable, str(SCRIPT), '--feed-only', str(package),
                                 '--release-tag', 'v0.0.1', '--feed-dir', str(self.root / 'bad')],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / 'bad').exists())

    def test_rejects_compilation_architecture_and_unsupported_install_expressions(self):
        original = MAKEFILE.read_text()
        (self.root / 'files').symlink_to(MAKEFILE.parent / 'files', target_is_directory=True)
        for changed, reason in [
                (original.replace('PKGARCH:=all', 'PKGARCH:=mipsel'), 'Only PKGARCH all'),
                (original.replace('\n\ttrue\n', '\n\t$(MAKE) all\n'), 'Compilation is not supported'),
                (original.replace('$(INSTALL_CONF)', '$(CP)'), 'Unsupported installation expression'),
                (original.replace('PKG_VERSION:=', 'PKG_VERSION:=$(shell echo foo)'), 'Unsupported Makefile statement')]:
            with self.subTest(changed=changed[:40]):
                makefile = self.root / 'Makefile'
                makefile.write_text(changed)
                result = subprocess.run([sys.executable, str(SCRIPT), '--makefile', str(makefile),
                                         '--output-dir', str(self.root / 'dist'), '--feed-dir',
                                         str(self.root / 'feed')], cwd=ROOT, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(reason, result.stderr)
                self.assertFalse((self.root / 'dist').exists())


if __name__ == '__main__':
    unittest.main()
