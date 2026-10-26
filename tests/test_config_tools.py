import contextlib
import io
import json
import os
import pathlib
import stat
import tempfile
import unittest
from unittest import mock

from test_cli import module
from test_failover import DEFAULT_CONFIG


class TestSpeedService(unittest.TestCase):
    def setUp(self):
        self.cfg = {**DEFAULT_CONFIG, 'target_group': 'main'}

    def test_editable_fields_match_packaged_schema(self):
        self.assertTrue(hasattr(module, 'CONFIG_FIELDS'))
        self.assertEqual(set(module.CONFIG_FIELDS), set(DEFAULT_CONFIG))

    def test_measure_speed_forwards_custom_service(self):
        cfg = {**self.cfg, 'speed_test_url': 'https://example.com/custom',
               'parallel_streams': 1, 'multi_rounds': 1, 'switch_wait_seconds': 0}
        with (mock.patch.object(module, 'download', return_value=1000000) as download,
              mock.patch.object(module, 'log'), mock.patch.object(module.time, 'sleep'),
              mock.patch.object(module.time, 'monotonic', side_effect=[0, 1])):
            module.measure_speed(mock.Mock(), cfg, 'node')
        download.assert_called_once_with(cfg['benchmark_proxy'], cfg['download_bytes'],
                                         cfg['speed_connect_timeout_seconds'], cfg['speed_test_url'])

    def test_default_is_configurable(self):
        self.assertIn('speed_test_url', module.validate_config(self.cfg))
        self.assertIn('speed_test_url', DEFAULT_CONFIG)

    def test_download_renders_template_and_keeps_query(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.side_effect = [b'x' * 1000000]
        opener = mock.Mock()
        opener.open.return_value = response
        with (mock.patch.object(module.urllib.request, 'build_opener', return_value=opener),
              mock.patch.object(module.time, 'time_ns', return_value=123)):
            received = module.download('http://127.0.0.1:17890', 1000000, 5,
                                       'https://test.example/down?token=a&size={bytes}&t={cache_bust}')
        self.assertEqual(received, 1000000)
        self.assertEqual(opener.open.call_args.args[0].full_url,
                         'https://test.example/down?token=a&size=1000000&t=123')

    def test_service_rejects_invalid_url_and_placeholders(self):
        cases = ['', None, 'file:///etc/passwd', 'https://user:pass@example.com/file',
                 'https://example.com/{unknown}', 'https://example.com/{bytes.x}',
                 'https://example.com/{bytes!r}', 'https://example.com/{bytes:05}',
                 'https://example.com/{', 'https://example.com:bad/file',
                 'https://example.com/file#fragment', 'https://example.com/white space']
        for url in cases:
            with self.subTest(url=url), self.assertRaises(ValueError):
                module.validate_config({**self.cfg, 'speed_test_url': url})

    def test_static_service_url_is_valid(self):
        cfg = module.validate_config({**self.cfg, 'speed_test_url': 'https://example.com/large.bin'})
        self.assertEqual(cfg['speed_test_url'], 'https://example.com/large.bin')


class TestConfigTools(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = pathlib.Path(self.temp.name) / 'config.json'
        self.cfg = {**DEFAULT_CONFIG, 'target_group': 'main', 'secret': 'private-value',
                    'old_custom_field': {'keep': True}}
        self.path.write_text(json.dumps(self.cfg))
        self.patch = mock.patch.object(module, 'CONFIG_PATH', self.path)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def update(self, changes):
        self.assertTrue(hasattr(module, 'update_config'), 'strict config update must exist')
        return module.update_config(self.cfg, changes)

    def test_patch_preserves_other_values_and_hides_secret(self):
        result = self.update({'top_n': 3})
        written = json.loads(self.path.read_text())
        self.assertEqual(written, {**self.cfg, 'top_n': 3})
        self.assertEqual(result['updated_fields'], ['top_n'])
        self.assertFalse(result['cron_sync_required'])
        self.assertNotIn('private-value', json.dumps(result))
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_unknown_type_null_and_nested_keys_fail_without_writing(self):
        cases = [{'not_a_setting': 1}, {'old_custom_field': {}}, {'top_n': True},
                 {'top_n': '3'}, {'parallel_streams': 0}, {'secret': None},
                 {'target_group': ''}, {'benchmark_group': 'main'},
                 {'schedule': {'windows': [], 'command': 'evil'}},
                 {'schedule': {'windows': [{'start':'07:00','end':'08:00',
                                            'every_minutes':1,'command':'evil'}]}},
                 {'switch_wait_seconds': float('inf')}, [], {}]
        original = self.path.read_bytes()
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.update(changes)
            self.assertEqual(self.path.read_bytes(), original)

    def test_schedule_requires_cron_sync_and_is_not_synchronized_implicitly(self):
        with mock.patch.object(module, 'sync_cron') as sync:
            result = self.update({'schedule': {'windows': []}})
        self.assertTrue(result['cron_sync_required'])
        sync.assert_not_called()

    def test_read_config_redacts_secret_and_exposes_editable_fields(self):
        self.assertTrue(hasattr(module, 'config_view'), 'safe config view must exist')
        result = module.config_view(self.cfg)
        self.assertNotIn('secret', result['config'])
        self.assertNotIn('old_custom_field', result['config'])
        self.assertTrue(result['secret_configured'])
        self.assertIn('speed_test_url', result['editable_fields'])
        self.assertIn('secret', result['editable_fields'])
        self.assertNotIn('private-value', json.dumps(result))

    def test_atomic_replace_failure_retains_file_and_cleans_temp(self):
        before = self.path.read_bytes()
        with mock.patch.object(module.os, 'replace', side_effect=OSError('write failed')):
            with self.assertRaises(OSError):
                self.update({'top_n': 3})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_cli_patch_reads_json_stdin_and_returns_only_result(self):
        with (mock.patch.object(module, 'LOCK_PATH', self.path.parent / 'lock'),
              mock.patch('sys.argv', ['router-watchdog', '--update-config']),
              mock.patch('sys.stdin', io.StringIO('{"top_n": 2}')),
              contextlib.redirect_stdout(io.StringIO()) as out):
            try:
                code = module.main()
            except SystemExit:
                self.fail('CLI --update-config must exist')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())['updated_fields'], ['top_n'])
        self.assertEqual(json.loads(self.path.read_text())['top_n'], 2)


    def test_config_cli_lock_and_invalid_patch_preserve_file(self):
        original = self.path.read_bytes()
        for busy, patch in [(True, '{"top_n":2}'), (False, '{"unknown":1}')]:
            with (mock.patch.object(module, 'LOCK_PATH', self.path.parent / 'lock'),
                  mock.patch.object(module.fcntl, 'flock', side_effect=BlockingIOError if busy else None),
                  mock.patch('sys.argv', ['router-watchdog', '--update-config']),
                  mock.patch('sys.stdin', io.StringIO(patch)),
                  contextlib.redirect_stdout(io.StringIO()) as out):
                code = module.main()
            self.assertNotEqual(code, 0)
            self.assertIn('error', json.loads(out.getvalue()))
            self.assertEqual(self.path.read_bytes(), original)

    def test_get_config_cli_omits_secret(self):
        with (mock.patch.object(module, 'LOCK_PATH', self.path.parent / 'lock'),
              mock.patch('sys.argv', ['router-watchdog', '--get-config']),
              contextlib.redirect_stdout(io.StringIO()) as out):
            code = module.main()
        self.assertEqual(code, 0)
        self.assertNotIn('private-value', out.getvalue())
        self.assertNotIn('secret', json.loads(out.getvalue())['config'])
