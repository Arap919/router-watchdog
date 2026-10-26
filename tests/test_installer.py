import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class TestInstaller(unittest.TestCase):
    def test_installer_is_idempotent_and_preserves_other_feeds(self):
        script = ROOT / 'install.sh'
        self.assertTrue(script.exists(), 'install.sh must exist')
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            config = root/'opkg.conf'
            config.write_text('src/gz original http://example.com/feed\n')
            config.chmod(0o600)
            log = root/'calls'
            opkg = root/'opkg'
            opkg.write_text('#!/bin/sh\nprintf "%s\n" "$*" >> "$TEST_CALLS"\n'
                            'if [ "$1" = status ]; then exit 0; fi\nexit 0\n')
            opkg.chmod(0o755)
            env = {**os.environ, 'PATH': folder+os.pathsep+os.environ['PATH'],
                   'ROUTER_WATCHDOG_OPKG_CONF':str(config), 'TEST_CALLS':str(log)}
            for _ in range(2):
                run = subprocess.run(['sh',str(script)],env=env,capture_output=True,text=True)
                self.assertEqual(run.returncode,0,run.stderr)
            contents = config.read_text()
            self.assertEqual(contents.count('src/gz router-watchdog '),1)
            self.assertIn('src/gz original http://example.com/feed',contents)
            self.assertEqual(config.stat().st_mode & 0o777,0o600)
            self.assertIn('install router-watchdog',log.read_text())
