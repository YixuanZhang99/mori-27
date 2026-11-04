"""Deterministic structural validation before evaluating a generated program."""
import ast

from core.funsearch_prompt import build_prompt


def program_validator(template, function_name):
    """Freeze a valid scaffold and return a non-executing materializer validator."""
    try:
        tree = ast.parse(template)
        targets = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                   and node.name == function_name]
        if len(targets) != 1:
            raise ValueError('one target function is required')
        source = ast.get_source_segment(template, targets[0])
        build_prompt(template, function_name, ['seed'], {'seed': source})
    except (SyntaxError, TypeError) as error:
        raise ValueError('invalid frozen FunSearch scaffold') from error

    def validate(artifact):
        try:
            build_prompt(template, function_name, ['candidate'], {'candidate': artifact})
        except (ValueError, TypeError, SyntaxError, UnicodeError):
            return ('Program must be one valid function with the frozen target signature.',)
        return ()

    return validate
