import importlib.util
import json
import os
import pathlib
import subprocess
import unittest
from unittest import mock

SERVER = pathlib.Path(__file__).resolve().parents[1] / 'tools/xkeen_mcp.py'


class TestMCPBridge(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SERVER.exists(), 'MCP SSH bridge must exist')
        spec = importlib.util.spec_from_file_location('xkeen_mcp', SERVER)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.env = mock.patch.dict(os.environ, {'XKEEN_SSH_HOST': 'router',
                                               'XKEEN_SSH_PORT': '222'}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.run = mock.patch.object(self.module.subprocess, 'run').start()
        self.addCleanup(mock.patch.stopall)
        self.run.return_value = subprocess.CompletedProcess([], 0, json.dumps({'applied': False}), '')

    def test_fixed_measure_command_and_noninteractive_ssh(self):
        result = self.module.call_watchdog('measure')
        self.assertEqual(result, {'applied': False})
        args = self.run.call_args.args[0]
        self.assertEqual(args[-2:], ['router', '/opt/bin/router-watchdog --measure-selected'])
        self.assertIn('BatchMode=yes', args)
        self.assertIn('StrictHostKeyChecking=yes', args)
        self.assertIn('222', args)
        self.assertNotIn('shell', self.run.call_args.kwargs)

    def test_search_does_not_apply_by_default(self):
        self.module.call_watchdog('find')
        self.assertEqual(self.run.call_args.args[0][-1], '/opt/bin/router-watchdog --find-faster')

    def test_apply_denied_without_local_capability(self):
        with self.assertRaisesRegex(ValueError, 'XKEEN_ALLOW_APPLY'):
            self.module.call_watchdog('find', apply=True)
        self.run.assert_not_called()

    def test_apply_requires_search_and_local_capability(self):
        os.environ['XKEEN_ALLOW_APPLY'] = '1'
        self.module.call_watchdog('find', apply=True)
        self.assertTrue(self.run.call_args.args[0][-1].endswith('--find-faster --apply'))
        self.run.reset_mock()
        with self.assertRaises(ValueError):
            self.module.call_watchdog('measure', apply=True)
        self.run.assert_not_called()

    def test_untrusted_host_and_invalid_port_rejected_before_ssh(self):
        for host in ['-oProxyCommand=evil', 'router;whoami', 'router\ncommand', '']:
            with self.subTest(host=host), mock.patch.dict(os.environ, {'XKEEN_SSH_HOST': host}):
                with self.assertRaises(ValueError):
                    self.module.call_watchdog('measure')
        with mock.patch.dict(os.environ, {'XKEEN_SSH_PORT': '0'}):
            with self.assertRaises(ValueError):
                self.module.call_watchdog('measure')
        self.run.assert_not_called()

    def test_unknown_operation_rejected(self):
        with self.assertRaises(ValueError):
            self.module.call_watchdog('restart')
        self.run.assert_not_called()

    def test_busy_and_failure_hide_raw_output(self):
        self.run.return_value = subprocess.CompletedProcess([], 1, '{"error":"busy"}', 'private-token')
        with self.assertRaisesRegex(RuntimeError, 'busy') as raised:
            self.module.call_watchdog('measure')
        self.assertNotIn('private-token', str(raised.exception))
        self.run.return_value = subprocess.CompletedProcess([], 1, 'https://private/token', 'private-token')
        with self.assertRaises(RuntimeError) as raised:
            self.module.call_watchdog('measure')
        self.assertNotIn('private', str(raised.exception))

    def test_timeout_reports_remote_operation_may_continue(self):
        self.run.side_effect = subprocess.TimeoutExpired('ssh', 1800)
        with self.assertRaisesRegex(RuntimeError, 'continue'):
            self.module.call_watchdog('measure')

    def test_malformed_success_is_rejected(self):
        for output in ['log line\n{}', '[]', '{}', '{"error":"secret-token"}']:
            self.run.return_value = subprocess.CompletedProcess([], 0, output, '')
            with self.subTest(output=output), self.assertRaises(RuntimeError):
                self.module.call_watchdog('measure')


    def test_config_patch_is_stdin_not_remote_command(self):
        changes = {'speed_test_url': 'https://example.com/file?q=$(do-not-run)', 'top_n': 3}
        self.run.return_value = subprocess.CompletedProcess([], 0,
            '{"updated_fields":["speed_test_url","top_n"],"cron_sync_required":false}', '')
        result = self.module.call_watchdog('update', changes=changes)
        self.assertEqual(result['updated_fields'], ['speed_test_url', 'top_n'])
        self.assertEqual(self.run.call_args.args[0][-1], '/opt/bin/router-watchdog --update-config')
        self.assertEqual(json.loads(self.run.call_args.kwargs['input']), changes)
        self.assertNotIn('do-not-run', self.run.call_args.args[0][-1])

    def test_get_config_checks_response_shape(self):
        self.run.return_value = subprocess.CompletedProcess([], 0,
            '{"config":{"top_n":7},"editable_fields":["top_n"],"secret_configured":true}', '')
        result = self.module.call_watchdog('get')
        self.assertEqual(result['config'], {'top_n': 7})
        self.assertEqual(self.run.call_args.args[0][-1], '/opt/bin/router-watchdog --get-config')

    def test_invalid_config_payload_never_starts_ssh(self):
        for changes in [None, [], {}, {'switch_wait_seconds': float('nan')}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.module.call_watchdog('update', changes=changes)
        self.run.assert_not_called()
