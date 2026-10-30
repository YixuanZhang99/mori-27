"""Auditable, non-retrying provider boundary for measured MLE pilot runs.

The returned model identifier, not just the requested alias, is evidence. Token
limits are physical totals; a response can exceed the remaining allowance due
to input tokens. Such usage is retained and makes the run ineligible.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from core.llm import UsageError, validate_usage
from zoo.mle_bench_lite.agent_common import token_usage_summary
from zoo.mle_bench_lite.usage_audit import audit_usage


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise RuntimeError("benchmark provider redirects are forbidden")


def _exclusive_json(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True, ensure_ascii=False, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


class BenchmarkProvider:
    """One receipt per actual HTTP request, with no automatic paid retries."""

    supplier = "openai-compatible-mle-pilot-v1"

    def __init__(self, model: str, base_url: str, usage_dir: str | Path,
                 token_budget: int, max_completion_tokens: int = 4096,
                 temperature: float = 0.0, timeout: float = 120.0,
                 api_key: str | None = None):
        if not isinstance(model, str) or not model.strip():
            raise ValueError("an explicit model is required")
        for name, value in (("token_budget", token_budget),
                            ("max_completion_tokens", max_completion_tokens)):
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if (type(temperature) not in (int, float) or not math.isfinite(temperature)
                or not 0 <= temperature <= 2):
            raise ValueError("temperature must be finite and in [0,2]")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        url = urllib.parse.urlsplit(base_url)
        if (not url.hostname or url.username or url.password or url.query or url.fragment
                or url.scheme not in {"https", "http"}
                or (url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1", "::1"})):
            raise ValueError("provider URL requires HTTPS (HTTP is only for loopback fixtures)")
        self.model, self.base_url = model, base_url.rstrip("/")
        self.usage_dir = Path(usage_dir)
        self.calls_dir = self.usage_dir.parent / (self.usage_dir.name + "_calls")
        self.token_budget, self.max_completion_tokens = token_budget, max_completion_tokens
        self.temperature, self.timeout = float(temperature), float(timeout)
        self.api_key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY", "")
        self.last_usage = {"total_tokens": 0}
        self.usage_dir.mkdir(parents=True, exist_ok=True)
        self.calls_dir.mkdir(parents=True, exist_ok=True)
        self.actual_model = None
        self._unresolved = False
        self._validate_existing()

    def manifest_binding(self) -> dict:
        return {"schema_version": 1, "requested_model": self.model,
                "base_url": self.base_url, "temperature": self.temperature,
                "max_completion_tokens": self.max_completion_tokens,
                "timeout": self.timeout, "token_budget": self.token_budget,
                "retry_policy": "never", "response_model_required": True}

    def _validate_existing(self) -> None:
        audit = audit_usage(self.usage_dir)
        if audit["unresolved_calls"]:
            raise UsageError("unfinished or modified provider operation; automatic retry is forbidden")
        if not audit["complete"]:
            raise ValueError("provider receipt identity or model changed; evidence audit failed")
        usage = token_usage_summary(self.usage_dir, require_nonempty=False)
        if len(usage["models"]) > 1:
            raise ValueError("provider response model changed within a run")
        if usage["models"]:
            self.actual_model = usage["models"][0]
        for path in self.usage_dir.glob("*.json"):
            receipt = json.loads(path.read_text())
            if receipt.get("requested_model") != self.model:
                raise ValueError("existing receipts have a different requested model")

    def __call__(self, prompt: str) -> str:
        # Before the HTTP request a refusal costs zero; after it starts, missing
        # usage stays unknown even if the caller resets last_usage.
        self.last_usage = {"total_tokens": 0}
        if self._unresolved:
            raise UsageError("provider has an unresolved earlier operation")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("provider prompt must be nonempty")
        self._validate_existing()
        used = token_usage_summary(self.usage_dir, require_nonempty=False)["total_tokens"]
        remaining = self.token_budget - used
        if remaining <= 0:
            raise ValueError("token budget exhausted before provider invocation")
        payload = {"model": self.model, "temperature": self.temperature,
                   "max_completion_tokens": min(self.max_completion_tokens, remaining),
                   "messages": [{"role": "user", "content": prompt}]}
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        call_id = uuid.uuid4().hex
        request_hash = hashlib.sha256(body).hexdigest()
        _exclusive_json(self.calls_dir / f"{call_id}.started.json", {
            "call_id": call_id, "request_sha256": request_hash,
            "provider": self.manifest_binding(), "output_allowance": payload["max_completion_tokens"]})
        self.last_usage = None
        self._unresolved = True
        request = urllib.request.Request(
            self.base_url + "/chat/completions", data=body, method="POST",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
        try:
            with urllib.request.build_opener(_NoRedirect()).open(request, timeout=self.timeout) as response:
                raw = response.read()
            data = json.loads(raw)
        except Exception as error:
            # Do not include server bodies, URLs with credentials or request
            # headers in errors. An absent response cannot establish zero cost.
            raise UsageError(f"provider operation has unknown usage ({type(error).__name__})") from None
        usage = validate_usage(data.get("usage") if isinstance(data, dict) else None)
        self.last_usage = dict(usage)
        returned_model = data.get("model")
        valid_model = isinstance(returned_model, str) and bool(returned_model.strip())
        receipt = {"usage_id": call_id, "source": "mle_composed_operator",
                   "requested_model": self.model, "model": returned_model if valid_model else "",
                   "pid": os.getpid(), "request_sha256": request_hash,
                   "response_sha256": hashlib.sha256(raw).hexdigest(), **usage}
        # Even malformed content/identity must preserve the known bill.
        _exclusive_json(self.usage_dir / f"{call_id}.json", receipt)
        _exclusive_json(self.calls_dir / f"{call_id}.completed.json", {
            "call_id": call_id, "usage_receipt_sha256": hashlib.sha256(
                (self.usage_dir / f"{call_id}.json").read_bytes()).hexdigest()})
        if not valid_model:
            raise ValueError("provider response omitted its actual model identity")
        if self.actual_model is not None and self.actual_model != returned_model:
            raise ValueError("provider response model changed within a run")
        self.actual_model = returned_model
        self._unresolved = False
        if used + usage["total_tokens"] > self.token_budget:
            raise ValueError("actual provider usage exceeded the token budget")
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ValueError("provider response has no usable content") from None
        if not isinstance(content, str) or not content.strip():
            raise ValueError("provider response has no usable content")
        return content
