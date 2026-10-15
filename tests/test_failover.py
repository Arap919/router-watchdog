import json
import io
import math
import pathlib
import tempfile
import unittest
from unittest import mock

from test_cli import module


DEFAULT_CONFIG = json.loads(
    (pathlib.Path(__file__).resolve().parents[1]
     / 'net/router-watchdog/files/opt/etc/router-watchdog.json').read_text()
)


class Controller:
    """Stateful controller boundary: production selectors and provider histories."""

    def __init__(self, nodes, members=None, histories=None):
        self.events = []
        self.selected = {'main': 'dead', 'BENCHMARK': 'dead'}
        self.members = members or list(nodes)
        self.nodes = nodes
        self.histories = histories or {name: delay for name, delay in nodes.items()}
        self.after_refresh = None
        self.update_errors = set()
        self._provider_cache = {}
        self._provider_names = None

    def proxy_group(self, group):
        return {'type': 'Selector', 'now': self.selected[group],
                'all': list(self.nodes) if group == 'BENCHMARK' else self.members}

    def proxy(self, node):
        return {'provider-name': 'Paper'}

    def provider_names(self):
        return ['Paper', 'unused']

    def provider(self, name):
        return {'testUrl': 'https://example.com/check', 'expectedStatus': 204,
                'proxies': [] if name == 'unused' else [
                    {'name': node, 'alive': bool(delay),
                     'history': [{'delay': self.histories.get(node, 0)}]}
                    for node, delay in self.nodes.items()]}

    def providers_for_nodes(self, nodes):
        return {node: 'Paper' for node in nodes if node in self.nodes}

    def provider_healthcheck(self, provider, node, url, timeout, expected):
        self.events.append(('check', node))
        delay = self.nodes[node]
        if not delay:
            raise RuntimeError('offline')
        return delay

    def select(self, group, node, timeout=5):
        if node not in self.proxy_group(group)['all']:
            raise RuntimeError('not a group member')
        self.events.append(('select', group, node))
        self.selected[group] = node

    def update_provider(self, provider):
        self.events.append(('refresh', provider))
        if provider in self.update_errors:
            raise RuntimeError('update failed')
        if self.after_refresh:
            self.after_refresh(self)


class TestFailover(unittest.TestCase):
    def setUp(self):
        self.cfg = {**DEFAULT_CONFIG, 'target_group': 'main',
                    'benchmark_group': 'BENCHMARK', 'switch_wait_seconds': 0,
                    'parallel_streams': 1, 'multi_rounds': 1,
                    'healthcheck_parallelism': 1}
        self.log = mock.patch.object(module, 'log').start()
        self.addCleanup(mock.patch.stopall)

    def run_watchdog(self, client, speeds=None):
        speeds = speeds or {}

        def download(proxy, size, timeout):
            node = client.selected['BENCHMARK']
            client.events.append(('download', node, client.selected['main']))
            speed = speeds.get(node, 10)
            if isinstance(speed, Exception):
                raise speed
            return size

        # Keep selection/ranking/checks real; replace only external downloads/timing.
        with (mock.patch.object(module, 'Mihomo', return_value=client),
              mock.patch.object(module, 'download', side_effect=download),
              mock.patch.object(module.time, 'sleep'),
              mock.patch.object(module.time, 'monotonic', side_effect=range(1000))):
            module.choose_and_apply(self.cfg)

    def test_healthy_current_exits_without_refresh_or_selection(self):
        client = Controller({'dead': 10, 'a': 20})
        self.run_watchdog(client)
        self.assertEqual(client.events, [('check', 'dead')])

    def test_fallback_precedes_isolated_measurements_without_refresh(self):
        client = Controller({'dead': 0, 'a': 20, 'b': 30})
        self.run_watchdog(client)
        downloads = [event for event in client.events if event[0] == 'download']
        self.assertEqual(downloads, [('download', 'a', 'a'), ('download', 'b', 'a')])
        self.assertNotIn(('refresh', 'Paper'), client.events)
        self.assertLess(client.events.index(('select', 'main', 'a')),
                        client.events.index(downloads[0]))
        self.assertEqual(client.selected['main'], 'a')

    def test_only_target_members_and_allowed_names_can_be_selected(self):
        client = Controller({'dead': 0, 'outside': 1, 'Россия 1': 2,
                             'Украина 1': 3, 'a': 50},
                            members=['dead', 'Россия 1', 'Украина 1', 'a'])
        self.run_watchdog(client)
        self.assertEqual(client.selected['main'], 'a')
        checked = [event[1] for event in client.events if event[0] == 'check']
        self.assertNotIn('outside', checked)
        self.assertNotIn('Россия 1', checked)
        self.assertNotIn('Украина 1', checked)

    def test_zero_history_restores_service_then_refreshes_all_providers(self):
        client = Controller({'dead': 0, 'a': 25}, histories={'dead': 0, 'a': 0})
        client.after_refresh = lambda c: c.histories.update(a=25)
        self.run_watchdog(client)
        self.assertLess(client.events.index(('select', 'main', 'a')),
                        client.events.index(('refresh', 'Paper')))
        self.assertIn(('refresh', 'unused'), client.events)
        self.assertEqual(client.selected['main'], 'a')

    def test_failed_shortlist_refreshes_and_rereads_membership(self):
        self.cfg['top_n'] = 1
        client = Controller({'dead': 0, 'old': 0, 'fallback': 100},
                            histories={'dead': 0, 'old': 1, 'fallback': 100})

        def changed(c):
            c.nodes = {'dead': 0, 'new': 20}
            c.histories = {'dead': 0, 'new': 20}
            c.members = ['dead', 'new']

        client.after_refresh = changed
        self.run_watchdog(client)
        self.assertEqual(client.selected['main'], 'new')
        self.assertIn(('download', 'new', 'new'), client.events)

    def test_all_speed_failures_retry_once_and_preserve_working_fallback(self):
        client = Controller({'dead': 0, 'a': 25})
        with self.assertRaisesRegex(RuntimeError, 'speed|Speed'):
            self.run_watchdog(client, {'a': RuntimeError('download failed')})
        self.assertEqual(client.selected['main'], 'a')
        self.assertEqual(client.events.count(('refresh', 'Paper')), 1)
        self.assertEqual(client.events.count(('refresh', 'unused')), 1)
        self.assertEqual(len([e for e in client.events if e[0] == 'download']), 2)

    def test_all_offline_after_refresh_is_error_without_selection(self):
        client = Controller({'dead': 0, 'a': 0})
        with self.assertRaisesRegex(RuntimeError, 'available|working'):
            self.run_watchdog(client)
        self.assertFalse(any(e[0] == 'select' for e in client.events))
        self.assertIn(('refresh', 'Paper'), client.events)

    def test_partial_refresh_failure_still_checks_working_nodes(self):
        client = Controller({'dead': 0, 'a': 20}, histories={'dead': 0, 'a': 0})
        client.update_errors.add('unused')
        self.run_watchdog(client)
        self.assertEqual(client.selected['main'], 'a')
        self.assertIn(('download', 'a', 'a'), client.events)

    def test_current_provider_resolution_failure_still_restores_service(self):
        client = Controller({'dead': 0, 'a': 20})
        with mock.patch.object(client, 'proxy', side_effect=RuntimeError('missing current')):
            self.run_watchdog(client)
        self.assertEqual(client.selected['main'], 'a')

    def test_failed_emergency_switch_does_not_start_measurements(self):
        client = Controller({'dead': 0, 'a': 20})
        with mock.patch.object(client, 'select', side_effect=RuntimeError('switch rejected')):
            with self.assertRaisesRegex(RuntimeError, 'switch rejected'):
                self.run_watchdog(client)
        self.assertFalse(any(e[0] == 'download' for e in client.events))

    def test_identical_benchmark_and_target_rejected_before_controller_access(self):
        self.cfg['benchmark_group'] = 'main'
        with mock.patch.object(module, 'Mihomo') as constructor:
            with self.assertRaises(ValueError):
                module.choose_and_apply(self.cfg)
        constructor.assert_not_called()

    def test_all_top_n_survivors_are_measured_despite_legacy_fresh_top_n(self):
        self.cfg['fresh_top_n'] = 1
        client = Controller({'dead': 0, 'a': 20, 'b': 30})
        self.run_watchdog(client)
        self.assertEqual([e[1] for e in client.events if e[0] == 'download'], ['a', 'b'])

    def test_speed_failure_can_recover_after_provider_update(self):
        client = Controller({'dead': 0, 'a': 20})
        failures = {'a': RuntimeError('temporary download failure')}
        client.after_refresh = lambda c: failures.clear()
        # Pass the mutable mapping through the actual benchmark stage.
        self.run_watchdog(client, failures)
        self.assertEqual(client.events.count(('refresh', 'Paper')), 1)
        self.assertEqual(client.selected['main'], 'a')

    def test_fallback_works_when_alive_flag_is_stale(self):
        client = Controller({'dead': 0, 'a': 20})
        original = client.provider

        def stale(provider):
            data = original(provider)
            for item in data['proxies']:
                item['alive'] = False
            return data

        with mock.patch.object(client, 'provider', side_effect=stale):
            self.run_watchdog(client)
        self.assertNotIn(('refresh', 'Paper'), client.events)
        self.assertIn(('download', 'a', 'a'), client.events)

    def test_candidate_missing_from_benchmark_is_never_tested_via_main(self):
        client = Controller({'dead': 0, 'a': 20})
        original = client.proxy_group

        def groups(group):
            result = original(group)
            if group == 'BENCHMARK':
                result['all'] = ['dead']
            return result

        with mock.patch.object(client, 'proxy_group', side_effect=groups):
            with self.assertRaisesRegex(RuntimeError, 'speed|Speed'):
                self.run_watchdog(client)
        self.assertEqual(client.selected['main'], 'a')
        self.assertFalse(any(e[0] == 'download' for e in client.events))

    def test_invalid_config_rejected_before_controller_and_switches(self):
        cases = [('top_n', True), ('parallel_streams', 0),
                 ('switch_wait_seconds', math.nan), ('target_group', ''),
                 ('benchmark_proxy', 'socks5://127.0.0.1:17890'),
                 ('controller', 'http://user:password@127.0.0.1:9090'),
                 ('log_cleanup_days', 0)]
        for key, value in cases:
            with self.subTest(key=key), mock.patch.object(module, 'Mihomo') as constructor:
                cfg = {**self.cfg, key: value}
                with self.assertRaises(ValueError):
                    module.choose_and_apply(cfg)
                constructor.assert_not_called()

    def test_winner_uses_speed_inside_inclusive_50ms_latency_window(self):
        cases = [
            ([('a', 30, 80), ('b', 80, 120)], 'b'),
            ([('a', 30, 80), ('b', 81, 120)], 'a'),
            ([('a', 30, 80), ('b', 50, 80)], 'a'),
            ([('c', 90, 500), ('b', 50, 90), ('a', 10, 80)], 'b'),
        ]
        for results, expected in cases:
            with self.subTest(results=results):
                self.assertEqual(module.choose_winner(results)[0], expected)

    def test_winner_rejects_invalid_speed_results(self):
        for speed in (0, -1, math.nan, math.inf):
            with self.subTest(speed=speed):
                with self.assertRaises(RuntimeError):
                    module.choose_winner([('a', 10, speed)])

    def test_api_errors_do_not_expose_subscription_response_body(self):
        client = module.Mihomo('http://localhost:9090')
        error = module.urllib.error.HTTPError(
            'http://localhost:9090/providers/proxies/Paper', 500, 'Internal Server Error',
            {}, io.BytesIO(b'provider failed: https://private.example/sub?token=secret-value'))
        with mock.patch.object(client.opener, 'open', side_effect=error):
            with self.assertRaises(module.MihomoAPIError) as raised:
                client.update_provider('Paper')
        self.assertNotIn('secret-value', str(raised.exception))
        self.assertNotIn('private.example', str(raised.exception))


if __name__ == '__main__':
    unittest.main()
