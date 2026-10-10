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


class TestProviderResolution(unittest.TestCase):
    def test_refresh_skips_provider_after_retries_and_keeps_successful_provider(self):
        class Client:
            def __init__(self):
                self.attempts = {}

            def update_provider(self, provider):
                self.attempts[provider] = self.attempts.get(provider, 0) + 1
                if provider == "Paper-запасной-ключ":
                    raise RuntimeError("temporary provider download failure")

        client = Client()
        with tempfile.TemporaryDirectory() as directory:
            stdout = io.StringIO()
            with (
                mock.patch.object(module, "LOG_PATH", pathlib.Path(directory) / "watchdog.log"),
                mock.patch.object(module.time, "sleep"),
                redirect_stdout(stdout),
            ):
                refreshed = module.refresh(
                    client, ["BlancVPN", "Paper-запасной-ключ"]
                )

        self.assertEqual(refreshed, ["BlancVPN"])
        self.assertEqual(client.attempts["BlancVPN"], 1)
        self.assertEqual(client.attempts["Paper-запасной-ключ"], 5)
        self.assertIn(
            "Skipping provider Paper-запасной-ключ after 5 refresh attempts",
            stdout.getvalue(),
        )

    def test_refresh_fails_if_no_provider_was_refreshed(self):
        class Client:
            def update_provider(self, provider):
                raise RuntimeError("provider unavailable")

        with tempfile.TemporaryDirectory() as directory:
            with (
                mock.patch.object(module, "LOG_PATH", pathlib.Path(directory) / "watchdog.log"),
                mock.patch.object(module.time, "sleep"),
                self.assertRaisesRegex(
                    RuntimeError, "Failed to refresh any proxy provider"
                ),
            ):
                module.refresh(Client(), ["Paper-запасной-ключ"])

    def test_resolve_provider_uses_provider_list_when_proxy_endpoint_returns_404(self):
        class Client:
            def proxy(self, node):
                raise module.MihomoAPIError(404, "Resource not found")

            def providers_for_nodes(self, nodes):
                self.nodes = nodes
                return {"🇩🇪 Берлин, Германия, Extra": "BlancVPN"}

        client = Client()
        self.assertEqual(
            module.resolve_provider(client, "🇩🇪 Берлин, Германия, Extra"),
            "BlancVPN",
        )
        self.assertEqual(client.nodes, {"🇩🇪 Берлин, Германия, Extra"})

    def test_resolve_provider_does_not_hide_non_404_errors(self):
        class Client:
            def proxy(self, node):
                raise module.MihomoAPIError(503, "Unavailable")

        with self.assertRaisesRegex(module.MihomoAPIError, "HTTP 503"):
            module.resolve_provider(Client(), "node")

    def test_providers_for_nodes_scans_provider_data_and_caches_results(self):
        with tempfile.TemporaryDirectory() as directory:
            responses = {
                "/providers/proxies": {
                    "providers": {"Unused": {}, "BlancVPN": {}, "Other": {}}
                },
                "/providers/proxies/Unused": {"proxies": [{"name": "unrelated"}]},
                "/providers/proxies/BlancVPN": {
                    "proxies": [{"name": "🇩🇪 Берлин, Германия, Extra"}]
                },
            }
            with mock.patch.object(
                module, "LOG_PATH", pathlib.Path(directory) / "watchdog.log"
            ):
                client = module.Mihomo("http://localhost:9090")
            with mock.patch.object(
                client, "request", side_effect=lambda method, path: responses[path]
            ) as request:
                resolved = client.providers_for_nodes(
                    {"🇩🇪 Берлин, Германия, Extra"}
                )
                self.assertEqual(
                    client.providers_for_nodes({"🇩🇪 Берлин, Германия, Extra"}),
                    resolved,
                )

        self.assertEqual(resolved, {"🇩🇪 Берлин, Германия, Extra": "BlancVPN"})
        self.assertEqual(request.call_count, 3)

    def test_refresh_invalidates_cached_provider_details(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(
                module, "LOG_PATH", pathlib.Path(directory) / "watchdog.log"
            ):
                client = module.Mihomo("http://localhost:9090")
            client._provider_cache["BlancVPN"] = {"proxies": []}
            with mock.patch.object(client, "request") as request:
                client.update_provider("BlancVPN")

        self.assertNotIn("BlancVPN", client._provider_cache)
        request.assert_called_once_with(
            "PUT", "/providers/proxies/BlancVPN", timeout=30
        )

    def test_target_group_resolves_provider_nodes_from_provider_data(self):
        class Client:
            def proxy_group(self, group):
                return {"all": ["node-a", "node-b"]}

            def proxy(self, node):
                raise AssertionError("provider resolution should not query proxies")

            def providers_for_nodes(self, nodes):
                self.nodes = nodes
                return {"node-a": "BlancVPN", "node-b": "BlancVPN"}

        client = Client()
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(
                module, "LOG_PATH", pathlib.Path(directory) / "watchdog.log"
            ):
                providers = module.providers_from_target_group(client, "selector")
        self.assertEqual(providers, ["BlancVPN"])
        self.assertEqual(client.nodes, {"node-a", "node-b"})

    def test_target_group_logs_nodes_missing_from_all_providers(self):
        class Client:
            def proxy_group(self, group):
                return {"all": ["node-a", "node-b"]}

            def providers_for_nodes(self, nodes):
                return {"node-a": "BlancVPN"}

        client = Client()
        with tempfile.TemporaryDirectory() as directory:
            stdout = io.StringIO()
            with (
                mock.patch.object(module, "LOG_PATH", pathlib.Path(directory) / "watchdog.log"),
                redirect_stdout(stdout),
            ):
                providers = module.providers_from_target_group(client, "selector")

        self.assertEqual(providers, ["BlancVPN"])
        self.assertIn("not found in any proxy provider: node-b", stdout.getvalue())


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
                "* 0,7-23 * * * root /opt/bin/flock -n /tmp/router_watchdog.lock /opt/bin/router-watchdog",
                "0,30 1-6 * * * root /opt/bin/flock -n /tmp/router_watchdog.lock /opt/bin/router-watchdog",
                "59 6 * * 0 root /opt/bin/router-watchdog --clear-log",
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
                "0,5 0 * * * root /opt/bin/flock -n /tmp/router_watchdog.lock /opt/bin/router-watchdog",
                "55 23 * * * root /opt/bin/flock -n /tmp/router_watchdog.lock /opt/bin/router-watchdog",
                "59 6 * * 0 root /opt/bin/router-watchdog --clear-log",
            ],
        )

    def test_empty_windows_disable_schedule(self):
        self.assertEqual(
            module.cron_entries({"windows": []}),
            ["59 6 * * 0 root /opt/bin/router-watchdog --clear-log"],
        )

    def test_scheduled_watchdog_entries_use_nonblocking_flock(self):
        entries = module.cron_entries(
            {
                "windows": [
                    {"start": "07:00", "end": "08:00", "every_minutes": 5}
                ]
            }
        )

        self.assertTrue(entries)
        self.assertTrue(
            all(
                " root /opt/bin/flock -n /tmp/router_watchdog.lock "
                "/opt/bin/router-watchdog" in entry
                for entry in entries
                if "--clear-log" not in entry
            )
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
                "* * * * * root /opt/bin/flock -n /tmp/router_watchdog.lock /opt/bin/router-watchdog",
                "59 6 * * 0 root /opt/bin/router-watchdog --clear-log",
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

    def test_sync_cron_uses_system_crontab_and_removes_old_watchdog_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = pathlib.Path(directory) / "config.json"
            crontab_path = pathlib.Path(directory) / "etc" / "crontab"
            legacy_crontab_path = pathlib.Path(directory) / "spool" / "root"
            old_legacy_crontab_path = pathlib.Path(directory) / "old-etc" / "root"
            log_path = pathlib.Path(directory) / "watchdog.log"
            config_path.write_text('{"controller": "http://localhost:9090"}', encoding="utf-8")
            crontab_path.parent.mkdir()
            crontab_path.write_text(
                'MAILTO=""\n'
                "*/1 * * * * root /opt/bin/run-parts /opt/etc/cron.1min\n"
                "* 7-23 * * * root /opt/bin/flock -n /tmp/router_watchdog.lock "
                "/opt/bin/python3 /opt/libexec/router-watchdog/router_watchdog.py "
                ">> /opt/share/router-watchdog.log 2>&1\n",
                encoding="utf-8",
            )
            legacy_crontab_path.parent.mkdir()
            legacy_crontab_path.write_text(
                f'MAILTO=""\n{module.CRON_BEGIN}\n'
                "* * * * * /opt/bin/router-watchdog\n"
                f"{module.CRON_END}\n0 4 * * * /opt/bin/backup\n",
                encoding="utf-8",
            )
            old_legacy_crontab_path.parent.mkdir()
            old_legacy_crontab_path.write_text(
                "0 4 * * * /opt/bin/backup\n", encoding="utf-8"
            )

            with (
                mock.patch.object(module, "CONFIG_PATH", config_path),
                mock.patch.object(module, "DEFAULT_CRONTAB_PATH", crontab_path),
                mock.patch.object(module, "LEGACY_CRONTAB_PATH", legacy_crontab_path),
                mock.patch.object(
                    module, "OLD_LEGACY_CRONTAB_PATH", old_legacy_crontab_path
                ),
                mock.patch.object(module, "CRONTAB_PATH", crontab_path),
                mock.patch.object(module, "CRON_INIT_SCRIPT", pathlib.Path("/mock/S10cron")),
                mock.patch.object(module.subprocess, "run") as restart_cron,
                mock.patch.object(module, "LOG_PATH", log_path),
                mock.patch.object(sys, "argv", ["router-watchdog", "--sync-cron"]),
            ):
                self.assertEqual(module.main(), 0)
                self.assertEqual(module.main(), 0)

            self.assertIn(
                "0,30 1-6 * * * root /opt/bin/flock -n /tmp/router_watchdog.lock "
                "/opt/bin/router-watchdog",
                crontab_path.read_text(encoding="utf-8"),
            )
            self.assertIn("/opt/bin/run-parts /opt/etc/cron.1min", crontab_path.read_text())
            self.assertNotIn("router_watchdog.py", crontab_path.read_text())
            restart_cron.assert_called_once_with(
                ["/mock/S10cron", "restart"], check=True
            )
            legacy_crontab = legacy_crontab_path.read_text(encoding="utf-8")
            self.assertNotIn(module.CRON_BEGIN, legacy_crontab)
            self.assertIn('MAILTO=""', legacy_crontab)
            self.assertIn("0 4 * * * /opt/bin/backup", legacy_crontab)
            self.assertEqual(
                old_legacy_crontab_path.read_text(encoding="utf-8"),
                "0 4 * * * /opt/bin/backup\n",
            )

    def test_remove_cron_command_cleans_active_and_legacy_crontabs(self):
        with tempfile.TemporaryDirectory() as directory:
            active_crontab = pathlib.Path(directory) / "spool" / "root"
            legacy_crontab = pathlib.Path(directory) / "etc" / "root"
            old_legacy_crontab = pathlib.Path(directory) / "old-etc" / "root"
            log_path = pathlib.Path(directory) / "watchdog.log"
            managed_block = (
                f"{module.CRON_BEGIN}\n"
                "* * * * * root /opt/bin/router-watchdog\n"
                f"{module.CRON_END}\n"
            )
            for path in (active_crontab, legacy_crontab, old_legacy_crontab):
                path.parent.mkdir()
                path.write_text(
                    "0 4 * * * /opt/bin/backup\n"
                    + "* * * * * root /opt/bin/router-watchdog\n"
                    + managed_block,
                    encoding="utf-8",
                )

            with (
                mock.patch.object(module, "DEFAULT_CRONTAB_PATH", active_crontab),
                mock.patch.object(module, "LEGACY_CRONTAB_PATH", legacy_crontab),
                mock.patch.object(
                    module, "OLD_LEGACY_CRONTAB_PATH", old_legacy_crontab
                ),
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
            for path in (active_crontab, legacy_crontab, old_legacy_crontab):
                content = path.read_text(encoding="utf-8")
                self.assertNotIn(module.CRON_BEGIN, content)
                self.assertNotIn("/opt/bin/router-watchdog", content)
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

            self.assertIn("Failed to synchronize cron schedule:", stdout.getvalue())
            self.assertIn("restart", stdout.getvalue())

    def test_watchdog_lock_is_removed_after_run_and_skips_existing_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = pathlib.Path(directory) / "config.json"
            lock_path = pathlib.Path(directory) / "router-watchdog.lock"
            log_path = pathlib.Path(directory) / "watchdog.log"
            config_path.write_text("{}", encoding="utf-8")
            stdout = io.StringIO()

            with (
                mock.patch.object(module, "CONFIG_PATH", config_path),
                mock.patch.object(module, "LOCK_PATH", lock_path),
                mock.patch.object(module, "LOG_PATH", log_path),
                mock.patch.object(module, "choose_and_apply") as choose,
                mock.patch.object(sys, "argv", ["router-watchdog"]),
                redirect_stdout(stdout),
            ):
                choose.side_effect = lambda _cfg: self.assertTrue(lock_path.exists())
                self.assertEqual(module.main(), 0)
                self.assertFalse(lock_path.exists())

                lock_path.touch()
                self.assertEqual(module.main(), 0)

            choose.assert_called_once_with({})
            self.assertIn("Previous run is still in progress; skipping.", stdout.getvalue())
            self.assertIn(
                "Previous run is still in progress; skipping.",
                log_path.read_text(encoding="utf-8"),
            )

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
