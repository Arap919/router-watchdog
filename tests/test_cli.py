import importlib.util
import io
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "net"
    / "router-watchdog"
    / "files"
    / "opt"
    / "libexec"
    / "router-watchdog"
    / "router_watchdog.py"
)

spec = importlib.util.spec_from_file_location("router_watchdog", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
spec.loader.exec_module(module)


class TestRouterWatchdogCli(unittest.TestCase):
    def test_help_prints_usage_without_config(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            with mock.patch.object(sys, "argv", ["router-watchdog", "--help"]):
                exit_code = module.main()

        self.assertEqual(exit_code, 0)
        self.assertIn("usage:", stdout.getvalue().lower())


class TestCronSchedule(unittest.TestCase):
    def test_default_schedule_generates_native_cron_entries(self):
        entries = module.cron_entries(
            {
                "windows": [
                    {"start": "07:00", "end": "01:00", "every_minutes": 1},
                    {"start": "01:00", "end": "07:00", "every_minutes": 30},
                ]
            }
        )

        self.assertEqual(
            entries,
            [
                "* 0,7-23 * * * /opt/bin/router-watchdog",
                "0,30 1-6 * * * /opt/bin/router-watchdog",
            ],
        )

    def test_windows_cross_midnight_and_follow_start_relative_interval(self):
        entries = module.cron_entries(
            {
                "windows": [
                    {"start": "23:55", "end": "00:10", "every_minutes": 5}
                ]
            }
        )

        self.assertEqual(
            entries,
            [
                "0,5 0 * * * /opt/bin/router-watchdog",
                "55 23 * * * /opt/bin/router-watchdog",
            ],
        )

    def test_empty_windows_disable_schedule(self):
        self.assertEqual(module.cron_entries({"windows": []}), [])

    def test_matching_start_and_end_mean_all_day(self):
        self.assertEqual(
            module.cron_entries(
                {
                    "windows": [
                        {"start": "00:00", "end": "00:00", "every_minutes": 1}
                    ]
                }
            ),
            ["* * * * * /opt/bin/router-watchdog"],
        )

    def test_rejects_ambiguous_or_invalid_windows(self):
        invalid_schedules = [
            {"windows": [{"start": "7:00", "end": "08:00", "every_minutes": 1}]},
            {"windows": [{"start": "07:00", "end": "08:00", "every_minutes": True}]},
        ]

        for schedule in invalid_schedules:
            with self.subTest(schedule=schedule):
                with self.assertRaises(ValueError):
                    module.cron_entries(schedule)

    def test_updates_only_the_managed_crontab_block(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "root"
            original = "MAILTO=\"\"\n0 4 * * * /opt/bin/backup\n"
            path.write_text(original, encoding="utf-8")
            entries = ["*/5 7-23 * * * /opt/bin/router-watchdog"]

            self.assertTrue(module.update_managed_crontab(path, entries))
            updated = path.read_text(encoding="utf-8")
            self.assertTrue(updated.startswith(original))
            self.assertIn(entries[0], updated)
            self.assertFalse(module.update_managed_crontab(path, entries))
            self.assertTrue(module.update_managed_crontab(path, []))
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_sync_cron_command_uses_default_for_existing_config(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = pathlib.Path(directory) / "config.json"
            crontab_path = pathlib.Path(directory) / "crontabs" / "root"
            config_path.write_text('{"controller": "http://localhost:9090"}', encoding="utf-8")

            with (
                mock.patch.object(module, "CONFIG_PATH", config_path),
                mock.patch.object(module, "CRONTAB_PATH", crontab_path),
                mock.patch.object(sys, "argv", ["router-watchdog", "--sync-cron"]),
            ):
                self.assertEqual(module.main(), 0)

            self.assertIn(
                "0,30 1-6 * * * /opt/bin/router-watchdog",
                crontab_path.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
