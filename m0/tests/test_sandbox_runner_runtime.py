"""Execute rejects changed frozen bytes before launch and before returning.

Only the sandbox/process transport is replaced: runtime verification reads the
actual manifest and files. Linux integration covers the real process transport.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.x1.checkpoint import payload_digest
from zoo.circle_packing.frozen_runtime import _runtime_manifest
from zoo.mle_bench_lite.cny_budget import CampaignBudget
from zoo.mle_bench_lite.composed_domain import SandboxRunner


@pytest.mark.parametrize('moment', ['before_launch', 'during_execution'])
def test_execute_rejects_mutated_bound_runtime(tmp_path, monkeypatch, moment):
    runtime = tmp_path / 'runtime'
    (runtime / 'bin').mkdir(parents=True)
    base = Path('/usr/bin/python3').resolve(strict=True)
    (runtime / 'bin/python').symlink_to(base)
    member = runtime / 'package.py'
    member.write_text('original runtime bytes')
    manifest = _runtime_manifest(runtime, base, 'c' * 64)
    ledger = CampaignBudget.create_fixture(tmp_path / 'campaign.db')
    ledger.enable_governance(expected_policy_sha256=ledger.manifest_binding()['policy_sha256'],
                             expected_head=ledger.snapshot()['journal_head'])
    plan_ref, tree_ref = 'sha256:' + 'a' * 64, 'sha256:' + 'b' * 64
    ledger.freeze_circle_pilot(plan_ref, tree_ref, 30, require_runtime=True)
    runtime_ref = 'sha256:' + payload_digest(manifest)
    ledger.freeze_circle_runtime(plan_ref, tree_ref, runtime_ref, manifest['base_python_sha256'])
    runner = object.__new__(SandboxRunner)
    runner.runtime_root, runner.interpreter = runtime, str(runtime / 'bin/python')
    runner._campaign_runtime = (ledger, manifest, str(base), runtime_ref)
    runner._continuation_runtime = None
    runner.sandbox = SimpleNamespace(wrap=lambda args, **kwargs: ['sandbox-transport', '--', *args],
                                     seccomp_spec=lambda: None)
    workspace = tmp_path / 'evaluation'
    workspace.mkdir()
    launched = []
    class Process:
        pid = 123

        def wait(self, timeout):
            member.write_text('changed during execution')
            return 0

    def launch(*args, **kwargs):
        launched.append(args)
        return Process()

    monkeypatch.setattr('zoo.mle_bench_lite.composed_domain.subprocess.Popen', launch)
    monkeypatch.setattr('zoo.mle_bench_lite.composed_domain.os.killpg', lambda *args: None)
    if moment == 'before_launch':
        member.write_text('changed before execution')
    before = ledger.snapshot()
    with pytest.raises(ValueError, match='runtime content differs'):
        runner.execute(workspace, timeout=1)
    assert bool(launched) is (moment == 'during_execution')
    assert ledger.snapshot() == before
