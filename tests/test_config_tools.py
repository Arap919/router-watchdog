import contextlib
import io
import http.server
import threading
import time
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
        self.assertEqual(set(module.CONFIG_FIELDS), set(DEFAULT_CONFIG) - {'_comment_speed_test_provider'})

    def test_measure_speed_uses_cloudflare_constant(self):
        cfg = {**self.cfg, 'speed_test_provider': 'cloudflare',
               'parallel_streams': 1, 'multi_rounds': 1, 'switch_wait_seconds': 0}
        with (mock.patch.object(module, 'download', return_value=1000000) as download,
              mock.patch.object(module, 'log'), mock.patch.object(module.time, 'sleep'),
              mock.patch.object(module.time, 'monotonic', side_effect=[0, 1])):
            module.measure_speed(mock.Mock(), cfg, 'node')
        download.assert_called_once_with(cfg['benchmark_proxy'], cfg['download_bytes'],
                                         cfg['speed_connect_timeout_seconds'], module.DEFAULT_SPEED_TEST_URL)

    def test_download_has_no_total_duration_limit(self):
        result = module.subprocess.CompletedProcess([], 0, '1000000', '')
        with mock.patch.object(module.subprocess, 'run', return_value=result) as run:
            self.assertEqual(module.download('http://127.0.0.1:17890', 1000000, 5), 1000000)
        self.assertIsNone(run.call_args.kwargs.get('timeout'))

    def test_real_download_worker_success_and_stalled_body_socket_timeout(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Length', '1000000')
                self.end_headers()
                try:
                    if self.path.endswith('/stall'):
                        self.wfile.write(b'x')
                        self.wfile.flush()
                        time.sleep(2)
                    else:
                        self.wfile.write(b'x' * 1000000)
                except OSError:
                    pass

        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f'http://127.0.0.1:{server.server_port}'
            self.assertEqual(module.download(url, 1000000, 5, url + '/ok'), 1000000)
            started = time.monotonic()
            with self.assertRaises(module.SpeedTestError) as raised:
                module.download(url, 1000000, 0.5, url + '/stall')
            self.assertEqual(raised.exception.code, 'download_timeout')
            self.assertLess(time.monotonic() - started, 1.5)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_download_worker_failure_is_allowlisted(self):
        for output, expected in [('download_http_error', 'download_http_error'),
                                 ('https://private/token', 'download_failed')]:
            result = module.subprocess.CompletedProcess([], 1, output, 'private-token')
            with mock.patch.object(module.subprocess, 'run', return_value=result):
                with self.assertRaises(module.SpeedTestError) as raised:
                    module.download('http://127.0.0.1:17890', 1000000, 5)
            self.assertEqual(raised.exception.code, expected)
            self.assertNotIn('private', str(raised.exception))

    def test_default_is_configurable(self):
        self.assertEqual(module.validate_config(self.cfg)['speed_test_provider'], 'cloudflare')
        self.assertIn('speed_test_provider', DEFAULT_CONFIG)

    def test_download_renders_template_and_keeps_query(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.side_effect = [b'x' * 1000000]
        opener = mock.Mock()
        opener.open.return_value = response
        with (mock.patch.object(module.urllib.request, 'build_opener', return_value=opener),
              mock.patch.object(module.time, 'time_ns', return_value=123)):
            received = module._download('http://127.0.0.1:17890', 1000000, 5,
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
                module.download_url(url, 1000000)

    def test_provider_accepts_only_two_exact_values(self):
        for value in ('speedtest', 'cloudflare'):
            self.assertEqual(module.validate_config({**self.cfg, 'speed_test_provider': value})['speed_test_provider'], value)
        for value in ('', None, True, [], {}, 'SPEEDTEST', 'other'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                module.validate_config({**self.cfg, 'speed_test_provider': value})

    def test_legacy_url_is_not_editable(self):
        self.assertNotIn('speed_test_url', module.CONFIG_FIELDS)
        self.assertNotIn('_comment_speed_test_provider', module.CONFIG_FIELDS)

    def test_speedtest_selects_benchmark_and_converts_bytes_per_second(self):
        cfg = {**self.cfg, 'speed_test_provider': 'speedtest', 'switch_wait_seconds': 0}
        client = mock.Mock()
        response = module.subprocess.CompletedProcess([], 0, json.dumps({
            'servers': [{'id': '6691', 'dl_speed': 12500000}]}), '')
        events = []
        client.select.side_effect = lambda *args: events.append('select')
        with (mock.patch.object(module.subprocess, 'run', return_value=response) as run,
              mock.patch.object(module, 'download') as download,
              mock.patch.object(module, 'log'), mock.patch.object(module.time, 'sleep')):
            run.side_effect = lambda *args, **kwargs: (events.append('run') or response)
            self.assertEqual(module.measure_speed(client, cfg, 'node'), 100)
        self.assertEqual(events, ['select', 'run'])
        client.select.assert_called_once_with('BENCHMARK', 'node', cfg['speed_connect_timeout_seconds'])
        command = run.call_args.args[0]
        self.assertEqual(command[0], '/opt/bin/speedtest-go')
        self.assertIn('--proxy=' + cfg['benchmark_proxy'], command)
        self.assertIn('--no-upload', command)
        self.assertIn('--json', command)
        self.assertIn('--ping-mode=http', command)
        self.assertNotIn('--list', command)
        self.assertFalse(any(arg.startswith('--server') for arg in command))
        self.assertFalse(run.call_args.kwargs.get('shell', False))
        self.assertGreater(run.call_args.kwargs['timeout'], 0)
        download.assert_not_called()

    def test_speedtest_rejects_failed_or_invalid_results(self):
        cfg = {**self.cfg, 'speed_test_provider': 'speedtest'}
        payloads = ['not json', '{}', '[]', '{"servers":[]}',
                    '{"servers":[{}]}', '{"servers":[{"dl_speed":0}]}',
                    '{"servers":[{"dl_speed":-1}]}', '{"servers":[{"dl_speed":true}]}',
                    '{"servers":[{"dl_speed":"100"}]}',
                    '{"servers":[{"dl_speed":NaN}]}',
                    '{"servers":[{"dl_speed":Infinity}]}']
        results = [module.subprocess.CompletedProcess([], 0, payload, 'private') for payload in payloads]
        results.append(module.subprocess.CompletedProcess([], 1, 'private', 'private'))
        for result in results:
            with (self.subTest(result=result),
                  mock.patch.object(module.subprocess, 'run', return_value=result),
                  mock.patch.object(module, 'log'), mock.patch.object(module.time, 'sleep'),
                  self.assertRaises(module.SpeedTestError) as raised):
                module.measure_speed(mock.Mock(), cfg, 'node')
            self.assertNotIn('private', str(raised.exception))

    def test_speedtest_missing_binary_and_timeout_are_sanitized(self):
        cfg = {**self.cfg, 'speed_test_provider': 'speedtest'}
        for error in (FileNotFoundError('private'), module.subprocess.TimeoutExpired('private', 180)):
            with (mock.patch.object(module.subprocess, 'run', side_effect=error),
                  mock.patch.object(module, 'log'), mock.patch.object(module.time, 'sleep'),
                  self.assertRaises(module.SpeedTestError) as raised):
                module.measure_speed(mock.Mock(), cfg, 'node')
            self.assertNotIn('private', str(raised.exception))


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
                 {'switch_wait_seconds': float('inf')}, {'speed_test_provider': 'other'},
                 {'speed_test_url': 'https://example.com/file'}, [], {}]
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
        self.assertIn('speed_test_provider', result['editable_fields'])
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
