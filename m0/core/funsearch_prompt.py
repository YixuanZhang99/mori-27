"""Construct a bounded versioned-program prompt; not a provider or sandbox.

Candidates are single functions with the frozen target signature. Python AST
rendering normalizes formatting and comments, so byte parity with upstream's
text formatter is not claimed. The caller must journal and authenticate the
selection and projected candidate evidence before using the resulting prompt.
"""
from __future__ import annotations

import ast
import copy
from core.x1.checkpoint import payload_digest


def _function(source, *, label):
    if type(source) is not str or not source.strip():
        raise ValueError(label + ' must be nonempty source')
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        raise ValueError(label + ' must parse as Python') from exc
    return tree


def _signature(function):
    return (ast.dump(function.args, include_attributes=False),
            ast.dump(function.returns, include_attributes=False) if function.returns else None,
            tuple(ast.dump(param, include_attributes=False) for param in getattr(function, 'type_params', [])))


class _Calls(ast.NodeTransformer):
    def __init__(self, old, new):
        self.old, self.new = old, new
    def visit_Call(self, node):
        self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id == self.old:
            node.func.id = self.new
        return node


def _reject_shadowing(function, name):
    for node in ast.walk(function):
        if (isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, (ast.Store, ast.Del))) or \
                (isinstance(node, ast.arg) and node.arg == name) or \
                (isinstance(node, ast.alias) and (node.asname or node.name.split('.')[0]) == name) or \
                (isinstance(node, ast.ExceptHandler) and node.name == name) or \
                (isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name == name) or \
                (isinstance(node, ast.MatchMapping) and node.rest == name) or \
                (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node is not function and node.name == name) or \
                (isinstance(node, (ast.Global, ast.Nonlocal)) and name in node.names):
            raise ValueError('candidate shadows the recursive function name')


def build_prompt(template, function_name, samples, candidates):
    if type(function_name) is not str or not function_name.isidentifier():
        raise ValueError('target must be a Python identifier')
    if type(samples) is not list or not samples or any(type(x) is not str or not x for x in samples):
        raise ValueError('ordered sampled candidate identities are required')
    if type(candidates) is not dict or any(key not in candidates for key in samples):
        raise ValueError('every sampled candidate must be supplied')
    tree = _function(template, label='template')
    targets = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name]
    if len(targets) != 1 or not isinstance(targets[0], ast.FunctionDef) or tree.body[-1] is not targets[0] or targets[0].decorator_list:
        raise ValueError('template target must be one undecorated final top-level function')
    target = targets[0]
    signature = _signature(target)
    sources = {}
    versions = []
    for index, candidate_id in enumerate(samples):
        source = candidates[candidate_id]
        candidate_tree = _function(source, label='candidate')
        if len(candidate_tree.body) != 1 or not isinstance(candidate_tree.body[0], ast.FunctionDef):
            raise ValueError('candidate must contain exactly one synchronous function')
        candidate = candidate_tree.body[0]
        if candidate.name != function_name or candidate.decorator_list or _signature(candidate) != signature:
            raise ValueError('candidate differs from frozen target signature')
        _reject_shadowing(candidate, function_name)
        sources[candidate_id] = source
        candidate.name = f'{function_name}_v{index}'
        candidate = _Calls(function_name, candidate.name).visit(candidate)
        if index:
            doc = ast.Expr(value=ast.Constant(value=f'Improved version of `{function_name}_v{index - 1}`.'))
            if candidate.body and isinstance(candidate.body[0], ast.Expr) and isinstance(candidate.body[0].value, ast.Constant) and isinstance(candidate.body[0].value.value, str):
                candidate.body[0] = doc
            else:
                candidate.body.insert(0, doc)
        versions.append(ast.unparse(ast.fix_missing_locations(candidate)))
    next_function = copy.deepcopy(target)
    next_function.name = f'{function_name}_v{len(samples)}'
    next_function.body = [ast.Expr(value=ast.Constant(value=f'Improved version of `{function_name}_v{len(samples) - 1}`.'))]
    header = ast.unparse(ast.fix_missing_locations(next_function))
    prefix = ''.join(template.splitlines(keepends=True)[:target.lineno - 1]).rstrip()
    prompt = (prefix + '\n\n' if prefix else '') + '\n\n'.join([*versions, header]) + '\n    '
    binding = {'template': template, 'function': function_name, 'samples': samples, 'sources': sources}
    return {'prompt': prompt, 'prompt_header_version': len(samples),
            'reference_version_generated': len(samples) + 1, 'samples': list(samples),
            'input_ref': 'sha256:' + payload_digest(binding), 'prompt_ref': 'sha256:' + payload_digest(prompt)}
