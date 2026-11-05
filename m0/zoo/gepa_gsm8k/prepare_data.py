"""Prepare C01 from the pinned official GSM8K train.jsonl and test.jsonl files."""
import hashlib
import json
from pathlib import Path

REVISION = '3101c7d5072418e28b9008a6636bde82a006892c'
SOURCE_SHA256 = {
    'train': '17f347dc51477c50d4efb83959dbb7c56297aba886e5544ee2aaed3024813465',
    'test': '3730d312f6e3440559ace48831e51066acaca737f6eabec99bccb9e4b3c39d14',
}


def prepare(source, output):
    source, output = Path(source), Path(output)
    if output.exists():
        raise ValueError('preparation requires a new output directory')
    loaded = {}
    for split, expected in SOURCE_SHA256.items():
        raw = (source / (split + '.jsonl')).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('official source hash differs: ' + split)
        loaded[split] = [{'id': f'gsm8k:{REVISION}:{split}:{index:06d}',
            'question': row['question'], 'answer': row['answer']}
            for index, row in enumerate(json.loads(line) for line in raw.splitlines() if line.strip())]
        if len(loaded[split]) < 128:
            raise ValueError('official source has too few rows')
    splits = {'train': loaded['train'][:64], 'validation': loaded['train'][64:128],
              'test': loaded['test'][:128]}
    from zoo.gepa_gsm8k.domain import FrozenDataset
    FrozenDataset.from_rows(splits)
    manifest = {'source': {'repository': 'openai/grade-school-math', 'revision': REVISION,
        'sha256': dict(SOURCE_SHA256)}, 'splits': {}, 'seeds': [0, 1, 2],
        'minibatch_size': 8, 'max_proposals': 10}
    content = {}
    for split, values in splits.items():
        content[split] = ''.join(json.dumps(row, sort_keys=True, ensure_ascii=False) + '\n' for row in values).encode()
        manifest['splits'][split] = {'count': len(values),
            'sha256': hashlib.sha256(content[split]).hexdigest(),
            'first_id': values[0]['id'], 'last_id': values[-1]['id']}
    output.mkdir(parents=True)
    for split, raw in content.items():
        (output / (split + '.jsonl')).write_bytes(raw)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    prepare(args.source_dir, args.output)
    print(str((args.output / 'manifest.json').resolve()))


if __name__ == '__main__':
    main()
