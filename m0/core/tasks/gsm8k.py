"""GSM8K-style deterministic task evaluator for prompt-evolution loads.

Dataset JSONL rows: {"question": ..., "answer": "... #### 42"} or
{"question": ..., "answer": 42}. The candidate is the solver's instruction prompt.
Scoring is per-item exact numeric match; feedback is textual and never enters M9.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from core.eval.types import EvalResult, ItemResult, ReliabilityMeta
from core.llm import reset_usage, take_usage

_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_SCORING_RULE = "gsm8k-final-number-absolute-tolerance-1e-6-v1"


def _canonical(value) -> bytes:
    def validate(item):
        if item is None or type(item) in (str, bool, int):
            return
        if type(item) is float and math.isfinite(item):
            return
        if isinstance(item, (list, tuple)):
            for child in item:
                validate(child)
            return
        if isinstance(item, dict) and all(type(key) is str for key in item):
            for child in item.values():
                validate(child)
            return
        raise ValueError("evaluation identity must contain finite JSON values and string keys")
    validate(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def _digest(value) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _solver_identity(solver) -> dict:
    """Capture public generation settings; never hash credentials or usage state.

    Custom adapters with additional output-affecting configuration should expose
    a JSON ``evaluation_identity`` mapping (or a pure zero-argument callable).
    An opaque adapter's class identity cannot certify undeclared configuration.
    """
    adapter = solver if hasattr(solver, "__qualname__") else type(solver)
    identity = {"adapter": f"{adapter.__module__}.{adapter.__qualname__}", "settings": {}}
    for name in ("supplier", "model", "model_version", "revision", "tokenizer_version",
                 "temperature", "top_p", "max_tokens", "seed"):
        if hasattr(solver, name):
            identity["settings"][name] = getattr(solver, name)
    if hasattr(solver, "base_url"):
        value = solver.base_url
        if not isinstance(value, str):
            raise ValueError("solver base_url must be a string")
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        if parsed.port is not None:
            host += f":{parsed.port}"
        credential_names = {"key", "api_key", "apikey", "access_token", "token",
                            "password", "secret", "signature", "authorization"}
        query = [(key, "<credential>" if key.lower().replace("-", "_") in
                  credential_names else value) for key, value in
                 parse_qsl(parsed.query, keep_blank_values=True)]
        identity["settings"]["base_url"] = urlunsplit(
            (parsed.scheme, host, parsed.path.rstrip("/"), urlencode(query), ""))
    declared = getattr(solver, "evaluation_identity", None)
    if declared is not None:
        declared = declared() if callable(declared) else declared
        if not isinstance(declared, dict):
            raise ValueError("solver evaluation_identity must be a JSON mapping")
        identity["declared"] = declared
    # Round-trip severs aliases held by a mutable metadata implementation.
    return json.loads(_canonical(identity))


@dataclass(frozen=True)
class _Item:
    question: str
    gold: float


def extract_number(text: str) -> float | None:
    """Prefer an explicit #### answer; otherwise use the final numeric token."""
    if "####" in text:
        text = text.rsplit("####", 1)[1]
    matches = _NUMBER.findall(text.replace("$", ""))
    if not matches:
        return None
    return float(matches[-1].replace(",", ""))


def load_jsonl(path: str | Path, limit: int | None = None) -> list[dict]:
    items = []
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            gold = extract_number(str(row["answer"]))
            if gold is None:
                raise ValueError(f"unparseable gold answer: {row['answer']!r}")
            items.append({"question": row["question"], "gold": gold})
            if limit is not None and len(items) >= limit:
                break
    if not items:
        raise ValueError("empty evaluation set")
    return items


class GSM8KEvaluator:
    def __init__(self, items: list[dict], solver_llm: Callable[[str], str],
                 evaluator_version: str = "gsm8k-det-v1", max_feedback: int = 3):
        if not callable(solver_llm):
            raise ValueError("GSM8K solver must be callable")
        if not isinstance(items, (list, tuple)) or not items:
            raise ValueError("GSM8K evaluation requires a non-empty dataset")
        frozen = []
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("question"), str) \
                    or not item["question"].strip():
                raise ValueError("GSM8K questions must be non-empty strings")
            gold = item.get("gold")
            if type(gold) not in (int, float):
                raise ValueError("GSM8K gold answers must be finite numbers")
            try:
                gold = float(gold)
            except (OverflowError, ValueError) as exc:
                raise ValueError("GSM8K gold answers must be finite numbers") from exc
            if not math.isfinite(gold):
                raise ValueError("GSM8K gold answers must be finite numbers")
            frozen.append(_Item(item["question"], gold + 0.0))
        if not isinstance(evaluator_version, str) or not evaluator_version.strip():
            raise ValueError("evaluator_version must be non-empty")
        if type(max_feedback) is not int or max_feedback < 0:
            raise ValueError("max_feedback must be a non-negative integer")
        self._items = tuple(frozen)
        self.solver_llm = solver_llm
        self.evaluator_version = evaluator_version
        self.max_feedback = max_feedback
        self.last_usage = {"total_tokens": 0}
        self._solver_context = _digest(_solver_identity(self.solver_llm))
        self._evaluation_context = _digest(self._context_payload())

    @property
    def items(self) -> list[dict]:
        """Return a detached view; callers cannot mutate the evaluation dataset."""
        return [{"question": item.question, "gold": item.gold} for item in self._items]

    def _context_payload(self) -> dict:
        return {"schema_version": 1, "dataset": self.items,
                "scoring_rule": _SCORING_RULE, "evaluator_version": self.evaluator_version,
                "max_feedback": self.max_feedback, "solver": _solver_identity(self.solver_llm)}

    @property
    def evaluation_context(self) -> str:
        return self._evaluation_context

    def validate_context(self) -> None:
        """Pure preflight usable before proposal calls or ledger mutations."""
        if _digest(self._context_payload()) != self._evaluation_context:
            raise ValueError("GSM8K evaluation configuration changed; create a new evaluator")

    def __call__(self, candidate_id: str, head_sha: str, prompt: str,
                 item_limit: int | None = None) -> EvalResult:
        results: list[ItemResult] = []
        failures: list[str] = []
        total_usage = 0
        self.last_usage = {"total_tokens": 0}
        self.validate_context()
        if item_limit is not None and (type(item_limit) is not int or item_limit < 1):
            raise ValueError("item_limit must be a positive integer or None")
        selected_items = self._items if item_limit is None else self._items[:item_limit]
        for idx, item in enumerate(selected_items):
            solver_prompt = (f"{prompt}\n\nQuestion: {item.question}\n"
                             "End your response with '#### <number>'.")
            reset_usage(self.solver_llm)
            self.last_usage = None  # cost of this invocation is not yet known
            try:
                output = self.solver_llm(solver_prompt)
            finally:
                total_usage += take_usage(self.solver_llm)
                self.last_usage = {"total_tokens": total_usage}
            if _digest(_solver_identity(self.solver_llm)) != self._solver_context:
                raise ValueError("GSM8K solver configuration changed during evaluation")
            pred = extract_number(output)
            gold = item.gold
            ok = pred is not None and abs(pred - gold) < 1e-6
            results.append(ItemResult(item_id=f"gsm8k-{idx}", verdict=1 if ok else 0))
            if not ok and len(failures) < self.max_feedback:
                failures.append(
                    f"gsm8k-{idx}: question={item.question}; expected={gold:g}; "
                    f"predicted={pred}; solver_output={output[:400]}")
        self.last_usage = {"total_tokens": total_usage}
        if _digest(self._context_payload()) != self._evaluation_context:
            raise ValueError("GSM8K evaluation configuration changed during evaluation")
        score = sum(r.verdict for r in results) / len(results)
        feedback = ("All evaluation items solved." if not failures else
                    "Failed examples and expected answers:\n" + "\n".join(failures))
        return EvalResult(candidate_id=candidate_id, head_sha=head_sha,
                          items=results, combined_score=score,
                          public={"score": score}, private={"gold_count": len(results)},
                          text_feedback=feedback,
                          reliability=ReliabilityMeta(n_trials=1, noise_floor=0.0),
                          evaluator_version=self.evaluator_version,
                          evaluation_context=self.evaluation_context)
