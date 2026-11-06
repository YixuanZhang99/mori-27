"""Trusted Mori host credential handoff; it does not start a live search."""
from __future__ import annotations

import os


def _prepare(config, *, api_key):
    from zoo.circle_packing.mori_live_controller import prepare_live_controller
    return prepare_live_controller(config, api_key=api_key)


def prepare(config):
    """Remove the provider key from the environment before preparing children."""
    api_key = os.environ.pop('DEEPSEEK_API_KEY', None)
    if type(api_key) is not str or not api_key.strip():
        raise ValueError('live host requires an in-memory provider credential')
    return _prepare(config, api_key=api_key)
