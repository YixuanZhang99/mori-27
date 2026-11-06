"""Recalculate one pair using its original frozen source and runtime.

This is an internal subprocess entry point. It never receives a provider key,
runs candidate code or appends to the original campaign.
"""
import json
from pathlib import Path
import socket
import sys


def main():
    if len(sys.argv) != 8:
        raise SystemExit('invalid frozen pair probe arguments')
    mori_root, vendor_root = map(Path, sys.argv[1:3])
    expected_head, expected_ref = json.loads(sys.argv[3]), sys.argv[4]
    seed, replay_output = int(sys.argv[5]), Path(sys.argv[6])
    expected_ledger = Path(sys.argv[7]).resolve(strict=True)
    from core.composition.recovery import ContinuationStore
    from core.x1.checkpoint import payload_digest
    from zoo.circle_packing.cell_deadline import RecordedCellClock
    from zoo.circle_packing.pair_audit import audit_replayed_supervised_pair
    from zoo.circle_packing.pair_recorded import _clock_evidence
    from zoo.circle_packing.domain import CirclePackingDomain
    import zoo.circle_packing.host_physical as host_physical
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    from zoo.mle_bench_lite.composed_domain import SandboxRunner
    from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView
    from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider

    def forbidden(*_args, **_kwargs):
        raise AssertionError('offline pair audit attempted external work')
    socket.socket.connect = forbidden
    GovernedCNYProvider.perform_request = forbidden
    CirclePackingDomain.evaluate = forbidden
    host_physical.run_stage = forbidden

    mori = json.loads((mori_root / 'config.json').read_text())
    vendor = json.loads((vendor_root / 'config.json').read_text())
    if type(seed) is not int or seed not in (0, 1, 2) or \
            any(type(c.get('seed')) is not int or c['seed'] != seed or c['ref'] != expected_ref
                for c in (mori, vendor)) or mori['plan'] != vendor['plan'] or \
            Path(mori['ledger']).resolve(strict=True) != expected_ledger or \
            Path(vendor['ledger']).resolve(strict=True) != expected_ledger:
        raise ValueError('pair configurations differ from the original plan')
    ledger = CampaignBudget(expected_ledger)
    if ledger.snapshot()['journal_head'] != expected_head:
        raise ValueError('campaign head differs from the requested audit head')
    mori_rows = list(ContinuationStore(Path(mori['output']) / 'framework' / 'x1.jsonl').read())
    vendor_rows = list(ContinuationStore(Path(vendor['output']) / 'events.jsonl').read())
    context = next(row['payload']['invocation']['external_context'] for row in mori_rows
                   if row['kind'] == 'composed_provider_started')
    mori_run, mori_plan = context['currency_run_id'], context['physical_plan_ref']
    vendor_run = ledger.reference_authority_claim(f'vendor-{seed}')['currency_run_id']
    vendor_plans = {row['payload']['plan_ref'] for row in vendor_rows if row['kind'] == 'governed_control_started'}
    if len(vendor_plans) != 1:
        raise ValueError('reference journal lacks one original physical plan')
    mori_view = RecordedCurrencyView(ledger.export_governance_evidence(mori_run, mori_plan),
                                     expected_run_id=mori_run, expected_head=expected_head)
    vendor_view = RecordedCurrencyView(ledger.export_governance_evidence(vendor_run, next(iter(vendor_plans))),
                                       expected_run_id=vendor_run, expected_head=expected_head)
    mori_clock = RecordedCellClock(_clock_evidence(mori['clock']), mori_view.cell_deadline_claim(f'mori-{seed}'))
    vendor_clock = RecordedCellClock(_clock_evidence(vendor['clock']), vendor_view.cell_deadline_claim(f'vendor-{seed}'))
    replay_input = json.loads((Path(mori['output']) / 'replay-input.json').read_text())
    reference_bundle = json.loads((Path(vendor['output']) / 'reference-currency.json').read_text())
    runner = SandboxRunner.for_campaign_runtime(ledger, runtime=mori['runtime'], manifest=mori['runtime_manifest'],
                                                base_python='/usr/bin/python3.12')
    result = audit_replayed_supervised_pair(replay_input=replay_input, ledger=ledger, runner=runner,
        replay_output=replay_output, mori_config=mori, reference_config=vendor,
        mori_supervisor_directory=mori_root, reference_supervisor_directory=vendor_root,
        seed=seed, plan=mori['plan'], expected_plan_ref=expected_ref,
        mori_rows=mori_rows, mori_rows_sha256=payload_digest(mori_rows), mori_view=mori_view,
        mori_clock=mori_clock, mori_run_id=mori_run, reference_rows=vendor_rows, reference_view=vendor_view,
        reference_clock=vendor_clock, reference_run_id=vendor_run,
        reference_worker_directory=vendor['worker_directory'], reference_bundle=reference_bundle)
    out = {key: result[key] for key in ('scope', 'seed', 'plan_ref', 'journal_head', 'performance_claim',
                                        'mori', 'reference', 'sum_radii_difference', 'replay')}
    print(json.dumps(out, sort_keys=True, ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
