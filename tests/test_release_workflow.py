import hashlib
import importlib.util
import io
import json
import os
import pathlib
import shutil
import subprocess
import tarfile
import tempfile
import unittest
import urllib.parse

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / '.github/scripts/select_release_build.py'
SHA = 'a' * 40


def run_record(**changes):
    return {'id': 101, 'head_sha': SHA, 'event': 'push', 'head_branch': 'main',
            'status': 'completed', 'conclusion': 'success', **changes}


def artifacts(expired=False):
    return [{'id': 201, 'name': 'router-watchdog-ipk', 'expired': expired},
            {'id': 202, 'name': 'router-watchdog-feed', 'expired': expired}]


class TestReleaseSelection(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.exists(), 'release artifact selector must exist')
        spec = importlib.util.spec_from_file_location('release_selection', SCRIPT)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.calls = []

    def select(self, runs, assets):
        def get(path):
            self.calls.append(path)
            if '/runs?' in path:
                return {'workflow_runs': runs}
            return {'artifacts': assets}
        return self.module.select_build(get, SHA)

    def test_selects_successful_main_push_for_exact_sha(self):
        result = self.select([run_record()], artifacts())
        self.assertEqual(result, {'run_id': 101, 'ipk_artifact_id': 201, 'feed_artifact_id': 202})
        self.assertIn('head_sha=' + SHA, self.calls[0])
        self.assertIn('branch=main', self.calls[0])
        self.assertIn('event=push', self.calls[0])

    def test_never_uses_another_commit_pr_or_failed_run(self):
        cases = [{'head_sha': 'b' * 40}, {'event': 'pull_request'},
                 {'head_branch': 'feature/test'}, {'conclusion': 'failure'},
                 {'status': 'in_progress'}]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(RuntimeError):
                self.select([run_record(**case)], artifacts())

    def test_missing_expired_or_duplicate_assets_fail(self):
        for assets in [[], artifacts()[:1], artifacts(True), artifacts() + artifacts()[:1]]:
            with self.subTest(assets=assets), self.assertRaises(RuntimeError):
                self.select([run_record()], assets)

    def test_no_matching_build_fails_without_fallback(self):
        with self.assertRaises(RuntimeError):
            self.select([], artifacts())

    def test_paginated_runs_and_artifacts(self):
        def get(path):
            page = int(urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)['page'][0])
            if '/runs?' in path:
                return {'workflow_runs': [run_record(head_sha='b' * 40)] * 100 if page == 1 else [run_record()]}
            return {'artifacts': [{'id': 1, 'name': 'other', 'expired': False}] * 100 if page == 1 else artifacts()}
        result = self.module.select_build(get, SHA)
        self.assertEqual(result['run_id'], 101)


class TestReleasePayload(unittest.TestCase):
    def setUp(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/build-package.yml').read_text())
        self.assertTrue('release' in workflow['jobs'], 'tag release must be separate from build')
        jobs = workflow['jobs']
        self.jobs = jobs
        self.verify = next(step['run'] for step in jobs['release']['steps']
                           if step['name'] == 'Verify release payload')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        (self.root / 'net/router-watchdog').mkdir(parents=True)
        (self.root / 'net/router-watchdog/Makefile').write_text('PKG_VERSION:=1.0.10\nPKG_RELEASE:=1\n')
        (self.root / 'dist').mkdir()
        (self.root / 'feed/all').mkdir(parents=True)

    def package(self, version='1.0.10-1'):
        control = ('Package: router-watchdog\nVersion: ' + version + '\nArchitecture: all\n').encode()
        inner = io.BytesIO()
        with tarfile.open(fileobj=inner, mode='w:gz') as archive:
            info = tarfile.TarInfo('./control')
            info.size = len(control)
            archive.addfile(info, io.BytesIO(control))
        package = self.root / 'dist/router-watchdog_1.0.10-1_all.ipk'
        with tarfile.open(package, mode='w:gz') as archive:
            data = inner.getvalue()
            info = tarfile.TarInfo('./control.tar.gz')
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        shutil.copyfile(package, self.root / 'feed/all' / package.name)
        digest = hashlib.sha256(package.read_bytes()).hexdigest()
        (self.root / 'feed/all/Packages').write_text(control.decode() + 'Filename: ' + package.name + '\nSHA256sum: ' + digest + '\nSize: ' + str(package.stat().st_size) + '\n')
        import gzip
        (self.root / 'feed/all/Packages.gz').write_bytes(gzip.compress((self.root / 'feed/all/Packages').read_bytes()))

    def verify_result(self):
        return subprocess.run(['bash', '-c', self.verify], cwd=self.root,
                              env={**os.environ, 'GITHUB_REF_NAME': 'v1.0.10'},
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_valid_payload_passes(self):
        self.package()
        self.assertEqual(self.verify_result().returncode, 0)

    def test_wrong_package_version_fails(self):
        self.package('1.0.9-1')
        self.assertNotEqual(self.verify_result().returncode, 0)

    def test_different_feed_package_fails(self):
        self.package()
        (self.root / 'feed/all/router-watchdog_1.0.10-1_all.ipk').write_bytes(b'other')
        self.assertNotEqual(self.verify_result().returncode, 0)

    def test_tag_does_not_build_and_publish_uses_selected_run(self):
        self.assertIn("refs/heads/main", self.jobs['build']['if'])
        self.assertIn('pull_request', self.jobs['build']['if'])
        self.assertIn('refs/tags/v', self.jobs['release']['if'])
        self.assertEqual(self.jobs['release']['permissions']['actions'], 'read')
        self.assertEqual(self.jobs['publish-feed']['needs'], 'release')
        downloads = [step for step in self.jobs['release']['steps']
                     if step.get('uses', '').startswith('actions/download-artifact@')]
        self.assertEqual(len(downloads), 2)
        for step in downloads:
            self.assertIn('run-id', step['with'])
            self.assertIn('artifact-ids', step['with'])
            self.assertIn('github-token', step['with'])
