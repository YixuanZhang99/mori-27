"""Shared source identity and synthetic CSV fixtures for named MLE recipes."""
# This constant program learns priors from the visible training table only.
# It is a plumbing fixture, not a research-method result or a competitive baseline.
FIXTURE_PROGRAM = '''import csv, json
from collections import Counter
with open('data/protocol.json') as f: protocol = json.load(f)
with open('data/train.csv') as f: train = list(csv.DictReader(f))
with open('data/predict.csv') as f: predict = list(csv.DictReader(f))
columns = protocol['output_columns']
if protocol['kind'] == 'classification':
    counts = Counter(row['target'] for row in train)
    values = [counts[name] / len(train) for name in columns[1:]]
else:
    values = [sum(float(row[name]) for row in train) / len(train) for name in columns[1:]]
with open('predictions.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(columns)
    writer.writerows([row['row_id'], *values] for row in predict)
'''


def source_identity():
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    try:
        return {'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root,
                    text=True, stderr=subprocess.DEVNULL).strip(),
                'dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=root,
                    text=True, stderr=subprocess.DEVNULL))}
    except (OSError, subprocess.CalledProcessError):
        return {'commit': None, 'dirty': None}


def fixture_data(root, task_id):
    """Small synthetic CSVs; no Kaggle access and no hidden labels in programs."""
    from zoo.mle_bench_lite.public_train import TASK_SPECS, write_csv
    if root.exists():
        return root
    root.mkdir(parents=True)
    spec = TASK_SPECS[task_id]
    if spec['kind'] == 'classification':
        classes = ['A', 'B', 'C']
        targets = [spec['target']]
        train = [{'id': str(i), 'x': i, targets[0]: classes[i % 3]} for i in range(60)]
        sample = [{'id': str(i), **{name: 1 / 3 for name in classes}} for i in range(4)]
        outputs = classes
    else:
        targets = outputs = spec['targets']
        train = [{'id': str(i), 'x': i, **{name: i / 10 + 1 for name in targets}} for i in range(60)]
        sample = [{'id': str(i), **{name: 0 for name in outputs}} for i in range(4)]
    write_csv(root / 'train.csv', ['id', 'x', *targets], train)
    write_csv(root / 'test.csv', ['id', 'x'], [{'id': str(i), 'x': i + 1000} for i in range(4)])
    write_csv(root / 'sample_submission.csv', ['id', *outputs], sample)
    return root


