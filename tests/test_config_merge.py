import importlib.util
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

PATH = pathlib.Path(__file__).resolve().parents[1] / 'net/router-watchdog/files/opt/libexec/router-watchdog/merge_config.py'
spec = importlib.util.spec_from_file_location('merge_config', PATH)
module = importlib.util.module_from_spec(spec)


class TestConfigMerge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec.loader.exec_module(module)

    def test_merge_uses_new_schema_and_preserves_filled_values(self):
        defaults = {'secret': '', 'count': 7, 'enabled': True, 'new': 9,
                    'nested': {'a': 1, 'b': 2}, 'items': [1], 'text': 'default'}
        old = {'secret': 'private', 'count': 0, 'enabled': False,
               'nested': {'a': 3, 'removed': 4}, 'items': [], 'text': '', 'removed': 5}
        self.assertEqual(module.merge(defaults, old),
                         {'secret': 'private', 'count': 0, 'enabled': False, 'new': 9,
                          'nested': {'a': 3, 'b': 2}, 'items': [1], 'text': 'default'})
        self.assertEqual(module.merge({'a': [1]}, {'a': [2, 3]}), {'a': [2, 3]})
        self.assertEqual(module.merge({'a': 1}, {'a': None}), {'a': 1})

    def test_upgrade_backups_exact_original_and_installs_merged_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            defaults, config = root / 'defaults.json', root / 'config.json'
            defaults.write_text('{"a": 1, "new": 2}')
            original = b'{ "a": 7, "obsolete": 8 }\n'
            config.write_bytes(original)
            module.install(defaults, config)
            self.assertEqual(config.with_name('config.json-old').read_bytes(), original)
            self.assertEqual(json.loads(config.read_text()), {'a': 7, 'new': 2})
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)

    def test_first_install_and_invalid_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            defaults, config = root / 'defaults.json', root / 'config.json'
            defaults.write_text('{"a": 1}')
            module.install(defaults, config)
            self.assertFalse(config.with_name('config.json-old').exists())
            config.write_text('invalid secret')
            with self.assertRaises(ValueError):
                module.install(defaults, config)
            self.assertEqual(config.read_text(), 'invalid secret')
            self.assertFalse(config.with_name('config.json-old').exists())

    def test_failed_replacement_keeps_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            defaults, config = root / 'defaults.json', root / 'config.json'
            defaults.write_text('{"a": 1}')
            config.write_text('{"a": 2}')
            with mock.patch.object(module.os, 'replace', side_effect=OSError('failure')):
                with self.assertRaises(OSError):
                    module.install(defaults, config)
            self.assertEqual(config.read_text(), '{"a": 2}')

    def test_primary_replacement_failure_keeps_config_and_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            defaults, config = root / 'defaults.json', root / 'config.json'
            defaults.write_text('{"a": 1, "new": 3}')
            config.write_text('{"a": 2}')
            backup = config.with_name('config.json-old')
            backup.write_text('previous backup')
            replace = module.os.replace

            def fail_primary(source, destination):
                if destination == config:
                    raise OSError('primary replacement failed')
                replace(source, destination)

            with mock.patch.object(module.os, 'replace', side_effect=fail_primary):
                with self.assertRaises(OSError):
                    module.install(defaults, config)
            self.assertEqual(config.read_text(), '{"a": 2}')
            self.assertEqual(backup.read_text(), '{"a": 2}')
            self.assertEqual(sorted(p.name for p in root.iterdir()),
                             ['config.json', 'config.json-old', 'defaults.json'])

    def test_invalid_defaults_keep_config_and_existing_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            defaults, config = root / 'defaults.json', root / 'config.json'
            defaults.write_text('[]')
            config.write_text('{"a": 2}')
            backup = config.with_name('config.json-old')
            backup.write_text('previous backup')
            with self.assertRaises(ValueError):
                module.install(defaults, config)
            self.assertEqual(config.read_text(), '{"a": 2}')
            self.assertEqual(backup.read_text(), 'previous backup')

    def test_uses_pre_unpack_original_instead_of_opkg_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            defaults, config = root / 'defaults.json', root / 'config.json'
            defaults.write_text('{"a": 9, "new": 3}')
            config.write_text(defaults.read_text())
            staged = root / 'config.json-upgrade'
            staged.write_text('{ "a": 2 }')
            module.install(defaults, config)
            self.assertEqual(json.loads(config.read_text()), {'a': 2, 'new': 3})
            self.assertEqual((root / 'config.json-old').read_text(), '{ "a": 2 }')
            self.assertFalse(staged.exists())

    def test_package_ships_only_defaults_and_does_not_register_conffile(self):
        package = PATH.parents[4]
        makefile = (package / 'Makefile').read_text()
        self.assertNotIn('define Package/router-watchdog/conffiles', makefile)
        body = makefile.split('define Package/router-watchdog/install\n', 1)[1].split('\nendef', 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            script = body.replace('$(1)', directory)
            for macro, command in [('INSTALL_DIR', 'mkdir -p'), ('INSTALL_BIN', 'install -m 755'),
                                   ('INSTALL_DATA', 'install -m 644'), ('INSTALL_CONF', 'install -m 600')]:
                script = script.replace('$(' + macro + ')', command)
            subprocess.run(['sh', '-eu', '-c', script], cwd=package, check=True,
                           capture_output=True)
            root = pathlib.Path(directory)
            self.assertFalse((root / 'opt/etc/router-watchdog.json').exists())
            self.assertTrue((root / 'opt/share/router-watchdog/defaults.json').is_file())

    def test_legacy_upgrade_restores_config_removed_during_unpack(self):
        package = PATH.parents[4]
        makefile = (package / 'Makefile').read_text()
        preinst = makefile.split('define Package/router-watchdog/preinst\n', 1)[1].split('\nendef', 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            defaults, config = root / 'defaults.json', root / 'router-watchdog.json'
            original = '{ "a": 2 }\n'
            defaults.write_text('{"a": 9, "new": 3}')
            config.write_text(original)
            script = preinst.replace('$$', '$').replace('/opt/etc/router-watchdog.json', str(config))
            with mock.patch.dict('os.environ', {'IPKG_INSTROOT': ''}):
                subprocess.run(['sh', '-eu', '-c', script], check=True, capture_output=True)
            config.unlink()  # Legacy package file becomes obsolete during opkg unpack.
            module.install(defaults, config)
            self.assertEqual(json.loads(config.read_text()), {'a': 2, 'new': 3})
            self.assertEqual((root / 'router-watchdog.json-old').read_text(), original)
            self.assertFalse((root / 'router-watchdog.json-upgrade').exists())
