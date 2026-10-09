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
                "59 6 * * 0 /opt/bin/router-watchdog --clear-log",
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
                "59 6 * * 0 /opt/bin/router-watchdog --clear-log",
            ],
        )

    def test_empty_windows_disable_schedule(self):
        self.assertEqual(
            module.cron_entries({"windows": []}),
            ["59 6 * * 0 /opt/bin/router-watchdog --clear-log"],
        )

    def test_matching_start_and_end_mean_all_day(self):
        self.assertEqual(
            module.cron_entries(
                {
                    "windows": [
                        {"start": "00:00", "end": "00:00", "every_minutes": 1}
                    ]
                }
            ),
            [
                "* * * * * /opt/bin/router-watchdog",
                "59 6 * * 0 /opt/bin/router-watchdog --clear-log",
            ],
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
            legacy_crontab_path = pathlib.Path(directory) / "etc-crontabs" / "root"
            log_path = pathlib.Path(directory) / "watchdog.log"
            config_path.write_text('{"controller": "http://localhost:9090"}', encoding="utf-8")
            legacy_crontab_path.parent.mkdir()
            legacy_crontab_path.write_text(
                f'MAILTO=""\n{module.CRON_BEGIN}\n'
                "* * * * * /opt/bin/router-watchdog\n"
                f"{module.CRON_END}\n0 4 * * * /opt/bin/backup\n",
                encoding="utf-8",
            )

            with (
                mock.patch.object(module, "CONFIG_PATH", config_path),
                mock.patch.object(module, "DEFAULT_CRONTAB_PATH", crontab_path),
                mock.patch.object(module, "LEGACY_CRONTAB_PATH", legacy_crontab_path),
                mock.patch.object(module, "CRONTAB_PATH", crontab_path),
                mock.patch.object(module, "CRON_INIT_SCRIPT", pathlib.Path("/mock/S10cron")),
                mock.patch.object(module.subprocess, "run") as restart_cron,
                mock.patch.object(module, "LOG_PATH", log_path),
                mock.patch.object(sys, "argv", ["router-watchdog", "--sync-cron"]),
            ):
                self.assertEqual(module.main(), 0)
                self.assertEqual(module.main(), 0)

            self.assertIn(
                "0,30 1-6 * * * /opt/bin/router-watchdog",
                crontab_path.read_text(encoding="utf-8"),
            )
            restart_cron.assert_called_once_with(
                ["/mock/S10cron", "restart"], check=True
            )
            legacy_crontab = legacy_crontab_path.read_text(encoding="utf-8")
            self.assertNotIn(module.CRON_BEGIN, legacy_crontab)
            self.assertIn('MAILTO=""', legacy_crontab)
            self.assertIn("0 4 * * * /opt/bin/backup", legacy_crontab)

    def test_remove_cron_command_cleans_active_and_legacy_crontabs(self):
        with tempfile.TemporaryDirectory() as directory:
            active_crontab = pathlib.Path(directory) / "spool" / "root"
            legacy_crontab = pathlib.Path(directory) / "etc" / "root"
            log_path = pathlib.Path(directory) / "watchdog.log"
            managed_block = (
                f"{module.CRON_BEGIN}\n"
                "* * * * * /opt/bin/router-watchdog\n"
                f"{module.CRON_END}\n"
            )
            for path in (active_crontab, legacy_crontab):
                path.parent.mkdir()
                path.write_text(
                    "0 4 * * * /opt/bin/backup\n" + managed_block,
                    encoding="utf-8",
                )

            with (
                mock.patch.object(module, "DEFAULT_CRONTAB_PATH", active_crontab),
                mock.patch.object(module, "LEGACY_CRONTAB_PATH", legacy_crontab),
                mock.patch.object(module, "CRONTAB_PATH", active_crontab),
                mock.patch.object(module, "CRON_INIT_SCRIPT", pathlib.Path("/mock/S10cron")),
                mock.patch.object(module.subprocess, "run") as restart_cron,
                mock.patch.object(module, "LOG_PATH", log_path),
                mock.patch.object(sys, "argv", ["router-watchdog", "--remove-cron"]),
            ):
                self.assertEqual(module.main(), 0)

            restart_cron.assert_called_once_with(
                ["/mock/S10cron", "restart"], check=True
            )
            for path in (active_crontab, legacy_crontab):
                content = path.read_text(encoding="utf-8")
                self.assertNotIn(module.CRON_BEGIN, content)
                self.assertIn("0 4 * * * /opt/bin/backup", content)

    def test_sync_cron_reports_service_restart_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = pathlib.Path(directory) / "config.json"
            crontab_path = pathlib.Path(directory) / "spool" / "root"
            log_path = pathlib.Path(directory) / "watchdog.log"
            stdout = io.StringIO()
            config_path.write_text(
                '{"controller": "http://localhost:9090"}', encoding="utf-8"
            )

            with (
                mock.patch.object(module, "CONFIG_PATH", config_path),
                mock.patch.object(module, "DEFAULT_CRONTAB_PATH", crontab_path),
                mock.patch.object(module, "CRONTAB_PATH", crontab_path),
                mock.patch.object(
                    module, "CRON_INIT_SCRIPT", pathlib.Path("/mock/S10cron")
                ),
                mock.patch.object(
                    module.subprocess,
                    "run",
                    side_effect=module.subprocess.CalledProcessError(
                        1, ["/mock/S10cron", "restart"]
                    ),
                ),
                mock.patch.object(module, "LOG_PATH", log_path),
                mock.patch.object(sys, "argv", ["router-watchdog", "--sync-cron"]),
                redirect_stdout(stdout),
            ):
                self.assertEqual(module.main(), 1)

            self.assertIn("Error:", stdout.getvalue())
            self.assertIn("restart", stdout.getvalue())

    def test_log_appends_timestamped_messages_to_file(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = pathlib.Path(directory) / "logs" / "watchdog.log"
            stdout = io.StringIO()

            with mock.patch.object(module, "LOG_PATH", log_path):
                with redirect_stdout(stdout):
                    module.log("test message")

            self.assertIn("test message", stdout.getvalue())
            self.assertIn("test message", log_path.read_text(encoding="utf-8"))
            self.assertRegex(log_path.read_text(encoding="utf-8"), r"^\d{4}-\d{2}-\d{2}")

    def test_weekly_clear_command_truncates_log(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = pathlib.Path(directory) / "logs" / "watchdog.log"
            log_path.parent.mkdir()
            log_path.write_text("old log entry\n", encoding="utf-8")
            stdout = io.StringIO()

            with (
                mock.patch.object(module, "LOG_PATH", log_path),
                mock.patch.object(sys, "argv", ["router-watchdog", "--clear-log"]),
                redirect_stdout(stdout),
            ):
                self.assertEqual(module.main(), 0)

            self.assertEqual(log_path.read_text(encoding="utf-8"), "")
            self.assertIn("Cleared log file", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
