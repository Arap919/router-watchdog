import io
import json
import tempfile
import pathlib
import unittest
from unittest import mock

from test_cli import module
from test_failover import Controller, DEFAULT_CONFIG


class TestManualSpeed(unittest.TestCase):
    def setUp(self):
        self.cfg = {**DEFAULT_CONFIG, 'target_group': 'main', 'healthcheck_parallelism': 1}
        self.client = Controller({'dead': 20, 'fast': 40, 'slow': 30})
        self.speeds = {'dead': 80, 'fast': 120, 'slow': 50}
        self.stack = __import__('contextlib').ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(module, 'log'))
        self.stack.enter_context(mock.patch.object(module, 'configured_providers', return_value=['Paper']))
        self.stack.enter_context(mock.patch.object(module, 'Mihomo', return_value=self.client))
        def measure(client, cfg, node):
            client.select('BENCHMARK', node)
            return self.speeds[node]
        self.measure = self.stack.enter_context(mock.patch.object(module, 'measure_speed', side_effect=measure))

    def run_speed(self, **kwargs):
        self.assertTrue(hasattr(module, 'manual_speed'), 'manual_speed operation must exist')
        return module.manual_speed(self.cfg, **kwargs)

    def test_measure_selected_uses_benchmark_without_main_switch(self):
        result = self.run_speed()
        self.assertEqual(result['current']['node'], 'dead')
        self.assertEqual(result['current']['mbps'], 80)
        self.assertEqual(result['current']['delay_ms'], 20)
        self.assertIn('measured_at', result)
        self.assertEqual(self.measure.call_count, 1)
        self.assertFalse(result['applied'])
        self.assertFalse(any(e[:2] == ('select', 'main') for e in self.client.events))

    def test_search_healthy_current_and_report_faster_without_apply(self):
        result = self.run_speed(find_faster=True)
        self.assertEqual(result['winner']['node'], 'fast')
        self.assertEqual(result['improvement_percent'], 50)
        self.assertEqual(self.client.selected['main'], 'dead')
        self.assertEqual(self.measure.call_count, 3)

    def test_apply_only_faster_and_verify_selection(self):
        result = self.run_speed(find_faster=True, apply=True)
        self.assertTrue(result['applied'])
        self.assertEqual(self.client.selected['main'], 'fast')

    def test_no_switch_to_slower_candidate_outside_baseline_latency_window(self):
        self.client.nodes = {'dead': 100, 'fast': 10}
        self.client.members = ['dead', 'fast']
        self.speeds['fast'] = 60
        result = self.run_speed(find_faster=True, apply=True)
        self.assertFalse(result['faster'])
        self.assertFalse(result['applied'])
        self.assertEqual(self.client.selected['main'], 'dead')

    def test_latency_window_excludes_fast_high_latency_node(self):
        self.client.nodes['fast'] = 71
        result = self.run_speed(find_faster=True, apply=True)
        self.assertEqual(result['winner']['node'], 'dead')
        self.assertFalse(result['applied'])

    def test_failed_baseline_never_switches(self):
        self.speeds['dead'] = float('nan')
        with self.assertRaisesRegex(RuntimeError, 'speed|throughput'):
            self.run_speed(find_faster=True, apply=True)
        self.assertEqual(self.client.selected['main'], 'dead')

    def test_failed_candidate_keeps_valid_results(self):
        self.speeds['fast'] = float('nan')
        result = self.run_speed(find_faster=True)
        self.assertEqual(result['winner']['node'], 'dead')

    def test_current_must_be_concrete_eligible_member(self):
        self.client.selected['main'] = 'nested-group'
        with self.assertRaisesRegex(RuntimeError, 'current|Current'):
            self.run_speed()
        self.measure.assert_not_called()

    def test_benchmark_membership_checked_before_download(self):
        original = self.client.proxy_group
        def groups(group):
            value = original(group)
            if group == 'BENCHMARK':
                value['all'] = ['fast']
            return value
        with mock.patch.object(self.client, 'proxy_group', side_effect=groups):
            with self.assertRaisesRegex(RuntimeError, 'benchmark_group'):
                self.run_speed()
        self.measure.assert_not_called()

    def test_external_selection_change_aborts_apply(self):
        original = self.measure.side_effect
        def measure(*args):
            value = original(*args)
            self.client.selected['main'] = 'slow'
            return value
        self.measure.side_effect = measure
        with self.assertRaisesRegex(RuntimeError, 'changed'):
            self.run_speed(find_faster=True, apply=True)
        self.assertEqual(self.client.selected['main'], 'slow')

    def test_initial_sync_precedes_checks_for_both_operations(self):
        for search in (False, True):
            with self.subTest(find_faster=search):
                self.client.selected['BENCHMARK'] = 'fast'
                self.client.events.clear()
                self.run_speed(find_faster=search)
                self.assertEqual(self.client.events[0], ('select', 'BENCHMARK', 'dead'))
                self.assertEqual(self.client.selected['main'], 'dead')

    def test_initial_sync_failure_stops_before_checks_and_measurements(self):
        self.client.selected['BENCHMARK'] = 'fast'
        with mock.patch.object(self.client, 'select', side_effect=RuntimeError('sync rejected')):
            with self.assertRaisesRegex(RuntimeError, 'sync rejected'):
                self.run_speed(find_faster=True)
        self.measure.assert_not_called()
        self.assertFalse(any(event[0] == 'check' for event in self.client.events))
        self.assertEqual(self.client.selected['main'], 'dead')

    def test_initial_sync_must_be_verified(self):
        self.client.selected['BENCHMARK'] = 'fast'
        with mock.patch.object(self.client, 'select'):
            with self.assertRaisesRegex(RuntimeError, 'synchroniz'):
                self.run_speed()
        self.measure.assert_not_called()
        self.assertFalse(any(event[0] == 'check' for event in self.client.events))

    def test_apply_requires_search(self):
        with self.assertRaises(ValueError):
            self.run_speed(apply=True)


class TestSelectNode(TestManualSpeed):
    def test_select_slower_without_download(self):
        result = module.select_node(self.cfg, 'slow', 'dead')
        self.assertEqual(result, {'group': 'main', 'applied': True, 'selected_after': 'slow'})
        self.assertEqual(self.client.events, [('check', 'slow'), ('select', 'main', 'slow')])
        self.measure.assert_not_called()

    def test_select_current_is_noop(self):
        result = module.select_node(self.cfg, 'dead', 'dead')
        self.assertFalse(result['applied'])
        self.assertEqual(result['selected_after'], 'dead')
        self.assertFalse(any(e[0] == 'select' for e in self.client.events))

    def test_changed_baseline_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'changed'):
            module.select_node(self.cfg, 'slow', 'fast')
        self.assertFalse(any(e[0] == 'select' for e in self.client.events))

    def test_missing_or_offline_node_rejected(self):
        for node in ('missing', 'slow'):
            self.client.nodes['slow'] = 0
            with self.subTest(node=node), self.assertRaises(RuntimeError):
                module.select_node(self.cfg, node, 'dead')
        self.assertEqual(self.client.selected['main'], 'dead')

    def test_change_during_check_rejected(self):
        original = self.client.provider_healthcheck
        def check(*args):
            self.client.selected['main'] = 'fast'
            return original(*args)
        with mock.patch.object(self.client, 'provider_healthcheck', side_effect=check):
            with self.assertRaisesRegex(RuntimeError, 'changed'):
                module.select_node(self.cfg, 'slow', 'dead')
        self.assertEqual(self.client.selected['main'], 'fast')

    def test_switch_verification_failure(self):
        with mock.patch.object(self.client, 'select'):
            with self.assertRaisesRegex(RuntimeError, 'verification'):
                module.select_node(self.cfg, 'slow', 'dead')

    def test_invalid_names_rejected_before_controller(self):
        for node in ('', None, 2):
            with self.subTest(node=node), mock.patch.object(module, 'Mihomo') as constructor:
                with self.assertRaises(ValueError):
                    module.select_node(self.cfg, node, 'dead')
                constructor.assert_not_called()


class TestManualCLI(unittest.TestCase):
    def invoke(self, args, busy=False, stdin=""):
        with tempfile.TemporaryDirectory() as folder:
            cfg = pathlib.Path(folder) / 'config.json'
            cfg.write_text(json.dumps({**DEFAULT_CONFIG, 'target_group': 'main'}))
            stdout, stderr = io.StringIO(), io.StringIO()
            operation = mock.Mock(return_value={'applied': False})
            with (mock.patch.object(module, 'CONFIG_PATH', cfg),
                  mock.patch.object(module, 'LOCK_PATH', pathlib.Path(folder) / 'lock'),
                  mock.patch.object(module, 'LOG_PATH', pathlib.Path(folder) / 'log'),
                  mock.patch.object(module, 'manual_speed', operation, create=True),
                  mock.patch.object(module, 'select_node', operation, create=True),
                  mock.patch('sys.stdin', io.StringIO(stdin)),
                  mock.patch.object(module.fcntl, 'flock', side_effect=BlockingIOError if busy else None),
                  mock.patch('sys.argv', ['router-watchdog', *args]),
                  mock.patch('sys.stdout', stdout), mock.patch('sys.stderr', stderr)):
                code = module.main()
            return code, stdout.getvalue(), operation

    def test_json_stdout_and_search_arguments(self):
        code, output, operation = self.invoke(['--find-faster', '--apply'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output), {'applied': False})
        self.assertEqual(operation.call_args.kwargs, {'find_faster': True, 'apply': True})

    def test_busy_is_json_error_and_does_not_run_operation(self):
        code, output, operation = self.invoke(['--measure-selected'], busy=True)
        self.assertNotEqual(code, 0)
        self.assertEqual(json.loads(output)['error'], 'busy')
        operation.assert_not_called()

    def test_select_cli_stdin_and_lock(self):
        code, output, operation = self.invoke(['--select-node'], stdin='{"node":"slow","expected_current":"dead"}')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output), {'applied': False})
        self.assertEqual(operation.call_args.args[1:], ('slow', 'dead'))
        code, output, operation = self.invoke(['--select-node'], busy=True)
        self.assertEqual(json.loads(output), {'error': 'busy'})
        operation.assert_not_called()

    def test_select_cli_invalid_stdin(self):
        for value in ('[]', '{}', '{"node":"slow","expected_current":"dead","extra":1}', 'x' * 65537):
            code, output, operation = self.invoke(['--select-node'], stdin=value)
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(output)['error'], 'operation_failed')
            operation.assert_not_called()

    def test_mcp_profile_overrides_only_measurement_copy(self):
        for action in ('--measure-selected', '--find-faster'):
            code, output, operation = self.invoke([action, '--mcp-speed-profile'])
            self.assertEqual(code, 0)
            cfg = operation.call_args.args[0]
            self.assertEqual((cfg['download_bytes'], cfg['parallel_streams'], cfg['multi_rounds']),
                             (10000000, 4, 1))
        code, output, operation = self.invoke(['--find-faster'])
        cfg = operation.call_args.args[0]
        self.assertEqual((cfg['download_bytes'], cfg['parallel_streams'], cfg['multi_rounds']),
                         (25000000, 4, 2))

    def test_mcp_profile_rejects_unrelated_actions_and_apply(self):
        for args in (['--mcp-speed-profile'], ['--get-config', '--mcp-speed-profile'],
                     ['--find-faster', '--apply', '--mcp-speed-profile']):
            with self.subTest(args=args), self.assertRaises(SystemExit) as raised:
                self.invoke(args)
            self.assertEqual(raised.exception.code, 2)
