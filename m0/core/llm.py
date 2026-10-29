"""OpenAI-compatible LLM adapter (stdlib only) with token usage metering.

The adapter is used only by operators/task solvers on the execution side. M1/M3/M9
never import it. Tests exercise request construction without making network calls.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any


class UsageError(ValueError):
    """A completed operation has no trustworthy token-cost evidence."""


def validate_usage(usage) -> dict[str, int]:
    """Require explicit provider totals; never coerce or estimate missing usage."""
    if not isinstance(usage, dict) or "total_tokens" not in usage:
        raise UsageError("missing token usage: explicit total_tokens is required")
    result = {}
    for key in ("total_tokens", "prompt_tokens", "completion_tokens"):
        if key not in usage:
            continue
        value = usage[key]
        if type(value) is not int or value < 0:
            raise UsageError(f"{key} must be a non-negative integer")
        result[key] = value
    if "prompt_tokens" in result and "completion_tokens" in result \
            and result["prompt_tokens"] + result["completion_tokens"] != result["total_tokens"]:
        raise UsageError("token usage components do not match total_tokens")
    return result


def reset_usage(obj) -> None:
    """Mark a new invocation pending, so stale usage cannot certify its cost."""
    try:
        obj.last_usage = None
    except Exception as exc:
        raise UsageError("token meter cannot be reset before invocation") from exc


class OpenAICompatibleLLM:
    def __init__(self, model: str, base_url: str = "https://api.openai.com/v1",
                 api_key: str | None = None, temperature: float = 0.0,
                 timeout: float = 120.0, supplier: str = "openai"):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY", "")
        self.temperature = temperature
        self.timeout = timeout
        self.supplier = supplier
        self.last_usage: dict[str, int] | None = None

    def build_payload(self, prompt: str) -> dict[str, Any]:
        """Deterministic request construction (temperature fixed by config)."""
        return {"model": self.model, "temperature": self.temperature,
                "messages": [{"role": "user", "content": prompt}]}

    @staticmethod
    def parse_response(data: dict) -> tuple[str, dict[str, int]]:
        content = data["choices"][0]["message"]["content"]
        usage = validate_usage(data.get("usage"))
        return content, usage

    def __call__(self, prompt: str) -> str:
        reset_usage(self)
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY (or api_key=) is required")
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(self.build_payload(prompt)).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        # A malformed content payload does not erase known provider charges.
        self.last_usage = validate_usage(data.get("usage"))
        content, self.last_usage = self.parse_response(data)
        return content


def take_usage(obj) -> int:
    """Consume known usage exactly once; unknown costs block settlement."""
    total = validate_usage(getattr(obj, "last_usage", None))["total_tokens"]
    try:
        obj.last_usage = {"total_tokens": 0}
    except Exception as exc:
        raise UsageError("token meter cannot be consumed exactly once") from exc
    return total
