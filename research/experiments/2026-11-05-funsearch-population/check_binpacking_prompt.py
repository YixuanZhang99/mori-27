"""Exercise prompt construction with the pinned public bin-packing skeleton."""
import ast
import hashlib
import json
from pathlib import Path
import sys
from core.funsearch_prompt import build_prompt

raw = Path(sys.argv[1]).read_bytes()
expected = 'eec45846a8661722addbb856179327cf2ede0bc502e32be4ad58a6ac54e0aca6'
if hashlib.sha256(raw).hexdigest() != expected:
    raise ValueError('pinned notebook hash differs')
notebook = json.loads(raw)
matches = []
for cell in notebook['cells']:
    source = ''.join(cell.get('source', []))
    if cell.get('cell_type') != 'code':
        continue
    try:
        parsed = ast.parse(source)
    except SyntaxError:
        continue
    targets = [node for node in parsed.body if isinstance(node, ast.FunctionDef) and node.name == 'priority']
    if len(targets) == 1 and parsed.body[-1] is targets[0]:
        matches.append((source, ast.get_source_segment(source, targets[0])))
if len(matches) != 1:
    raise ValueError('expected one final priority function in notebook')
template, seed = matches[0]
result = build_prompt(template, 'priority', ['seed', 'seed'], {'seed': seed})
tree = ast.parse(result['prompt'])
names = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
assert names[-3:] == ['priority_v0', 'priority_v1', 'priority_v2']
assert all(name in names for name in ('get_valid_bin_indices', 'online_binpack', 'evaluate'))
print(json.dumps({'reference_commit':'cc53f274237d7ab05c19df939edbc1f9616a7c19',
                  'notebook_sha256':expected, 'prompt_ref':result['prompt_ref'],
                  'input_ref':result['input_ref'], 'duplicate_samples_preserved':True,
                  'executed_candidate':False, 'provider_requests':0,
                  'scope':'prompt fixture only; no task evaluation or benchmark score'}, indent=2))
