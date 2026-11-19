"""Rebuild and record a seed-0 pair from the original supervisor artifacts.

Run in the frozen source and runtime. This command makes no provider calls or
candidate executions; it records a trusted offline audit, not a benchmark or
an authorization to open the live gate.
"""
import json
import os
from pathlib import Path
import sys

from core.composition.recovery import ContinuationStore
from core.x1.checkpoint import payload_digest
from zoo.circle_packing.cell_deadline import RecordedCellClock
from zoo.circle_packing.pair_audit import record_first_pair_audit
from zoo.mle_bench_lite.cny_budget import CampaignBudget
from zoo.mle_bench_lite.composed_domain import SandboxRunner
from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView


def _clock_evidence(path):
    rows = list(ContinuationStore(path).read())
    if not rows or rows[0]['kind'] != 'circle_cell_deadline_started' or any(
            row['kind'] != 'circle_cell_deadline_observed' for row in rows[1:]):
        raise ValueError('clock journal must contain one original start and its observations')
    return {'schema_version': 1, 'record': rows[0]['payload'],
            'observations': [row['payload'] for row in rows[1:]]}


def record_first_pair_from_supervisors(*, mori_directory, reference_directory, expected_head, replay_output):
    """Reconstruct from the two original supervisors at the supplied campaign head."""
    try:
        mori_directory, reference_directory = Path(mori_directory), Path(reference_directory)
        config = json.loads((mori_directory / 'config.json').read_text())
        reference = json.loads((reference_directory / 'config.json').read_text())
        if config['seed'] != 0 or reference['seed'] != 0 or config['ref'] != reference['ref'] or \
                config['plan'] != reference['plan'] or config['ledger'] != reference['ledger']:
            raise ValueError('supervisors do not belong to the same first pair')
        ledger = CampaignBudget(config['ledger'])
        if ledger.snapshot()['journal_head'] != expected_head:
            raise ValueError('campaign head differs from the requested audit head')
        mori_rows = list(ContinuationStore(Path(config['output']) / 'framework' / 'x1.jsonl').read())
        reference_rows = list(ContinuationStore(Path(reference['output']) / 'events.jsonl').read())
        context = next(row['payload']['invocation']['external_context'] for row in mori_rows
                       if row['kind'] == 'composed_provider_started')
        mori_run, mori_plan = context['currency_run_id'], context['physical_plan_ref']
        reference_run = ledger.reference_authority_claim('vendor-0')['currency_run_id']
        physical_plans = {row['payload']['plan_ref'] for row in reference_rows
                          if row['kind'] == 'governed_control_started'}
        if len(physical_plans) != 1:
            raise ValueError('reference journal lacks one original physical plan')
        mori_view = RecordedCurrencyView(ledger.export_governance_evidence(mori_run, mori_plan),
                                         expected_run_id=mori_run, expected_head=expected_head)
        reference_view = RecordedCurrencyView(ledger.export_governance_evidence(reference_run, next(iter(physical_plans))),
                                              expected_run_id=reference_run, expected_head=expected_head)
        mori_clock = RecordedCellClock(_clock_evidence(config['clock']), mori_view.cell_deadline_claim('mori-0'))
        reference_clock = RecordedCellClock(_clock_evidence(reference['clock']),
                                            reference_view.cell_deadline_claim('vendor-0'))
        replay_input = json.loads((Path(config['output']) / 'replay-input.json').read_text())
        reference_bundle = json.loads((Path(reference['output']) / 'reference-currency.json').read_text())
        runner = SandboxRunner.for_campaign_runtime(ledger, runtime=config['runtime'],
                    manifest=config['runtime_manifest'], base_python='/usr/bin/python3.12')
        return record_first_pair_audit(replay_input=replay_input, ledger=ledger, runner=runner,
            replay_output=Path(replay_output), mori_config=config, reference_config=reference,
            mori_supervisor_directory=mori_directory, reference_supervisor_directory=reference_directory,
            seed=0, plan=config['plan'], expected_plan_ref=config['ref'], mori_rows=mori_rows,
            mori_rows_sha256=payload_digest(mori_rows), mori_view=mori_view, mori_clock=mori_clock,
            mori_run_id=mori_run, reference_rows=reference_rows, reference_view=reference_view,
            reference_clock=reference_clock, reference_run_id=reference_run,
            reference_worker_directory=reference['worker_directory'], reference_bundle=reference_bundle)
    except (KeyError, TypeError, AttributeError, StopIteration, json.JSONDecodeError, OSError) as error:
        raise ValueError('cannot reconstruct original first-pair evidence') from error


def main():
    os.environ.pop('DEEPSEEK_API_KEY', None)
    if len(sys.argv) != 5:
        raise SystemExit('usage: python -m zoo.circle_packing.pair_recorded MORI_SUPERVISOR '
                         'REFERENCE_SUPERVISOR HEAD_JSON REPLAY_OUTPUT')
    proof = record_first_pair_from_supervisors(mori_directory=Path(sys.argv[1]),
        reference_directory=Path(sys.argv[2]), expected_head=json.loads(sys.argv[3]), replay_output=Path(sys.argv[4]))
    print(json.dumps({'scope': 'recorded_first_pair_audit', 'plan_ref': proof['plan_ref'],
                      'original_head': proof['result']['journal_head'], 'performance_claim': False}, sort_keys=True))


if __name__ == '__main__':
    main()
