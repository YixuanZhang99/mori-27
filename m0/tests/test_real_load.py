"""Real-load adapters, public API, profiles and protocol extensions."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.extensions import H2MonitorExtension, NoveltyGateExtension
from core.llm import OpenAICompatibleLLM
from core.loop import Framework, LoopConfig
from core.profiles import extensions_for, load_profile
from core.tasks.gsm8k import GSM8KEvaluator, extract_number
from examples.toy_gepa import MockLLM, toy_evaluator


def test_numeric_extraction():
    assert extract_number("reasoning\n#### 1,234.5") == 1234.5
    assert extract_number("The answer is $-42.") == -42
    assert extract_number("first 3, then 7") == 7
    assert extract_number("no numbers") is None


def test_gsm8k_evaluator_per_item_feedback_and_metering():
    items = [{"question": "1+1?", "gold": 2.0},
             {"question": "2+2?", "gold": 4.0}]

    class Solver:
        def __init__(self):
            self.last_usage = {"total_tokens": 0}

        def __call__(self, prompt):
            self.last_usage = {"total_tokens": 5}
            return "#### 2" if "1+1" in prompt else "I do not know"

    ev = GSM8KEvaluator(items, Solver())
    result = ev("cand", "sha", "Solve accurately")
    assert [i.verdict for i in result.items] == [1, 0]
    assert result.combined_score == 0.5
    assert "expected=4" in result.text_feedback
    assert result.evaluator_version == "gsm8k-det-v1"
    assert ev.last_usage["total_tokens"] == 10


def test_openai_adapter_offline_request_and_response():
    llm = OpenAICompatibleLLM("test-model", api_key="x", temperature=0.0)
    assert llm.build_payload("hello") == {
        "model": "test-model", "temperature": 0.0,
        "messages": [{"role": "user", "content": "hello"}]}
    content, usage = llm.parse_response({
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"total_tokens": 12, "prompt_tokens": 8, "completion_tokens": 4}})
    assert content == "ok" and usage["total_tokens"] == 12


def test_public_api_replay_and_inspect(tmp_path):
    fw = Framework(MockLLM(), toy_evaluator, LoopConfig(max_generations=12),
                   str(tmp_path / "run"))
    first = fw.evolve("toy")
    inspection = fw.inspect()
    assert inspection["self_attestation_pass"] is True
    assert inspection["accepted_receipt_coverage"] is True
    assert inspection["governance_pass"] is True
    assert inspection["ledger_reconciliation_pass"] is True
    assert inspection["stop_action_replay_pass"] is True
    assert inspection["receipt_count"] >= inspection["accepted_candidates"]
    assert inspection["formal_governance_pass"] is True
    assert inspection["baseline_resident"] is True
    assert inspection["replay_certified"] is False
    replay = fw.replay()
    for key in ("best_prompt", "best_score", "self_attestation", "governance_audit",
                "main_scores", "baseline_scores"):
        assert replay[key] == first[key]
    certificate = fw.inspect()["replay_certificate"]
    assert fw.inspect()["replay_certified"] is True
    assert certificate["passed"] is True
    assert certificate["snapshot_match"] is True
    assert certificate["receipt_chain_match"] is True
    assert certificate["result_match"] is True


def test_profiles_compile_without_kernel_changes():
    gepa = load_profile("gepa_reflective")
    funsearch = load_profile("funsearch_island")
    assert gepa["operators"]["improve"] == "llm_reflective"
    assert funsearch["operators"]["improve"] == "llm_evolve_block"
    assert extensions_for(gepa) == []
    assert isinstance(extensions_for(funsearch)[0], NoveltyGateExtension)


def test_gepa_profile_runs_through_public_api(tmp_path):
    fw = Framework.from_profile("gepa_reflective", MockLLM(), toy_evaluator,
                                LoopConfig(max_generations=4), str(tmp_path))
    assert fw.evolve("toy")["best_score"] > 0.33


def test_novelty_and_h2_extensions_execute():
    gate = NoveltyGateExtension(threshold=0.9)
    proposal = type("P", (), {"patch_text": "abcdef"})()
    pool = [{"candidate_id": "old", "prompt": "abcdef"}]
    assert "novelty_gate" in gate.admission_veto(proposal, None, pool)
    monitor = H2MonitorExtension(window=2, min_effective_parents=2)
    assert monitor.after_parent_selection(pool[0], 1) is None
    alarm = monitor.after_parent_selection(pool[0], 2)
    assert alarm["kind"] == "h2_collapse_alarm"


def test_gsm8k_offline_full_framework(tmp_path):
    from examples.gsm8k_offline import run
    out = run(workdir=str(tmp_path), generations=4)
    assert out["best_score"] == 1.0
    assert out["baseline_scores"] and all(s < 1.0 for s in out["baseline_scores"])
    # Real operator + solver token metering must settle below the fixed reserve.
    assert out["ledger"]["spent"]["explore"] < 500


def test_low_budget_reissues_lower_tiers(tmp_path):
    # Budget supports genesis + one full-cost improve; later reissues must halve.
    fw = Framework(MockLLM(), toy_evaluator,
                   LoopConfig(total_budget=3_000, intent_cost=1_000,
                              reeval_floor=100, max_generations=20),
                   str(tmp_path))
    out = fw.evolve("toy")
    assert out["ledger"]["spent"]["explore"] + out["ledger"]["spent"]["exploit"] <= 3_000
