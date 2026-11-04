"""CI's temporary directory is private, writable and exported to later steps."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/setup_ci_tmpdir.sh'


class CITemporaryDirectoryTests(unittest.TestCase):
    def test_workflow_configures_temp_before_full_acceptance(self):
        workflow = (ROOT / '.github/workflows/ci.yml').read_text()
        self.assertLess(workflow.index('bash scripts/setup_ci_tmpdir.sh'),
                        workflow.index('run: make accept-linux'))

    def test_creates_private_unique_directory_and_exports_it(self):
        with tempfile.TemporaryDirectory() as base:
            base = Path(base)
            env_file = base / 'github-env'
            env_file.touch()
            env = dict(os.environ, GITHUB_ENV=str(env_file), MORI_CI_TMP_ROOT=str(base))
            subprocess.run(['bash', str(SCRIPT)], env=env, check=True)
            line = env_file.read_text().strip()
            self.assertTrue(line.startswith('TMPDIR='))
            path = Path(line.removeprefix('TMPDIR='))
            self.assertEqual(path.parent, base)
            self.assertTrue(path.is_dir())
            self.assertEqual(path.stat().st_mode & 0o777, 0o700)
            (path / 'probe').write_text('ok')

    def test_refuses_missing_github_environment_file(self):
        env = dict(os.environ)
        env.pop('GITHUB_ENV', None)
        result = subprocess.run(['bash', str(SCRIPT)], env=env, capture_output=True)
        self.assertNotEqual(result.returncode, 0)

    def test_falls_back_to_runner_temp_when_fast_root_is_unavailable(self):
        with tempfile.TemporaryDirectory() as base:
            base = Path(base)
            env_file = base / 'github-env'
            env_file.touch()
            fallback = base / 'fallback'
            fallback.mkdir()
            env = dict(os.environ, GITHUB_ENV=str(env_file), MORI_CI_TMP_ROOT=str(base / 'missing'),
                       RUNNER_TEMP=str(fallback))
            subprocess.run(['bash', str(SCRIPT)], env=env, check=True)
            path = Path(env_file.read_text().strip().removeprefix('TMPDIR='))
            self.assertEqual(path.parent, fallback)
            self.assertTrue(path.is_dir())

    def test_falls_back_when_fast_root_has_insufficient_space(self):
        with tempfile.TemporaryDirectory() as base:
            base = Path(base)
            env_file = base / 'github-env'
            env_file.touch()
            fallback = base / 'fallback'
            fallback.mkdir()
            tools = base / 'bin'
            tools.mkdir()
            df = tools / 'df'
            df.write_text('#!/bin/sh\nprintf "Filesystem 1024-blocks Used Available Capacity Mounted\\nfixture 100 0 100 0%% /fixture\\n"\n')
            df.chmod(0o700)
            env = dict(os.environ, GITHUB_ENV=str(env_file), MORI_CI_TMP_ROOT=str(base),
                       RUNNER_TEMP=str(fallback), PATH=str(tools) + os.pathsep + os.environ['PATH'])
            subprocess.run(['bash', str(SCRIPT)], env=env, check=True)
            path = Path(env_file.read_text().strip().removeprefix('TMPDIR='))
            self.assertEqual(path.parent, fallback)

    def test_falls_back_when_fast_root_cannot_execute_files(self):
        with tempfile.TemporaryDirectory() as base:
            base = Path(base)
            env_file = base / 'github-env'
            env_file.touch()
            fallback = base / 'fallback'
            fallback.mkdir()
            tools = base / 'bin'
            tools.mkdir()
            chmod = tools / 'chmod'
            chmod.write_text('#!/bin/sh\nif [ ! -e "$MORI_TEST_MARKER" ]; then touch "$MORI_TEST_MARKER"; exit 0; fi\nexec /bin/chmod "$@"\n')
            chmod.chmod(0o700)
            env = dict(os.environ, GITHUB_ENV=str(env_file), MORI_CI_TMP_ROOT=str(base),
                       RUNNER_TEMP=str(fallback), MORI_TEST_MARKER=str(base / 'marker'),
                       PATH=str(tools) + os.pathsep + os.environ['PATH'])
            subprocess.run(['bash', str(SCRIPT)], env=env, check=True)
            path = Path(env_file.read_text().strip().removeprefix('TMPDIR='))
            self.assertEqual(path.parent, fallback)


if __name__ == '__main__':
    unittest.main()
