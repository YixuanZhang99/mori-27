"""Build and independently install the wheel, then execute copied public examples."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    env = {k: v for k, v in os.environ.items() if 'API_KEY' not in k.upper()
           and not k.upper().endswith('_TOKEN') and k not in {'PYTHONPATH', 'UV_PROJECT_ENVIRONMENT'}}
    env.update(UV_OFFLINE='1', UV_PYTHON=sys.executable, PYTHONDONTWRITEBYTECODE='1')
    with tempfile.TemporaryDirectory(prefix='mori-installed-m7-') as directory:
        root = Path(directory)
        def run(args):
            child = subprocess.run(args, cwd=root, env=env, capture_output=True, text=True, timeout=120)
            if child.returncode:
                raise RuntimeError(f'Installed acceptance command failed ({child.returncode}): {args!r}\n{child.stderr[-4000:]}')
            return child.stdout
        run(['uv', 'build', str(ROOT), '--out-dir', str(root / 'dist')])
        wheels = list((root / 'dist').glob('*.whl'))
        if len(wheels) != 1:
            raise ValueError('expected exactly one built wheel')
        run(['uv', 'venv', '--python', sys.executable, str(root / 'venv')])
        python = str(root / 'venv/bin/python')
        run(['uv', 'pip', 'install', '--offline', '--python', python, str(wheels[0])])
        location = Path(run([python, '-I', '-c', 'from pathlib import Path; import core; print(Path(core.__file__).parent.parent)']).strip())
        if not location.is_relative_to(root / 'venv'):
            raise ValueError('independent interpreter imported outside its environment')
        checked = 0
        for package in ('core', 'zoo'):
            for source in (ROOT / package).rglob('*.py'):
                relative = source.relative_to(ROOT)
                installed = location / relative
                if source.read_bytes() != installed.read_bytes():
                    raise ValueError('installed source differs: ' + str(relative))
                checked += 1
        reports = {}
        for name, file, options in (
            ('git_native', 'configured_execution_offline.py', []),
            ('legacy_currency', 'governed_cny_offline.py', []),
            ('construction_currency', 'governed_cny_offline.py', ['--construction'])):
            script = root / file
            shutil.copyfile(ROOT / 'examples' / file, script)
            reports[name] = json.loads(run([python, '-I', str(script), '--workdir', str(root / name), *options]))
        native, legacy, currency = (reports[n] for n in ('git_native', 'legacy_currency', 'construction_currency'))
        assert native['artifacts'] == 2 and native['generation_calls'] == 2 and native['evaluations'] == 5
        assert native['external_provider_requests'] == 0 and native['recorded_replay_passed']
        for report, calls, cost in ((legacy, 4, 152), (currency, 8, 304)):
            assert report['external_model_requests'] == report['replay_new_http_requests'] == 0
            assert report['recorded_replay_passed'] and report['replay_currency_events_changed'] is False
            assert report['loopback_http_requests'] == calls and report['fixture_settled_micro_cny'] == cost
        assert currency['construction_artifacts'] == 4
        print(json.dumps({'passed': True, 'isolated_python': True, 'outside_checkout': True,
            'verified_installed_modules': checked, 'wheel_sha256': hashlib.sha256(wheels[0].read_bytes()).hexdigest(),
            'external_provider_requests': 0, 'reports': reports}, sort_keys=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
