"""Versioned request admission, separate from measured usage and CNY pricing.

The UTF-8 envelope is deliberately labelled an estimate. Hosted prompt framing
is not an exact local-tokenizer contract. Capacity mode instead reserves the
service's whole input capacity plus the enforced output limit.
"""
from core.llm import ProviderBudgetExhausted


def admission_policy(mode, campaign):
    if mode == "estimated_utf8_v1":
        return {"mode": mode, "guarantee": "estimate_only", "framing_allowance": 1024}
    if mode == "model_capacity_v1":
        return {"mode": mode, "guarantee": "service_capacity_bound",
                "input_capacity": campaign["context_tokens"]}
    raise ValueError("unsupported token admission policy")


def admission_quote(policy, *, prompt_bytes, used, token_budget, output_allowance):
    remaining = token_budget - used
    input_allowance = (prompt_bytes + policy["framing_allowance"]
                       if policy["mode"] == "estimated_utf8_v1" else policy["input_capacity"])
    total = input_allowance + output_allowance
    if total > remaining:
        raise ProviderBudgetExhausted("token admission capacity exhausted before provider invocation")
    return {"used_before": used, "remaining_before": remaining,
            "prompt_utf8_bytes": prompt_bytes, "input_allowance": input_allowance,
            "output_allowance": output_allowance, "total_allowance": total}


def validate_admission(start, receipt):
    """Recompute new-policy evidence; legacy evidence makes no new guarantee."""
    provider = start.get("provider", {})
    if not isinstance(provider, dict):
        raise ValueError("invalid token admission provider evidence")
    if not any("token_admission" in row for row in (provider, start, receipt)):
        return
    policy = provider.get("token_admission")
    if not isinstance(policy, dict) or provider.get("request_format") != "deepseek":
        raise ValueError("invalid token admission policy evidence")
    if policy != admission_policy(policy.get("mode"), provider.get("campaign", {})):
        raise ValueError("token admission policy parameters changed")
    quote = start.get("token_admission")
    fields = {"used_before", "remaining_before", "prompt_utf8_bytes", "input_allowance",
              "output_allowance", "total_allowance"}
    if (not isinstance(quote, dict) or set(quote) != fields
            or any(type(value) is not int or value < 0 for value in quote.values())
            or quote != receipt.get("token_admission")):
        raise ValueError("token admission quote evidence differs or is invalid")
    for key in ("token_budget", "max_completion_tokens"):
        if type(provider.get(key)) is not int or provider[key] <= 0:
            raise ValueError("invalid token admission provider limits")
    expected = admission_quote(policy, prompt_bytes=quote["prompt_utf8_bytes"],
        used=quote["used_before"], token_budget=provider["token_budget"],
        output_allowance=provider["max_completion_tokens"])
    if quote != expected or start.get("output_allowance") != quote["output_allowance"]:
        raise ValueError("token admission quote does not match the frozen limits")
    for field, maximum in (("prompt_tokens", quote["input_allowance"]),
                           ("completion_tokens", quote["output_allowance"]),
                           ("total_tokens", quote["total_allowance"])):
        if type(receipt.get(field)) is not int or not 0 <= receipt[field] <= maximum:
            raise ValueError("actual usage breached token admission allowance")
