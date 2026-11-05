"""Auditable, non-retrying provider boundary for measured MLE pilot runs.

The returned model identifier, not just the requested alias, is evidence.
DeepSeek checks input plus full output capacity before dispatch. Its default
input envelope is an estimate, not a hard hosted-tokenizer bound. Actual usage
is always retained; a breached envelope makes the run ineligible.
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

from core.llm import ProviderBudgetExhausted, UsageError, validate_usage
from zoo.mle_bench_lite.agent_common import token_usage_summary
from zoo.mle_bench_lite.usage_audit import audit_usage
from zoo.mle_bench_lite.provider_protocol import build_request


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
                 api_key: str | None = None, *, request_format: str | None = None,
                 spending_ledger=None, token_admission: str | None = None):
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
        self.request_format = request_format or ("deepseek" if url.hostname == "api.deepseek.com" else "openai")
        if self.request_format not in {"openai", "deepseek"}:
            raise ValueError("unsupported provider request format")
        if url.hostname == "api.deepseek.com" and self.request_format != "deepseek":
            raise ValueError("official DeepSeek calls require the campaign protocol")
        self.spending_ledger = spending_ledger
        self._campaign_binding = None
        if self.request_format == "deepseek":
            from zoo.mle_bench_lite.cny_budget import CampaignBudget
            if not isinstance(spending_ledger, CampaignBudget):
                raise ValueError("DeepSeek requires an existing campaign CNY ledger")
            binding = spending_ledger.manifest_binding()
            if (model != binding["model"] or max_completion_tokens > binding["max_output_tokens"]
                    or (self.base_url != binding["provider_base_url"]
                        and url.hostname not in {"localhost", "127.0.0.1", "::1"})):
                raise ValueError("provider endpoint, model or output limit differs from campaign policy")
            self._campaign_binding = binding
        elif spending_ledger is not None:
            raise ValueError("campaign CNY pricing requires the DeepSeek request format")
        self.token_admission = None
        if self.request_format == "deepseek":
            from zoo.mle_bench_lite.token_admission import admission_policy
            self.token_admission = admission_policy(
                "estimated_utf8_v1" if token_admission is None else token_admission, self._campaign_binding)
        elif token_admission is not None:
            raise ValueError("token admission policies require DeepSeek campaign limits")
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
        binding = {"schema_version": 1, "requested_model": self.model,
                "base_url": self.base_url, "temperature": self.temperature,
                "max_completion_tokens": self.max_completion_tokens,
                "timeout": self.timeout, "token_budget": self.token_budget,
                "retry_policy": "never", "response_model_required": True}
        if self.request_format == "deepseek":
            from zoo.mle_bench_lite.cny_budget import usage_run_id
            binding.update(request_format="deepseek", thinking={"type": "enabled"},
                           reasoning_effort="high", wire_output_field="max_tokens",
                           temperature_applied=False, immutable_snapshot_verified=False,
                           campaign=self._campaign_binding, currency_run_id=usage_run_id(self.usage_dir))
            binding["token_admission"] = dict(self.token_admission)
        return binding

    def _validate_existing(self) -> None:
        audit = audit_usage(self.usage_dir, spending_ledger=self.spending_ledger)
        if audit["unresolved_calls"]:
            raise UsageError("unfinished or modified provider operation; automatic retry is forbidden")
        if not audit["complete"]:
            raise ValueError("provider receipt identity or model changed; campaign or evidence audit failed")
        usage = token_usage_summary(self.usage_dir, require_nonempty=False)
        if usage["total_tokens"] > self.token_budget:
            raise ValueError("token budget exhausted after actual provider usage exceeded its limit")
        if len(usage["models"]) > 1:
            raise ValueError("provider response model changed within a run")
        if usage["models"]:
            self.actual_model = usage["models"][0]
        for path in self.usage_dir.glob("*.json"):
            receipt = json.loads(path.read_text())
            if receipt.get("requested_model") != self.model:
                raise ValueError("existing receipts have a different requested model")
        for path in self.calls_dir.glob("*.started.json"):
            previous = json.loads(path.read_text()).get("provider", {})
            if ((self.request_format == "deepseek" or previous.get("request_format") == "deepseek")
                    and previous != self.manifest_binding()):
                raise ValueError("campaign or provider configuration differs from the original run")

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
            raise ProviderBudgetExhausted("token budget exhausted before provider invocation")
        allowance = min(self.max_completion_tokens, remaining)
        quote = None
        if self.token_admission is not None:
            from zoo.mle_bench_lite.token_admission import admission_quote
            allowance = self.max_completion_tokens
            quote = admission_quote(self.token_admission, prompt_bytes=len(prompt.encode("utf-8")),
                used=used, token_budget=self.token_budget, output_allowance=allowance)
        body = build_request(prompt, {"requested_model": self.model,
            "temperature": self.temperature, "max_completion_tokens": allowance,
            "request_format": self.request_format})
        call_id = uuid.uuid4().hex
        request_hash = hashlib.sha256(body).hexdigest()
        request = urllib.request.Request(
            self.base_url + "/chat/completions", data=body, method="POST",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
        if self.spending_ledger is not None:
            from zoo.mle_bench_lite.cny_budget import usage_run_id
            self.spending_ledger.reserve(call_id, request_hash, allowance, run_id=usage_run_id(self.usage_dir))
        start = {
            "call_id": call_id, "request_sha256": request_hash,
            "provider": self.manifest_binding(), "output_allowance": allowance}
        if quote is not None:
            start["token_admission"] = quote
        _exclusive_json(self.calls_dir / f"{call_id}.started.json", start)
        self.last_usage = None
        self._unresolved = True
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
        try:
            reason = data["choices"][0]["finish_reason"]
        except (KeyError, IndexError, TypeError):
            reason = None
        receipt["finish_reason"] = (reason if isinstance(reason, str) and reason in {
            "stop", "length", "content_filter", "tool_calls", "insufficient_system_resource"} else None)
        if quote is not None:
            receipt["token_admission"] = quote
        if self.request_format == "deepseek":
            from zoo.mle_bench_lite.cny_budget import validate_detailed_usage
            # A known total survives even when component details cannot settle
            # the monetary reservation. Never invent missing zero components.
            try:
                receipt.update(validate_detailed_usage(data.get("usage")))
                receipt["usage_details_valid"] = True
            except ValueError:
                receipt["usage_details_valid"] = False
            receipt.update(campaign_id=self._campaign_binding["campaign_id"],
                currency_policy_sha256=self._campaign_binding["policy_sha256"],
                immutable_snapshot_verified=False)
            for field in ("system_fingerprint", "id", "created"):
                if field in data and (data[field] is None or type(data[field]) in (str, int)):
                    receipt[field] = data[field]
        # Even malformed content/identity must preserve the known bill.
        _exclusive_json(self.usage_dir / f"{call_id}.json", receipt)
        if self.request_format == "deepseek" and returned_model != self._campaign_binding["model"]:
            # The tokens are known, but a different/missing model has no valid
            # price under this frozen policy. Keep the monetary reservation
            # unresolved rather than pricing another model as Flash.
            raise ValueError("provider response model differs from the frozen campaign price policy")
        if self.spending_ledger is not None:
            self.spending_ledger.settle(call_id, data.get("usage"), receipt["response_sha256"])
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
        if quote is not None:
            from zoo.mle_bench_lite.token_admission import validate_admission
            validate_admission(start, receipt)
        if self.request_format == "deepseek":
            if receipt["finish_reason"] != "stop":
                raise ValueError("provider completion is incomplete; measured usage was retained")
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ValueError("provider response has no usable content") from None
        if not isinstance(content, str) or not content.strip():
            raise ValueError("provider response has no usable content")
        return content
