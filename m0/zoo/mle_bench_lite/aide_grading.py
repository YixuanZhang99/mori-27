"""Grade a frozen AIDE submission after search; never invoke search or training."""
import json
from pathlib import Path

from core.tasks.adapter import Workspace
from core.x1.store import AppendOnlyStore
from zoo.mle_bench_lite.agent_common import _atomic_json
from zoo.mle_bench_lite.public_train import digest, file_digest


def grade_selected(*, output, adapter, prepared_identity, fixture=False):
    """Consume the pinned adapter and a separately verified prepared-data identity.

    The command-line entry validates official imports and data against an identity
    frozen before search. Fixture mode is for synthetic protocol tests only.
    """
    output = Path(output).resolve()
    report = json.loads((output / 'method-report.json').read_text())
    manifest = json.loads((output / 'run-manifest.json').read_text())
    if report['run_state'] != 'completed' or not report.get('submission') or not report.get('replay_certificate', {}).get('passed'):
        raise ValueError('grading requires a completed, replay-certified selected submission')
    if not fixture and (report['mode'] != 'live' or not report.get('independent_physical_submission')
                        or not report.get('independent_currency_receipts')):
        raise ValueError('official grading requires a complete live run with independent audits')
    if report['task_id'] != adapter.competition_id or manifest['task_id'] != adapter.competition_id:
        raise ValueError('grader task differs from selected submission')
    selected = report['submission']
    if file_digest(output / 'submission.csv') != selected['submission_sha256']:
        raise ValueError('frozen submission changed')
    original = AppendOnlyStore(output / 'composed/x1.jsonl')
    frozen = [r['payload'] for r in original.read('metric_final_frozen')]
    terminal = [r['payload'] for r in original.read('metric_final_completed')]
    if (len(frozen) != 1 or len(terminal) != 1 or terminal[0]['state'] != 'completed' or
            frozen[0]['candidate_id'] != selected['candidate_id'] or
            terminal[0]['candidate_id'] != selected['candidate_id'] or
            frozen[0]['binding']['artifact_sha256'] != selected['artifact_sha256']):
        raise ValueError('submission differs from original frozen selection')
    binding = {'schema_version': 1, 'method_id': 'AIDE', 'task_id': adapter.competition_id,
        'run_manifest_sha256': digest(manifest), 'selection': selected,
        'final_freeze_sha256': digest(frozen[0]), 'prepared_identity_sha256': digest(prepared_identity),
        'fixture': fixture}
    audit = AppendOnlyStore(output / 'official/audit.jsonl')
    starts = [r['payload'] for r in audit.read('aide_grading_started')]
    ends = [r['payload'] for r in audit.read('aide_grading_completed')]
    if starts or ends:
        if not ends:
            raise ValueError('unfinished grading attempt; automatic grader re-execution is disabled')
        if starts != [binding] or len(ends) != 1 or ends[0]['binding'] != binding:
            raise ValueError('original grading identity differs')
        _atomic_json(output / 'official/result.json', ends[0])
        return ends[0]
    audit.append('aide_grading_started', binding)
    result = {'binding': binding, 'state': 'grading_failed', 'error_type': None,
              'official_score': None, 'external_benchmark_score_produced': False, 'report': None}
    try:
        public = adapter.grade_submission(Workspace(output), 'audit', audit)
        if file_digest(output / 'submission.csv') != selected['submission_sha256']:
            raise ValueError('submission changed during grading')
        result.update(state='completed', report=public, official_score=public.get('audit/score'),
                      external_benchmark_score_produced=not fixture)
    except Exception as error:
        result['error_type'] = type(error).__name__
    audit.append('aide_grading_completed', result)
    _atomic_json(output / 'official/result.json', result)
    return result


def main(argv=None):
    import argparse
    from zoo.mle_bench_lite.adapter import MLEBenchLiteAdapter
    from zoo.mle_bench_lite.pilot import _official_prepared_identity
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--official-root', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--frozen-prepared-identity', type=Path, required=True)
    args = parser.parse_args(argv)
    run = json.loads((args.output / 'run-manifest.json').read_text())
    task = run['task_id']
    adapter = MLEBenchLiteAdapter(task, args.official_root, args.data_root)
    expected = json.loads(args.frozen_prepared_identity.read_text())
    actual = _official_prepared_identity(args.official_root, args.data_root,
                                       list(expected['prepared_tasks']), {name: MLEBenchLiteAdapter(
                                           name, args.official_root, args.data_root) for name in expected['prepared_tasks']})
    if actual != expected:
        raise ValueError('official prepared data or grader differs from the predeclared identity')
    # Prove the CSVs used by the selected run came from the same official data.
    sources = actual['prepared_tasks'][task]['files']
    for name, sha in run['dataset_manifest']['source_sha256'].items():
        if sources['public/' + name]['sha256'] != sha:
            raise ValueError('search public data differs from the official prepared dataset')
    result = grade_selected(output=args.output, adapter=adapter, prepared_identity=actual)
    print(json.dumps({key: result[key] for key in ('state', 'error_type', 'official_score', 'external_benchmark_score_produced')}))
    return 0 if result['state'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
