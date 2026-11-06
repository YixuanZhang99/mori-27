"""Persist and bind a clean source bundle without starting a pilot cell."""
import argparse
import json
from pathlib import Path

from zoo.circle_packing.pilot_draft import _read_private_json, freeze_source_bundle
from zoo.mle_bench_lite.cny_budget import CampaignBudget


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('ledger', 'plan', 'expected-plan-ref', 'checkout', 'directory'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    result = freeze_source_bundle(CampaignBudget(args.ledger), plan=_read_private_json(Path(args.plan)),
        expected_plan_ref=args.expected_plan_ref, checkout=args.checkout, directory=args.directory)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
