"""Check the pinned reference notebook's best-fit benchmark without generated code."""
import argparse
import ast
import bisect
import hashlib
import json
import math
from pathlib import Path

NOTEBOOK_SHA256 = 'eec45846a8661722addbb856179327cf2ede0bc502e32be4ad58a6ac54e0aca6'


def datasets(path):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != NOTEBOOK_SHA256:
        raise ValueError('notebook differs from the pinned reference')
    notebook = json.loads(raw)
    source = ''.join(notebook['cells'][2]['source'])
    result = {}
    for node in ast.parse(source).body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if (isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name)
                and target.value.id == 'datasets' and isinstance(target.slice, ast.Constant)
                and target.slice.value in {'OR3', 'Weibull 5k'}):
            result[target.slice.value] = ast.literal_eval(node.value)
    if set(result) != {'OR3', 'Weibull 5k'}:
        raise ValueError('pinned reference datasets are missing')
    return result


def best_fit(instance):
    capacity, items = instance['capacity'], instance['items']
    if len(items) != instance['num_items'] or not items or any(not 0 < item <= capacity for item in items):
        raise ValueError('invalid bin-packing instance')
    residuals = []
    for item in items:
        index = bisect.bisect_left(residuals, item)
        if index == len(residuals):
            remaining = capacity - item
        else:
            remaining = residuals.pop(index) - item
        bisect.insort(residuals, remaining)
    return len(residuals)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('notebook')
    args = parser.parse_args()
    report = {}
    for name, instances in datasets(args.notebook).items():
        scores = [best_fit(instance) for instance in instances.values()]
        bounds = [math.ceil(sum(instance['items']) / instance['capacity']) for instance in instances.values()]
        mean, lower = sum(scores) / len(scores), sum(bounds) / len(bounds)
        report[name] = {'instances': len(scores), 'average_bins': mean, 'average_l1_bound': lower,
                        'excess_percent': 100 * (mean - lower) / lower}
    print(json.dumps({'schema_version': 1, 'method': 'best_fit_reference_baseline',
                      'notebook_sha256': NOTEBOOK_SHA256, 'results': report}, indent=2))


if __name__ == '__main__':
    main()
