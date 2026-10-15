import importlib.util
import json
import pathlib
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
