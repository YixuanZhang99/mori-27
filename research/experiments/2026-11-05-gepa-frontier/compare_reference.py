"""Compare winner frequencies to a separately downloaded pinned GEPA helper."""
import argparse, hashlib, importlib.util, json, random
from pathlib import Path
from core.frontier.gepa import InstanceFrontier

REFERENCE_SHA256 = '6b9d546d9b8c7e6dd3fb17807f50ba2dcd2108f6232beb456f8951820ba3fa16'
parser = argparse.ArgumentParser()
parser.add_argument('--reference', type=Path, required=True)
args = parser.parse_args()
if hashlib.sha256(args.reference.read_bytes()).hexdigest() != REFERENCE_SHA256:
    raise ValueError('reference bytes do not match the recorded pinned helper')
spec = importlib.util.spec_from_file_location('pinned_gepa_utils', args.reference)
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)
rng = random.Random(91234)
checked = skipped = 0
for _ in range(200):
    items = [str(i) for i in range(5)]
    scores = [[rng.randrange(6) + idx / 1000 for _ in items] for idx in range(6)]
    if len({sum(row) for row in scores}) != len(scores):
        skipped += 1
        continue
    frontier = InstanceFrontier(items, seed=5)
    for index, row in enumerate(scores):
        frontier.offer(str(index), dict(zip(items, row)))
    winners = {key: {int(candidate) for candidate in value} for key, value in frontier.winners().items()}
    retained = reference.remove_dominated_programs(winners, [sum(row) / len(row) for row in scores])
    expected = {str(i): sum(i in value for value in retained.values()) for i in range(len(scores))
                if any(i in value for value in retained.values())}
    if frontier.frequencies() != expected:
        raise AssertionError('frontier frequencies differ from pinned GEPA reference')
    checked += 1
print(json.dumps({'passed': True, 'cases_checked': checked, 'aggregate_ties_skipped': skipped,
                  'reference_commit': '3d34469165f0d604df3b48f1d5c776e9080f3da0',
                  'reference_sha256': REFERENCE_SHA256, 'benchmark_result': False}))
