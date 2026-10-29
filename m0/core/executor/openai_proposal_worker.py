"""Trusted OpenAI-compatible worker for ExternalCommandLLM.

Credentials are inherited from OPENAI_API_KEY or an explicitly supplied worker
environment; they are never written to the request, response, spec or journal.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from core.llm import OpenAICompatibleLLM


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default="https://api.openai.com/v1")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("request")
    parser.add_argument("response")
    args = parser.parse_args()
    request_path, response_path = Path(args.request), Path(args.response)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(request, dict) or request.get("schema_version") != 1 \
            or not isinstance(request.get("prompt"), str):
        raise ValueError("invalid proposal request")
    llm = OpenAICompatibleLLM(args.model, args.base_url, temperature=args.temperature,
                              timeout=args.timeout)
    content = llm(request["prompt"])
    from core.llm import take_usage
    usage = {"total_tokens": take_usage(llm)}
    envelope = {"schema_version": 1, "content": content, "token_usage": usage}
    temporary = response_path.with_suffix(response_path.suffix + ".tmp")
    temporary.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, response_path)


if __name__ == "__main__":
    main()
