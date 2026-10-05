import importlib.util
import io
import pathlib
import sys
import unittest
from contextlib import redirect_stdout

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
            with unittest.mock.patch.object(sys, "argv", ["router-watchdog", "--help"]):
                exit_code = module.main()

        self.assertEqual(exit_code, 0)
        self.assertIn("usage:", stdout.getvalue().lower())


if __name__ == "__main__":
    unittest.main()
