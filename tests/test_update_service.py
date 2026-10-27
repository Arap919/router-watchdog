import contextlib
import hashlib
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVICE = ROOT / 'net/router-watchdog/files/opt/libexec/router-watchdog/update_service.py'


def package(path, version='1.0.11-1'):
    text = f'Package: router-watchdog\nVersion: {version}\nArchitecture: all\n'.encode()
    inner = io.BytesIO()
    with tarfile.open(fileobj=inner, mode='w:gz') as archive:
        info = tarfile.TarInfo('./control')
        info.size = len(text)
        archive.addfile(info, io.BytesIO(text))
    with tarfile.open(path, mode='w:gz') as archive:
        data = inner.getvalue()
        info = tarfile.TarInfo('./control.tar.gz')
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))


class TestUpdateService(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SERVICE.exists(), 'update_service module must exist')
        spec = importlib.util.spec_from_file_location('update_service_tests', SERVICE)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = pathlib.Path(self.temp.name) / 'package.ipk'
        package(self.path)
        self.manifest = {'schema_version': 1, 'latest_version': '1.0.11-1',
            'package_url': 'https://arap919.github.io/router-watchdog/all/router-watchdog_1.0.11-1_all.ipk',
            'sha256': hashlib.sha256(self.path.read_bytes()).hexdigest(),
            'size': self.path.stat().st_size,
            'release_url': 'https://github.com/Arap919/router-watchdog/releases/tag/v1.0.11',
            'release_notes': ''}
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(self.module, 'UPDATE_LOCK_PATH', pathlib.Path(self.temp.name) / 'lock'))

    def test_check_returns_contract_without_controller_config(self):
        with (mock.patch.object(self.module, 'fetch_manifest', return_value=self.manifest),
              mock.patch.object(self.module, 'installed_version', return_value='1.0.10-1')):
            result = self.module.check_update()
        self.assertTrue(result['update_available'])
        self.assertEqual(result['latest_version'], '1.0.11-1')
        self.assertEqual(result['installed_version'], '1.0.10-1')
        self.assertTrue(result['checked_at'].endswith('Z'))

    def test_versions_are_numeric_and_never_downgrade(self):
        for installed, available in [('1.0.9-1', True), ('1.0.11-1', False),
                                      ('1.0.12-1', False), ('1.0.11-2', False)]:
            with (self.subTest(installed=installed),
                  mock.patch.object(self.module, 'fetch_manifest', return_value=self.manifest),
                  mock.patch.object(self.module, 'installed_version', return_value=installed)):
                self.assertEqual(self.module.check_update()['update_available'], available)

    def test_manifest_rejects_untrusted_url_hash_size_or_schema(self):
        cases = [('package_url', 'https://evil.example/pkg.ipk'),
                 ('package_url', self.manifest['package_url'] + '?token=a'),
                 ('latest_version', '1.0.11;id'), ('sha256', 'bad'),
                 ('size', True), ('size', 0), ('schema_version', 2),
                 ('release_url', 'https://evil.example/release')]
        for key, value in cases:
            with self.subTest(key=key), mock.patch.object(self.module, '_open', return_value=io.BytesIO(json.dumps({**self.manifest, key:value}).encode())):
                with self.assertRaises(self.module.UpdateError):
                    self.module.fetch_manifest()

    def test_package_integrity_and_control_metadata(self):
        self.module.verify_package(self.path, self.manifest)
        with self.assertRaises(self.module.UpdateError):
            self.module.verify_package(self.path, {**self.manifest, 'sha256': '0'*64})
        package(self.path, '1.0.10-1')
        bad = {**self.manifest, 'size': self.path.stat().st_size,
               'sha256': hashlib.sha256(self.path.read_bytes()).hexdigest()}
        with self.assertRaises(self.module.UpdateError):
            self.module.verify_package(self.path, bad)

    def test_install_is_pinned_and_verified(self):
        def download(manifest, path):
            path.write_bytes(self.path.read_bytes())
        with (mock.patch.object(self.module, 'fetch_manifest', return_value=self.manifest),
              mock.patch.object(self.module, 'installed_version', side_effect=['1.0.10-1','1.0.11-1']),
              mock.patch.object(self.module, 'download_package', side_effect=download),
              mock.patch.object(self.module.subprocess, 'run', return_value=subprocess.CompletedProcess([],0,'','')) as run):
            result = self.module.install_update('1.0.11-1')
        self.assertEqual(result, {'installed_version':'1.0.11-1','updated':True})
        self.assertEqual(run.call_args_list[0].args[0], ['/opt/bin/opkg','update'])
        argv = run.call_args_list[1].args[0]
        self.assertEqual(argv[:2], ['/opt/bin/opkg','install'])
        self.assertTrue(argv[2].endswith('.ipk'))
        self.assertNotIn('shell', run.call_args.kwargs)

    def test_stale_expected_version_and_downgrade_never_invoke_opkg(self):
        for expected, installed in [('1.0.10-1','1.0.9-1'),('1.0.11-1','1.0.12-1')]:
            with (self.subTest(expected=expected, installed=installed),
                  mock.patch.object(self.module, 'fetch_manifest', return_value=self.manifest),
                  mock.patch.object(self.module, 'installed_version', return_value=installed),
                  mock.patch.object(self.module.subprocess, 'run') as run):
                with self.assertRaises(self.module.UpdateError):
                    self.module.install_update(expected)
                run.assert_not_called()

    def test_busy_and_opkg_failure_are_errors(self):
        with mock.patch.object(self.module.fcntl, 'flock', side_effect=BlockingIOError):
            with self.assertRaises(self.module.UpdateError) as raised:
                self.module.install_update('1.0.11-1')
            self.assertEqual(raised.exception.code, 'busy')
        with (mock.patch.object(self.module, 'fetch_manifest', return_value=self.manifest),
              mock.patch.object(self.module, 'installed_version', return_value='1.0.10-1'),
              mock.patch.object(self.module, 'download_package', side_effect=lambda manifest,path:path.write_bytes(self.path.read_bytes())),
              mock.patch.object(self.module.subprocess, 'run', return_value=subprocess.CompletedProcess([],1,'private-output',''))):
            with self.assertRaises(self.module.UpdateError) as raised:
                self.module.install_update('1.0.11-1')
            self.assertNotIn('private-output', str(raised.exception))

    def test_status_parses_opkg_user_install_and_uninstalled(self):
        for output, expected in [('Package: router-watchdog\nVersion: 1.0.10-1\nStatus: install user installed\n','1.0.10-1'), ('',None)]:
            with mock.patch.object(self.module.subprocess, 'run', return_value=subprocess.CompletedProcess([],0,output,'')):
                self.assertEqual(self.module.installed_version(), expected)

    def test_download_stream_and_integrity(self):
        target = pathlib.Path(self.temp.name) / 'download.ipk'
        with mock.patch.object(self.module, '_open', return_value=io.BytesIO(self.path.read_bytes())):
            self.module.download_package(self.manifest, target)
        self.module.verify_package(target, self.manifest)
        with mock.patch.object(self.module, '_open', return_value=io.BytesIO(self.path.read_bytes()+b'extra')):
            with self.assertRaises(self.module.UpdateError):
                self.module.download_package(self.manifest, target)

    def test_already_current_is_a_noop(self):
        with (mock.patch.object(self.module, 'fetch_manifest', return_value=self.manifest),
              mock.patch.object(self.module, 'installed_version', return_value='1.0.11-1'),
              mock.patch.object(self.module.subprocess, 'run') as run):
            self.assertEqual(self.module.install_update('1.0.11-1'),
                             {'installed_version':'1.0.11-1','updated':False})
        run.assert_not_called()

    def test_opkg_timeout_is_sanitized(self):
        with mock.patch.object(self.module.subprocess, 'run', side_effect=subprocess.TimeoutExpired('opkg',60,output='private-value')):
            with self.assertRaises(self.module.UpdateError) as raised:
                self.module.run_opkg(['update'])
        self.assertEqual(raised.exception.code, 'update_timeout')
        self.assertNotIn('private-value', str(raised.exception))

    def test_opkg_subprocesses_prioritize_entware_path(self):
        status = subprocess.CompletedProcess([],0,'Package: router-watchdog\nVersion: 1.0.10-1\nStatus: install user installed\n','')
        with (mock.patch.dict(os.environ, {'PATH':'/usr/bin:/bin'}),
              mock.patch.object(self.module.subprocess, 'run', return_value=status) as run):
            self.module.installed_version()
            self.assertTrue(run.call_args.kwargs.get('env',{}).get('PATH','').startswith('/opt/bin:/opt/sbin:'))
            self.module.run_opkg(['update'])
            self.assertTrue(run.call_args.kwargs.get('env',{}).get('PATH','').startswith('/opt/bin:/opt/sbin:'))

    def test_cli_routes_before_watchdog_config_or_shared_lock(self):
        from test_cli import module
        with (mock.patch.dict('sys.modules', {'update_service': self.module}),
              mock.patch.object(self.module, 'main', return_value=0) as main,
              mock.patch.object(module, 'CONFIG_PATH', pathlib.Path(self.temp.name)/'missing'),
              mock.patch('sys.argv', ['router-watchdog','--check-update'])):
            code = module.main()
        self.assertEqual(code, 0)
        main.assert_called_once_with(None)
