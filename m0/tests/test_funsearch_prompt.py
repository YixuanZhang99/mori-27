import ast
import pytest
from core.funsearch_prompt import build_prompt

TEMPLATE = '''import math\n\ndef helper(x):\n    return x + 1\n\ndef priority(x: float) -> float:\n    """Initial priority."""\n    return helper(x)\n'''
CANDIDATES = {
    'recursive': '''def priority(x: float) -> float:\n    if x <= 0:\n        return 0\n    return priority(x - 1) + obj.priority(x)\n''',
    'simple': '''def priority(x: float) -> float:\n    return x + 2\n''',
}


def test_versioned_prompt_preserves_repeated_samples_and_recursion():
    result = build_prompt(TEMPLATE, 'priority', ['recursive', 'simple', 'recursive'], CANDIDATES)
    assert result['samples'] == ['recursive', 'simple', 'recursive']
    assert result['prompt_header_version'] == 3
    assert result['prompt'].startswith('import math\n\ndef helper(x):')
    tree = ast.parse(result['prompt'])
    names = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
    assert names == ['helper', 'priority_v0', 'priority_v1', 'priority_v2', 'priority_v3']
    assert 'priority_v0(x - 1)' in result['prompt']
    assert 'priority_v2(x - 1)' in result['prompt']
    assert 'obj.priority(x)' in result['prompt']
    assert result['prompt'].endswith('    ')
    assert result == build_prompt(TEMPLATE, 'priority', ['recursive', 'simple', 'recursive'], CANDIDATES)


def test_rejects_scaffold_changes_invalid_candidates_and_missing_samples():
    invalid = [
        'def priority(x: int) -> float:\n    return x\n',
        'def priority(x: float) -> float:\n    return x\n\nimport os\n',
        '@decorator\ndef priority(x: float) -> float:\n    return x\n',
        'async def priority(x: float) -> float:\n    return x\n',
    ]
    for code in invalid:
        with pytest.raises(ValueError):
            build_prompt(TEMPLATE, 'priority', ['bad'], {'bad': code})
    with pytest.raises(ValueError):
        build_prompt(TEMPLATE, 'priority', ['missing'], CANDIDATES)
    with pytest.raises(ValueError):
        build_prompt(TEMPLATE + '\nprint(1)\n', 'priority', ['simple'], CANDIDATES)
    with pytest.raises(ValueError):
        build_prompt(TEMPLATE, 'priority', [], CANDIDATES)


def test_generic_type_parameters_are_compared_structurally():
    template = 'def identity[T](x: T) -> T:\n    return x\n'
    candidate = 'def identity[T](x: T) -> T:\n    return x\n'
    result = build_prompt(template, 'identity', ['a'], {'a': candidate})
    assert 'def identity_v0[T]' in result['prompt']
    with pytest.raises(ValueError):
        build_prompt(template, 'identity', ['a'], {'a': 'def identity[U](x: U) -> U:\n    return x\n'})


def test_recursive_name_shadowing_is_rejected_before_rewriting():
    candidates = [
        'def priority(x: float) -> float:\n    from math import sqrt as priority\n    return priority(x)\n',
        'def priority(x: float) -> float:\n    try:\n        return 0\n    except Exception as priority:\n        return priority(x)\n',
    ]
    for source in candidates:
        with pytest.raises(ValueError, match='shadows'):
            build_prompt(TEMPLATE, 'priority', ['a'], {'a': source})


def test_reference_version_convention_is_reported_separately():
    result = build_prompt(TEMPLATE, 'priority', ['simple'], CANDIDATES)
    assert result['prompt_header_version'] == 1
    assert result['reference_version_generated'] == 2
