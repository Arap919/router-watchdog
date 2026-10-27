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
        self.assertEqual(args[-2:], ['router', '/opt/bin/router-watchdog --measure-selected --mcp-speed-profile'])
        self.assertIn('BatchMode=yes', args)
        self.assertIn('StrictHostKeyChecking=yes', args)
        self.assertIn('222', args)
        self.assertNotIn('shell', self.run.call_args.kwargs)

    def test_search_does_not_apply_by_default(self):
        self.module.call_watchdog('find')
        self.assertEqual(self.run.call_args.args[0][-1], '/opt/bin/router-watchdog --find-faster --mcp-speed-profile')

    def test_measurements_have_no_ssh_duration_limit(self):
        for operation in ('measure', 'find'):
            with self.subTest(operation=operation):
                self.module.call_watchdog(operation)
                self.assertIsNone(self.run.call_args.kwargs.get('timeout'))

    def test_other_operations_keep_ssh_duration_limit(self):
        self.run.return_value = subprocess.CompletedProcess([], 0,
            '{"config":{},"editable_fields":[],"secret_configured":false}', '')
        self.module.call_watchdog('get')
        self.assertEqual(self.run.call_args.kwargs['timeout'], 1800)

    def test_select_denied_without_local_capability(self):
        with self.assertRaisesRegex(ValueError, 'XKEEN_ALLOW_APPLY'):
            self.module.call_watchdog('select', selection={'node': 'B', 'expected_current': 'A'})
        self.run.assert_not_called()

    def test_select_uses_json_stdin_and_fixed_command(self):
        os.environ['XKEEN_ALLOW_APPLY'] = '1'
        selection = {'node': 'B; $(do-not-run) "name"', 'expected_current': 'A'}
        self.run.return_value = subprocess.CompletedProcess([], 0, json.dumps(
            {'applied': True, 'selected_after': selection['node'], 'group': 'main'}), '')
        self.module.call_watchdog('select', selection=selection)
        self.assertEqual(self.run.call_args.args[0][-1], '/opt/bin/router-watchdog --select-node')
        self.assertEqual(json.loads(self.run.call_args.kwargs['input']), selection)

    def test_invalid_select_payload_never_starts_ssh(self):
        os.environ['XKEEN_ALLOW_APPLY'] = '1'
        for selection in (None, {}, {'node': 'B'}, {'node': '', 'expected_current': 'A'},
                          {'node': 'B', 'expected_current': 'A', 'extra': 1}):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                self.module.call_watchdog('select', selection=selection)
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

    def test_safe_router_error_is_reported_without_untrusted_message(self):
        self.run.return_value = subprocess.CompletedProcess([], 1, json.dumps(
            {'error': 'download_timeout', 'message': 'https://private/token'}), 'private-token')
        with self.assertRaisesRegex(RuntimeError, 'download_timeout') as raised:
            self.module.call_watchdog('find')
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
        changes = {'speed_test_provider': 'speedtest', 'target_group': 'group-$(do-not-run)', 'top_n': 3}
        self.run.return_value = subprocess.CompletedProcess([], 0,
            '{"updated_fields":["speed_test_provider","top_n"],"cron_sync_required":false}', '')
        result = self.module.call_watchdog('update', changes=changes)
        self.assertEqual(result['updated_fields'], ['speed_test_provider', 'top_n'])
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


class TestMCPChoice(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        spec = importlib.util.spec_from_file_location('xkeen_choice', SERVER)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.server = self.module.build_server()
        self.report = {'applied': False, 'group': 'main', 'current': {'node': 'A'},
                       'results': [{'node': 'A', 'mbps': 80}, {'node': 'B', 'mbps': 50}],
                       'failed_speed_nodes': ['C']}
        self.bridge = mock.patch.object(self.module, 'call_watchdog').start()
        self.addCleanup(mock.patch.stopall)
        self.bridge.return_value = self.report

    async def test_search_schema_has_no_apply(self):
        tools = {tool.name: tool for tool in await self.server.list_tools()}
        self.assertEqual(tools['find_faster_node'].inputSchema.get('properties', {}), {})
        self.assertIn('select_measured_node', tools)
        self.assertFalse(tools['find_faster_node'].annotations.destructiveHint)

    async def test_choice_requires_successful_comparison(self):
        for node in ('B', ''):
            with self.assertRaises(Exception):
                await self.server.call_tool('select_measured_node', {'node': node})
        self.bridge.assert_not_called()

    async def test_only_measured_nodes_and_one_selection(self):
        await self.server.call_tool('find_faster_node', {})
        self.bridge.assert_called_once_with('find')
        self.bridge.reset_mock()
        for node in ('C', 'unknown'):
            with self.assertRaises(Exception):
                await self.server.call_tool('select_measured_node', {'node': node})
        self.bridge.assert_not_called()
        self.bridge.return_value = {'applied': True, 'selected_after': 'B', 'group': 'main'}
        await self.server.call_tool('select_measured_node', {'node': 'B'})
        self.bridge.assert_called_once_with('select', selection={'node': 'B', 'expected_current': 'A'})
        self.bridge.reset_mock()
        with self.assertRaises(Exception):
            await self.server.call_tool('select_measured_node', {'node': 'A'})
        self.bridge.assert_not_called()

    async def test_failed_comparison_invalidates_previous_choices(self):
        await self.server.call_tool('find_faster_node', {})
        self.bridge.side_effect = RuntimeError('failed comparison')
        with self.assertRaises(Exception):
            await self.server.call_tool('find_faster_node', {})
        self.bridge.reset_mock()
        self.bridge.side_effect = None
        with self.assertRaises(Exception):
            await self.server.call_tool('select_measured_node', {'node': 'B'})
        self.bridge.assert_not_called()

    async def test_noncomparison_measure_does_not_enable_selection(self):
        await self.server.call_tool('measure_selected_node', {})
        self.bridge.reset_mock()
        with self.assertRaises(Exception):
            await self.server.call_tool('select_measured_node', {'node': 'A'})
        self.bridge.assert_not_called()

    async def test_malformed_comparison_cannot_authorize_selection(self):
        for rows in ([], [{'node': 'A', 'mbps': 0}], [{'node': 'B', 'mbps': 50}],
                     [{'node': 'A', 'mbps': float('nan')}], [{'node': 'A', 'mbps': True}]):
            self.bridge.return_value = {**self.report, 'results': rows}
            with self.subTest(rows=rows), self.assertRaises(Exception):
                await self.server.call_tool('find_faster_node', {})
            self.bridge.reset_mock()
            with self.assertRaises(Exception):
                await self.server.call_tool('select_measured_node', {'node': 'A'})
            self.bridge.assert_not_called()

    async def test_config_update_invalidates_comparison(self):
        await self.server.call_tool('find_faster_node', {})
        self.bridge.return_value = {'updated_fields': ['target_group'], 'cron_sync_required': False}
        await self.server.call_tool('update_watchdog_config', {'changes': {'target_group': 'other'}})
        self.bridge.reset_mock()
        with self.assertRaises(Exception):
            await self.server.call_tool('select_measured_node', {'node': 'B'})
        self.bridge.assert_not_called()
