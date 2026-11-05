"""Recompute published OR3 summaries from original records; no model or sandbox."""
import argparse
import gzip
from pathlib import Path

from export_runs import read, require, summarize


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('root', nargs='?', type=Path, default=Path(__file__).resolve().parent)
    args = p.parse_args()
    summaries = []
    for run in sorted(args.root.glob('seed-*')):
        summary, programs = summarize(read(run / 'run-manifest.json'),
            (run / 'baseline-reference.json').read_bytes(), gzip.decompress((run / 'x1.jsonl.gz').read_bytes()),
            read(run / 'currency-receipts.json.gz'), read(run / 'method-report.json.gz'))
        require(summary == read(run / 'summary.json'), 'summary differs: ' + run.name)
        require(programs == read(run / 'programs.json.gz'), 'program export differs')
        if summary['best_development']:
            require((run / 'selected-program.py').read_text() == programs[summary['best_development']['candidate_id']], 'selected program differs')
        summaries.append(summary)
    require(bool(summaries), 'no attempts exported')
    require(summaries == read(args.root / 'summary.json')['runs'], 'batch summary differs')
    for s in summaries:
        print(f"seed={s['seed']} held_out={s['held_out']['mean_bins']} search={s['search']} cost={s['currency']['cost_upper_micro_cny']}")


if __name__ == '__main__':
    main()
