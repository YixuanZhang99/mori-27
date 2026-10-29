"""OpenAI-compatible LLM adapter (stdlib only) with token usage metering.

The adapter is used only by operators/task solvers on the execution side. M1/M3/M9
never import it. Tests exercise request construction without making network calls.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any


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
        self.last_usage: dict[str, int] = {"total_tokens": 0}

    def build_payload(self, prompt: str) -> dict[str, Any]:
        """Deterministic request construction (temperature fixed by config)."""
        return {"model": self.model, "temperature": self.temperature,
                "messages": [{"role": "user", "content": prompt}]}

    @staticmethod
    def parse_response(data: dict) -> tuple[str, dict[str, int]]:
        content = data["choices"][0]["message"]["content"]
        usage_raw = data.get("usage", {})
        usage = {"total_tokens": int(usage_raw.get("total_tokens", 0)),
                 "prompt_tokens": int(usage_raw.get("prompt_tokens", 0)),
                 "completion_tokens": int(usage_raw.get("completion_tokens", 0))}
        return content, usage

    def __call__(self, prompt: str) -> str:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY (or api_key=) is required")
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(self.build_payload(prompt)).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content, self.last_usage = self.parse_response(data)
        return content


def take_usage(obj) -> int:
    """Read and reset an object's total token meter; unmetered objects cost 0."""
    usage = getattr(obj, "last_usage", None) or {}
    total = int(usage.get("total_tokens", 0))
    if hasattr(obj, "last_usage"):
        obj.last_usage = {"total_tokens": 0}
    return total
