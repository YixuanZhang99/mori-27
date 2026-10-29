"""v27 run/evidence isolation: mixed histories fail before any new spending."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.loop import Framework, LoopConfig
from examples.toy_gepa import MockLLM, toy_evaluator


def test_non_resume_run_cannot_mix_two_runs_in_one_evidence_store(tmp_path):
    config = LoopConfig(max_generations=2)
    fw = Framework(MockLLM(), toy_evaluator, config, str(tmp_path))
    fw.evolve("run isolation")
    before = len(list(fw.store.read()))
    other = Framework(MockLLM(), toy_evaluator, config, str(tmp_path))
    for candidate in (fw, other):
        with pytest.raises(ValueError, match="fresh evidence workdir"):
            candidate.evolve("run isolation")
        assert len(list(fw.store.read())) == before
        assert not list(candidate.store.read("batch_cycle_started"))
