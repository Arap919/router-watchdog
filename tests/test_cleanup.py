import json
import pathlib
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

from test_cli import module


class TestCleanup(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = pathlib.Path(directory.name)
        self.log = self.root / 'watchdog.log'
        self.log.write_text('existing log\n')
        self.state = self.root / 'watchdog.log.cleanup'
        self.config = self.root / 'config.json'
        self.config.write_text('{"log_cleanup_days": 3}')
        for key, value in [('LOG_PATH', self.log), ('LOCK_PATH', self.root / 'lock'),
                           ('CONFIG_PATH', self.config)]:
            patch = mock.patch.object(module, key, value)
            patch.start()
            self.addCleanup(patch.stop)

    def run_clear(self, now, due=True):
        argv = ['watchdog', '--clear-log'] + (['--if-due'] if due else [])
        with (mock.patch.object(module.sys, 'argv', argv),
              mock.patch.object(module.time, 'time', return_value=now)):
            return module.main()

    def test_first_daily_check_starts_interval_without_truncating(self):
        self.assertEqual(self.run_clear(1000000), 0)
        self.assertEqual(self.log.read_text(), 'existing log\n')
        self.assertEqual(float(self.state.read_text()), 1000000)

    def test_three_elapsed_days_across_month_boundary(self):
        start = datetime(2026, 10, 30, 6, 59, tzinfo=timezone.utc).timestamp()
        self.state.write_text(str(start))
        self.assertEqual(self.run_clear(start + 2 * 86400), 0)
        self.assertEqual(self.log.read_text(), 'existing log\n')
        self.assertEqual(self.run_clear(start + 3 * 86400), 0)
        self.assertEqual(self.log.read_text(), '')
        self.assertEqual(float(self.state.read_text()), start + 3 * 86400)

    def test_manual_clear_without_config_resets_interval(self):
        self.config.unlink()
        self.assertEqual(self.run_clear(1000000, due=False), 0)
        self.assertEqual(self.log.read_text(), '')
        self.assertEqual(float(self.state.read_text()), 1000000)

    def test_failed_truncation_does_not_advance_cleanup_state(self):
        self.state.write_text('1000000')
        with mock.patch.object(module, 'clear_log', side_effect=OSError('read only')):
            self.assertEqual(self.run_clear(2000000), 1)
        self.assertEqual(self.state.read_text(), '1000000')

    def test_invalid_interval_rejected_without_truncation(self):
        for invalid in [0, -1, True, '3', 1.5, None]:
            with self.subTest(interval=invalid):
                self.config.write_text(json.dumps({'log_cleanup_days': invalid}))
                self.assertEqual(self.run_clear(1000000), 1)
                self.assertIn('existing log', self.log.read_text())

    def test_daily_cleanup_uses_same_lock_as_watchdog(self):
        self.state.write_text('1000000')
        with module.LOCK_PATH.open('w') as lock:
            module.fcntl.flock(lock, module.fcntl.LOCK_EX | module.fcntl.LOCK_NB)
            self.assertEqual(self.run_clear(2000000), 0)
        self.assertIn('existing log', self.log.read_text())
        self.assertEqual(self.state.read_text(), '1000000')

    def test_corrupt_state_does_not_erase_log(self):
        self.state.write_text('not a timestamp')
        self.assertEqual(self.run_clear(1000000), 1)
        self.assertIn('existing log', self.log.read_text())

    def test_default_cleanup_interval_is_three_days(self):
        self.config.write_text('{}')
        self.state.write_text('1000000')
        self.assertEqual(self.run_clear(1000000 + 2 * 86400), 0)
        self.assertIn('existing log', self.log.read_text())
        self.assertEqual(self.run_clear(1000000 + 3 * 86400), 0)
        self.assertEqual(self.log.read_text(), '')


if __name__ == '__main__':
    unittest.main()
