"""OpenEvolve evaluator entry; initialized independently inside host workers."""
from __future__ import annotations

from zoo.mle_bench_lite.agent_common import (
    extract_generator_prompt, runtime_from_environment)

_RUNTIME = None


def evaluate(program_path: str) -> dict[str, float]:
    global _RUNTIME
    try:
        if _RUNTIME is None:
            _RUNTIME = runtime_from_environment()
        with open(program_path, encoding="utf-8") as handle:
            prompt = extract_generator_prompt(handle.read())
        outcome = _RUNTIME.evaluate_prompt(prompt_digest_id(program_path), prompt)
        return {"combined_score": float(outcome["valid_submission"]),
                "dev_valid_submission": float(outcome["valid_submission"])}
    except Exception:
        # Host search receives only a failed dev candidate. Raw grader reports and
        # exceptions never become synthetic external benchmark measurements.
        return {"combined_score": 0.0, "dev_valid_submission": 0.0}


def prompt_digest_id(program_path: str) -> str:
    import hashlib
    return "host:" + hashlib.sha256(program_path.encode("utf-8")).hexdigest()[:16]
