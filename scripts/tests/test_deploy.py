"""Linux command-level deployment tests: actual source filtering, Git and flock.

Docker/curl are isolated executables that emulate project state without any
network calls, containers, or changes outside a dedicated /tmp test directory.
Run: python3 -m unittest discover -s scripts/tests -v
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
MOCK_COMMAND = r'''#!/usr/bin/env python3
import json, os, pathlib, shutil, signal, sqlite3, subprocess, sys
command = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['MOCK_LOG'], 'a') as log:
    log.write(json.dumps({'command': command, 'args': args, 'tag': os.environ.get('RELEASE_TAG')}) + '\n')
mode = os.environ.get('MOCK_MODE', '')
candidate = os.environ['MOCK_CANDIDATE']
state_path = pathlib.Path(os.environ['MOCK_STATE'])
state = json.loads(state_path.read_text())
if command == 'docker':
    if args[0] == 'ps':
        if os.environ.get('MOCK_HAS_BACKEND') == '1': print('abc123def456')
    elif args[0] == 'exec':
        assert args[1] == 'abc123def456' and args[-1] == 'pre-' + candidate + '.sqlite3'
        if 'source.backup(target)' in args[4]:
            source = sqlite3.connect(os.environ['MOCK_DB'])
            target = sqlite3.connect(os.environ['MOCK_BACKUP'])
            source.backup(target); target.close(); source.close()
        else:
            assert 'os.unlink("/data/"+sys.argv[1])' in args[4]
            pathlib.Path(os.environ['MOCK_BACKUP']).unlink()
    elif args[0] == 'cp':
        assert args[1].startswith('abc123def456:/data/pre-')
        shutil.copyfile(os.environ['MOCK_BACKUP'], args[2])
    elif args[0] == 'compose':
        assert args[args.index('--project-name') + 1] == 'turning-point'
        directory = args[args.index('--project-directory') + 1]
        action = args[args.index('-f') + 2:]
        tag = os.environ['RELEASE_TAG']
        if action[0] == 'build' and mode == 'build_fail': sys.exit(12)
        if action[0] == 'up':
            assert '--no-build' in action and '--wait' in action
            state_path.write_text(json.dumps({'tag': tag, 'directory': directory}))
            if tag == candidate and mode in ('up_fail', 'rollback_fail'): sys.exit(13)
            if tag != candidate and mode == 'rollback_fail': sys.exit(14)
        if action[0] == 'exec':
            assert action[1:] == ['-T', 'frontend', 'nginx', '-t']
            if tag == candidate and mode == 'nginx_fail': sys.exit(15)
    else: raise AssertionError('Unexpected Docker operation: ' + repr(args))
elif command == 'curl':
    assert args[args.index('--header') + 1] == 'Host: football.thedebeer.co.za'
    output = pathlib.Path(args[args.index('--output') + 1])
    url = args[-1]
    assert url.startswith('http://192.168.10.58:5177/')
    if state['tag'] == candidate and mode == 'api_fail': sys.exit(22)
    if url.endswith('/api/health'):
        value = {'status': 'bad' if state['tag'] == candidate and mode == 'api_bad_json' else 'ok'}
    elif url.endswith('/release.json'):
        value = json.loads((pathlib.Path(state['directory']) / 'frontend/public/release.json').read_text())
        if state['tag'] == candidate and mode == 'release_mismatch': value['commit'] = '0' * 40
    else: raise AssertionError(url)
    output.write_text(json.dumps(value))
elif command == 'mv':
    if mode == 'signal_pointer_fail' and pathlib.Path(args[-2]).resolve().name == 'prior-release':
        sys.exit(16)
    result = subprocess.run([os.environ['MOCK_REAL_MV'], *args])
    if result.returncode: sys.exit(result.returncode)
    if mode in ('signal_after_switch', 'signal_pointer_fail') and pathlib.Path(args[-1]).resolve().name == candidate:
        os.kill(os.getppid(), signal.SIGTERM)
else: raise AssertionError(command)
'''


@unittest.skipUnless(sys.platform.startswith('linux'), 'Linux Bash/flock command integration tests')
class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='turning-point-deploy-test-', dir='/tmp')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'checkout'
        self.base = self.root / 'deployment'
        self.source.mkdir()
        (self.source / 'scripts').mkdir()
        shutil.copyfile(ROOT / 'deploy.sh', self.source / 'scripts/deploy.sh')
        shutil.copyfile(ROOT / 'package_deploy.py', self.source / 'scripts/package_deploy.py')
        for relative, content in {
            'backend/main.py': '# fixture source only\n',
            'server_data/fixture.json': '{}\n',
            'frontend/public/index.html': 'Turning Point\n',
            'docker/backend.Dockerfile': 'FROM scratch\n',
            'docker-compose.production.yml': 'name: turning-point\n',
            '.dockerignore': '.env\n',
        }.items():
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        (self.source / 'backend/main.py').chmod(0o600)
        for relative in ('backend', 'server_data', 'frontend', 'frontend/public'):
            (self.source / relative).chmod(0o700)
        subprocess.run(['git', 'init', '-q', str(self.source)], check=True)
        subprocess.run(['git', '-C', str(self.source), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.source), '-c', 'user.name=Deployment test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture'], check=True)
        self.commit = subprocess.check_output(['git', '-C', str(self.source), 'rev-parse', 'HEAD'], text=True).strip()
        # Private/untracked local files must not enter the source archive.
        (self.source / 'backend/.env').write_text('private test sentinel')
        (self.source / 'backend/local.sqlite3').write_bytes(b'private sqlite sentinel')
        (self.source / 'frontend/node_modules').mkdir()
        (self.source / 'frontend/node_modules/private.js').write_text('excluded')
        self.candidate = '1001-1-abcdef0'
        self.previous = self.base / 'releases/prior-release'
        self.previous.mkdir(parents=True)
        (self.previous / 'docker-compose.production.yml').write_text('name: turning-point\n')
        (self.previous / 'release-tag').write_text('prior-release\n')
        marker = self.previous / 'frontend/public/release.json'
        marker.parent.mkdir(parents=True)
        marker.write_text(json.dumps({'commit': 'a' * 40, 'release': 'prior-release'}))
        (self.base / 'current').symlink_to(self.previous, target_is_directory=True)
        self.database = self.root / 'retained-volume.sqlite3'
        connection = sqlite3.connect(self.database)
        connection.execute('CREATE TABLE retained (value TEXT)')
        connection.execute("INSERT INTO retained VALUES ('existing replay data')")
        connection.commit()
        connection.close()
        self.state = self.root / 'container-state.json'
        self.state.write_text(json.dumps({'tag': 'prior-release', 'directory': str(self.previous)}))
        self.log = self.root / 'commands.jsonl'
        mock_bin = self.root / 'mock-bin'
        mock_bin.mkdir()
        for command in ('docker', 'curl', 'mv'):
            path = mock_bin / command
            path.write_text(MOCK_COMMAND)
            path.chmod(0o700)
        self.environment = {**os.environ, 'PATH': str(mock_bin) + os.pathsep + os.environ['PATH'],
            'TP_DEPLOY_TEST_MODE': '1', 'TP_DEPLOY_TEST_BASE': str(self.base), 'TP_DEPLOY_TEST_LOCK_SECONDS': '1',
            'MOCK_LOG': str(self.log), 'MOCK_STATE': str(self.state), 'MOCK_DB': str(self.database),
            'MOCK_BACKUP': str(self.root / 'consistent-backup.sqlite3'), 'MOCK_CANDIDATE': self.candidate, 'MOCK_HAS_BACKEND': '1',
            'MOCK_REAL_MV': shutil.which('mv')}

    def deploy(self, mode='', args=None, env=None):
        return subprocess.run(['bash', str(self.source / 'scripts/deploy.sh'), *(args or [str(self.source), self.commit, self.candidate])],
            env={**self.environment, 'MOCK_MODE': mode, **(env or {})}, capture_output=True, text=True, timeout=20)

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def assert_retained(self):
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(connection.execute('SELECT value FROM retained').fetchall(), [('existing replay data',)])
        for command in self.commands():
            self.assertFalse({'down', 'prune', 'rm', 'volume', 'restore'}.intersection(command['args']), command)

    def test_success_builds_before_backup_and_switch_and_filters_private_source(self):
        result = self.deploy()
        self.assertEqual(result.returncode, 0, result.stderr)
        release = self.base / 'releases' / self.candidate
        self.assertEqual((self.base / 'current').resolve(), release)
        self.assertEqual((release / 'deployed-commit').read_text().strip(), self.commit)
        self.assertEqual(json.loads((release / 'frontend/public/release.json').read_text()), {'commit': self.commit, 'release': self.candidate})
        self.assertEqual(stat.S_IMODE((release / 'frontend/public/release.json').stat().st_mode), 0o644)
        self.assertEqual(stat.S_IMODE((release / 'backend/main.py').stat().st_mode), 0o644)
        for relative in ('backend', 'server_data', 'frontend', 'frontend/public'):
            self.assertEqual(stat.S_IMODE((release / relative).stat().st_mode), 0o755, relative)
        archive = self.base / 'archives' / f'source-{self.candidate}.tar.gz'
        self.assertEqual(stat.S_IMODE(archive.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(release.stat().st_mode), 0o700)
        with tarfile.open(archive) as bundle:
            self.assertFalse(any('.env' in name or '.sqlite' in name or 'node_modules' in name for name in bundle.getnames()))
            self.assertTrue(all(info.mode == 0o644 for info in bundle.getmembers() if info.isfile()))
        commands = self.commands()
        build = next(i for i, c in enumerate(commands) if 'build' in c['args'])
        backup = next(i for i, c in enumerate(commands) if c['args'][0] == 'exec')
        up = next(i for i, c in enumerate(commands) if 'up' in c['args'])
        self.assertLess(build, backup)
        self.assertLess(backup, up)
        backup_file = self.base / 'backups' / f'pre-{self.candidate}.sqlite3'
        self.assertEqual(stat.S_IMODE((self.base / 'backups').stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(backup_file.stat().st_mode), 0o600)
        with sqlite3.connect(backup_file) as connection:
            self.assertEqual(connection.execute('SELECT value FROM retained').fetchall(), [('existing replay data',)])
        self.assertFalse(Path(self.environment['MOCK_BACKUP']).exists())
        self.assert_retained()

    def test_failed_build_never_switches_or_backs_up_running_containers(self):
        result = self.deploy('build_fail')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.base / 'current').resolve(), self.previous)
        self.assertFalse(any(c['args'][0] in ('exec', 'cp') or 'up' in c['args'] for c in self.commands()))
        self.assert_retained()

    def test_failed_start_nginx_api_or_wrong_frontend_automatically_restore_old_images(self):
        for mode in ('up_fail', 'nginx_fail', 'api_fail', 'api_bad_json', 'release_mismatch'):
            with self.subTest(mode=mode):
                self.candidate = 'failure-' + mode.replace('_', '-')
                self.environment['MOCK_CANDIDATE'] = self.candidate
                result = self.deploy(mode)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn('Previous release restored', result.stderr)
                self.assertEqual((self.base / 'current').resolve(), self.previous)
                self.assertEqual(json.loads(self.state.read_text())['tag'], 'prior-release')
                self.assertFalse(any(c['command'] == 'mv' for c in self.commands()))
                self.assert_retained()

    def test_failed_rollback_preserves_pointer_data_and_reports_manual_inspection(self):
        result = self.deploy('rollback_fail')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Rollback health failed', result.stderr)
        self.assertEqual((self.base / 'current').resolve(), self.previous)
        self.assert_retained()

    def test_signal_after_atomic_pointer_switch_restores_previous_pointer_and_images(self):
        result = self.deploy('signal_after_switch')
        self.assertEqual(result.returncode, 143, result.stderr)
        self.assertIn('Previous release restored', result.stderr)
        self.assertEqual((self.base / 'current').resolve(), self.previous)
        self.assertEqual(json.loads(self.state.read_text())['tag'], 'prior-release')
        self.assert_retained()

    def test_pointer_repair_failure_still_restores_previous_runtime_and_reports_marker(self):
        result = self.deploy('signal_pointer_fail')
        self.assertEqual(result.returncode, 143, result.stderr)
        self.assertIn('Previous runtime restored', result.stderr)
        self.assertIn('Current marker repair failed', result.stderr)
        self.assertEqual(json.loads(self.state.read_text())['tag'], 'prior-release')
        self.assertEqual((self.base / 'current').resolve(), self.base / 'releases' / self.candidate)
        self.assert_retained()

    def test_held_lock_times_out_without_packaging_or_docker_mutation(self):
        lock = self.base / '.deploy.lock'
        signal = self.root / 'lock-held'
        holder = subprocess.Popen(['bash', '-c', 'exec 9>"$1"; flock 9; touch "$2"; sleep 3', 'test', str(lock), str(signal)])
        self.addCleanup(lambda: holder.wait(timeout=5))
        for _ in range(100):
            if signal.exists(): break
            time.sleep(.01)
        self.assertTrue(signal.exists())
        result = self.deploy()
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertEqual(self.commands(), [])
        self.assertFalse((self.base / 'releases' / self.candidate).exists())
        self.assert_retained()

    def test_unsafe_base_source_commit_or_tag_is_refused_before_docker(self):
        cases = [
            ([str(self.source), '0' * 40, self.candidate], {}),
            ([str(self.source), self.commit, '../unsafe'], {}),
            ([str(self.source.parent), self.commit, self.candidate], {}),
            (None, {'TP_DEPLOY_TEST_BASE': '/home/balanceworx/turning-point'}),
            (None, {'TP_DEPLOY_TEST_MODE': '0'}),
        ]
        for args, environment in cases:
            with self.subTest(args=args, environment=environment):
                self.assertNotEqual(self.deploy(args=args, env=environment).returncode, 0)
                self.assertEqual(self.commands(), [])

    def test_symlink_backup_escape_is_refused_before_docker(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (self.base / 'backups').symlink_to(outside, target_is_directory=True)
        self.assertNotEqual(self.deploy().returncode, 0)
        self.assertEqual(self.commands(), [])
        self.assertEqual(list(outside.iterdir()), [])

    def test_release_tag_cannot_overwrite_a_retained_release(self):
        result = self.deploy()
        self.assertEqual(result.returncode, 0, result.stderr)
        count = len(self.commands())
        result = self.deploy()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.commands()), count)
        self.assert_retained()


if __name__ == '__main__':
    unittest.main()
