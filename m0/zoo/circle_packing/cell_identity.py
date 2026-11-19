"""Legacy and version-qualified circle cell identities."""
from __future__ import annotations

import re


def parse_cell_identity(value):
    if type(value) is not str:
        raise ValueError('cell identity must be text')
    legacy = re.fullmatch(r'(vendor|mori)-(0|[1-9][0-9]*)', value)
    if legacy:
        return None, legacy.group(1), int(legacy.group(2))
    versioned = re.fullmatch(r'([A-Za-z0-9_-]{1,96})--(vendor|mori)-([012])', value)
    if versioned:
        return versioned.group(1), versioned.group(2), int(versioned.group(3))
    raise ValueError('cell identity has an unsupported format')
