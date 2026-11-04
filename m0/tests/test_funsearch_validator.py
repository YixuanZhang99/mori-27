"""Validate generated programs before they reach an evaluator."""
from core.composition.funsearch_validator import program_validator


def test_validator_checks_signature_and_never_executes_program(tmp_path):
    marker = tmp_path / 'executed'
    template = 'def priority(x):\n    return x\n'
    validate = program_validator(template, 'priority')
    assert validate('def priority(x):\n    return x + 1\n') == ()
    invalid = f"open({str(marker)!r}, 'w').close()\ndef priority(x):\n    return x\n"
    assert validate(invalid)
    assert validate('def priority(x, y):\n    return x\n')
    assert not marker.exists()
