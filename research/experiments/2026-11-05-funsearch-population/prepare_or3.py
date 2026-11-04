"""Prepare disjoint public OR3 files from the hash-pinned reference notebook."""
import argparse
import json
from pathlib import Path

from check_binpacking_baseline import NOTEBOOK_SHA256, datasets
from core.tasks.funsearch_binpacking import split_instances


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('notebook')
    parser.add_argument('output', type=Path, help='new output directory; existing paths are refused')
    args = parser.parse_args()
    splits = split_instances(datasets(args.notebook)['OR3'])
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = {'schema_version': 1, 'notebook_sha256': NOTEBOOK_SHA256,
                'split_rule': 'sorted instance id: first 10 dev, last 10 held_out', 'splits': {}}
    for label in ('dev', 'held_out'):
        part = splits[label]
        directory = args.output / label
        directory.mkdir()
        raw = json.dumps(part['instances'], sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        (directory / 'data.json').write_bytes(raw)
        manifest['splits'][label] = {'sha256': part['sha256'], 'count': len(part['instances'])}
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, sort_keys=True))


if __name__ == '__main__':
    main()
