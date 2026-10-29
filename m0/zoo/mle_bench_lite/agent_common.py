"""Shared host/governed MLE task agent runtime.

The two arms evolve different representations of the same solution-prompt generator,
but share solution generation, isolated execution and official dev validity grading.
Raw official reports are appended outside the agent workspace; candidate feedback
contains validity only. This module never creates benchmark performance records.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import uuid
from pathlib import Path

from core.executor.sandbox import BubblewrapSandbox
from core.executor.seccomp import seccomp_arguments
from core.llm import OpenAICompatibleLLM
from core.tasks.adapter import Workspace
from core.x1.store import AppendOnlyStore
from zoo.mle_bench_lite.adapter import MLEBenchLiteAdapter

SOLUTION_GENERATION_MARKER = "[shared-mle-solution-generation-v1]"
INITIAL_PROMPT = """Follow the task description in description.md. Inspect the public
training and test inputs under data/ and the required columns in sample_submission.csv.
Write a robust standalone Python solution that trains or computes predictions as needed,
then writes submission.csv in the current directory with exactly the required schema.
Use only the public inputs; do not look for answers, graders, leaderboards or credentials."""
INITIAL_GENERATOR = f'''# EVOLVE-BLOCK-START
SOLUTION_PROMPT = """{INITIAL_PROMPT}"""
# EVOLVE-BLOCK-END
'''


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    os.replace(temporary, path)


def extract_generator_prompt(program_code: str) -> str:
    """Read SOLUTION_PROMPT without executing an evolved host program."""
    module = ast.parse(program_code)
    for node in module.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == "SOLUTION_PROMPT"
                   for target in targets):
                value = ast.literal_eval(node.value)
                if isinstance(value, str) and value.strip():
                    return value.strip()
                raise ValueError("SOLUTION_PROMPT must be a non-empty string")
    raise ValueError("generator has no SOLUTION_PROMPT assignment")


def prompt_digest(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _validated_usage(usage: dict) -> dict[str, int]:
    if not isinstance(usage, dict):
        raise RuntimeError("LLM response omitted token usage; cost evidence is incomplete")
    values = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RuntimeError(f"LLM token usage has invalid {key}")
        values[key] = value
    if values["total_tokens"] <= 0 or values["total_tokens"] < (
            values["prompt_tokens"] + values["completion_tokens"]):
        raise RuntimeError("LLM token usage is zero or internally inconsistent")
    return values


def _check_token_budget(usage_dir: Path, token_budget: int | None) -> None:
    if token_budget is not None and token_usage_summary(
            usage_dir, require_nonempty=False)["total_tokens"] >= token_budget:
        raise RuntimeError("token budget exhausted before LLM call")


def _write_usage_receipt(usage_dir: Path, source: str, model: str,
                         usage: dict) -> dict:
    values = _validated_usage(usage)
    receipt = {"usage_id": uuid.uuid4().hex, "source": source, "model": model,
               "pid": os.getpid(), **values}
    _atomic_json(usage_dir / f"{receipt['usage_id']}.json", receipt)
    return receipt


def token_usage_summary(usage_dir: str | Path, require_nonempty: bool = True) -> dict:
    """Independently aggregate immutable per-call receipts; never trust a summary alone."""
    root = Path(usage_dir)
    records = []
    if root.exists():
        for path in root.glob("*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            if (record.get("usage_id") != path.stem
                    or not isinstance(record.get("source"), str)
                    or not isinstance(record.get("model"), str) or not record["model"]):
                raise ValueError(f"invalid token usage receipt identity: {path.name}")
            values = _validated_usage(record)
            records.append({**record, **values})
    records.sort(key=lambda record: record["usage_id"])
    if require_nonempty and not records:
        raise ValueError("no metered LLM calls were recorded")
    by_source = {}
    for record in records:
        bucket = by_source.setdefault(record["source"], {
            "calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
        bucket["calls"] += 1
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            bucket[key] += record[key]
    digest = hashlib.sha256(json.dumps(
        records, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {"calls": len(records), "receipt_count": len(records),
            "prompt_tokens": sum(record["prompt_tokens"] for record in records),
            "completion_tokens": sum(record["completion_tokens"] for record in records),
            "total_tokens": sum(record["total_tokens"] for record in records),
            "models": sorted({record["model"] for record in records}),
            "by_source": by_source, "receipts_sha256": digest}


class MeteredOpenAICompatibleLLM:
    """Synchronous metering with cumulative take_usage semantics across proposer+evaluator."""

    def __init__(self, inner: OpenAICompatibleLLM, usage_dir: Path,
                 token_budget: int | None):
        self.inner = inner
        self.usage_dir = usage_dir
        self.token_budget = token_budget
        self._cumulative = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self._usage_known = True

    @property
    def model(self):
        return self.inner.model

    @property
    def base_url(self):
        return self.inner.base_url

    @property
    def last_usage(self):
        return dict(self._cumulative) if self._usage_known else None

    @last_usage.setter
    def last_usage(self, value):
        self._cumulative = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self._usage_known = value is not None

    def __call__(self, prompt: str) -> str:
        self._usage_known = False
        _check_token_budget(self.usage_dir, self.token_budget)
        response = self.inner(prompt)
        receipt = _write_usage_receipt(
            self.usage_dir, "openai_compatible", self.inner.model, self.inner.last_usage)
        for key in self._cumulative:
            self._cumulative[key] += receipt[key]
        self._usage_known = True
        return response


class MeteredHostLLM:
    """Async OpenEvolve boundary; each evolution call gets an independent receipt."""

    def __init__(self, inner):
        self.inner = inner
        self.model = inner.model
        self.usage_dir = Path(_env_or_arg(None, "MLE_TOKEN_USAGE_DIR"))
        budget = os.environ.get("MLE_TOKEN_BUDGET")
        self.token_budget = int(budget) if budget else None

    @property
    def last_usage(self):
        return self.inner.last_usage

    async def generate(self, prompt: str, **kwargs):
        _check_token_budget(self.usage_dir, self.token_budget)
        response = await self.inner.generate(prompt, **kwargs)
        _write_usage_receipt(self.usage_dir, "host_evolution", self.model,
                             self.inner.last_usage)
        return response

    async def generate_with_context(self, system_message: str, messages: list[dict],
                                    **kwargs):
        _check_token_budget(self.usage_dir, self.token_budget)
        response = await self.inner.generate_with_context(system_message, messages, **kwargs)
        _write_usage_receipt(self.usage_dir, "host_evolution", self.model,
                             self.inner.last_usage)
        return response


def metered_host_llm(model_cfg):
    """OpenEvolve init_client factory; also works in spawned evaluator workers."""
    from openevolve.llm.openai import OpenAILLM

    inner = OpenAILLM(model_cfg)
    return MeteredHostLLM(inner)


def _extract_solution_code(response: str) -> str:
    fenced = re.findall(r"```(?:python)?[ \t]*\r?\n(.*?)```", response,
                        flags=re.DOTALL | re.IGNORECASE)
    code = (fenced[0] if fenced else response).strip()
    if not code:
        raise ValueError("solution generation returned empty code")
    ast.parse(code)
    return code


class AgentRuntime:
    """One task/seed/arm runtime; official grading never enters the sandbox."""

    def __init__(self, workspace: str | Path, task_id: str,
                 official_root: str | Path, data_root: str | Path,
                 audit_path: str | Path, model: str, api_base: str,
                 manifest_path: str | Path | None = None,
                 solution_timeout: float = 60, seed: int = 1,
                 token_budget: int | None = 60_000, grader=None):
        self.workspace = Path(workspace).resolve()
        self.task_id = task_id
        self.seed = seed
        if not self.workspace.is_dir():
            raise FileNotFoundError("agent workspace must be prepared before startup")
        if not (self.workspace / "data").is_dir():
            raise FileNotFoundError("agent workspace lacks prepared public data/")
        if isinstance(solution_timeout, bool) or solution_timeout <= 0:
            raise ValueError("solution_timeout must be positive")
        self.solution_timeout = float(solution_timeout)
        if (token_budget is not None and (isinstance(token_budget, bool)
                or not isinstance(token_budget, int) or token_budget <= 0)):
            raise ValueError("token_budget must be a positive integer or None")
        self.token_budget = token_budget
        self.adapter = MLEBenchLiteAdapter(
            task_id, official_root, data_root, manifest_path)
        self.audit = AppendOnlyStore(audit_path)
        self.sandbox = BubblewrapSandbox()
        self.artifacts = self.workspace.parent / "agent_artifacts"
        self.candidates = self.artifacts / "candidates"
        self.usage_dir = self.artifacts / "token_usage"
        self.candidates.mkdir(parents=True, exist_ok=True)
        self.usage_dir.mkdir(parents=True, exist_ok=True)
        inner_llm = OpenAICompatibleLLM(
            model=model, base_url=api_base, temperature=0.0,
            timeout=max(30.0, self.solution_timeout))
        self.llm = MeteredOpenAICompatibleLLM(inner_llm, self.usage_dir, token_budget)
        self.description = (self.workspace / "description.md").read_text(encoding="utf-8")
        self.grader = grader

    def _solution_prompt(self, solution_prompt: str) -> str:
        return (f"{SOLUTION_GENERATION_MARKER}\nSEED: {self.seed}\n"
                f"TASK: {self.task_id}\n\nSOLUTION STRATEGY:\n{solution_prompt}\n\n"
                f"TASK DESCRIPTION:\n{self.description}\n\n"
                "Return only executable Python code (one fenced block is acceptable). "
                "The program runs with the prepared workspace as its current directory.")

    def evaluate_prompt(self, candidate_id: str, solution_prompt: str) -> dict:
        if not isinstance(solution_prompt, str) or not solution_prompt.strip():
            raise ValueError("candidate solution prompt must be non-empty")
        solution_prompt = solution_prompt.strip()
        digest = prompt_digest(solution_prompt)
        outcome_dir = self.candidates / digest
        outcome_dir.mkdir(parents=True, exist_ok=True)
        solution_path = self.workspace / ".mle_candidate_solution.py"
        submission = self.workspace / "submission.csv"
        outcome = {"candidate_id": candidate_id, "prompt_sha256": digest,
                   "evaluator_version": "official-dev-validity-v1",
                   "valid_submission": False, "timed_out": False,
                   "solution_returncode": None, "submission_path": None,
                   "text_feedback": "candidate did not execute"}
        try:
            response = self.llm(self._solution_prompt(solution_prompt))
            code = _extract_solution_code(response)
            (outcome_dir / "solution.py").write_text(code + "\n", encoding="utf-8")
            solution_path.write_text(code + "\n", encoding="utf-8")
            if submission.exists():
                if not submission.is_file():
                    raise RuntimeError("submission.csv is not a regular file")
                submission.unlink()
            protected = ["description.md", "sample_submission.csv", "task.json",
                         solution_path.name]
            command = self.sandbox.wrap(
                [os.environ.get("PYTHON", os.sys.executable), str(solution_path)],
                cwd=self.workspace, protected_paths=protected,
                data_dir=str(self.workspace / "data"))
            with seccomp_arguments(command, self.sandbox.seccomp_spec()) as (
                    command, pass_fds):
                process = subprocess.Popen(
                    command, cwd=self.workspace, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, start_new_session=True, pass_fds=pass_fds)
            try:
                stdout, stderr = process.communicate(timeout=self.solution_timeout)
            except subprocess.TimeoutExpired:
                outcome["timed_out"] = True
                os.killpg(process.pid, signal.SIGKILL)
                stdout, stderr = process.communicate()
            outcome["solution_returncode"] = process.returncode
            (outcome_dir / "stdout.log").write_bytes(stdout[-1_000_000:])
            (outcome_dir / "stderr.log").write_bytes(stderr[-1_000_000:])
            if process.returncode == 0 and submission.is_file():
                archived_submission = outcome_dir / "submission.csv"
                shutil.copyfile(submission, archived_submission)
                outcome["submission_path"] = str(archived_submission)
                try:
                    public = self.adapter.grade_submission(
                        Workspace(self.workspace), "dev", self.audit, grader=self.grader)
                    outcome["valid_submission"] = bool(public["valid_submission"])
                    outcome["text_feedback"] = (
                        "official dev grading: valid submission"
                        if outcome["valid_submission"] else
                        "official dev grading: invalid submission; inspect schema and execution")
                except Exception as error:
                    outcome["text_feedback"] = (
                        f"official dev grading failed closed: {type(error).__name__}")
            else:
                detail = stderr.decode("utf-8", errors="replace")[-1200:]
                outcome["text_feedback"] = (
                    f"solution failed or produced no submission; returncode={process.returncode}; "
                    f"timed_out={outcome['timed_out']}; stderr={detail}")
        except Exception as error:
            outcome["text_feedback"] = f"candidate evaluation failed: {type(error).__name__}: {error}"[-2000:]
        finally:
            solution_path.unlink(missing_ok=True)
        _atomic_json(outcome_dir / "outcome.json", outcome)
        return outcome

    def outcome_for_prompt(self, solution_prompt: str) -> dict:
        path = self.candidates / prompt_digest(solution_prompt.strip()) / "outcome.json"
        if not path.is_file():
            raise FileNotFoundError("selected generator has no evaluated outcome")
        outcome = json.loads(path.read_text(encoding="utf-8"))
        if outcome.get("prompt_sha256") != prompt_digest(solution_prompt.strip()):
            raise ValueError("selected outcome prompt hash mismatch")
        return outcome

    def finalize(self, solution_prompt: str, arm: str, details: dict) -> dict:
        outcome = self.outcome_for_prompt(solution_prompt)
        archived = outcome.get("submission_path")
        if archived:
            source = Path(archived)
            if not source.is_file():
                raise FileNotFoundError("selected submission artifact is missing")
            shutil.copyfile(source, self.workspace / "submission.csv")
        usage = token_usage_summary(self.usage_dir)
        if len(usage["models"]) != 1 or usage["models"][0] != self.llm.model:
            raise ValueError("token usage receipts do not establish one declared backbone")
        summary = {"arm": arm, "task_id": self.task_id, "seed": self.seed,
                   "selected_prompt_sha256": outcome["prompt_sha256"],
                   "selected_dev_valid_submission": outcome["valid_submission"],
                   "submission_materialized": bool(archived),
                   "external_benchmark_score_produced": False,
                   "actual_model": self.llm.model, "token_budget": self.token_budget,
                   "token_usage": usage,
                   "token_budget_exceeded": (self.token_budget is not None
                                             and usage["total_tokens"] > self.token_budget),
                   "details": details}
        _atomic_json(self.artifacts / "agent_run.json", summary)
        return summary


def _env_or_arg(value, name: str) -> str:
    result = value or os.environ.get(name)
    if not result:
        raise ValueError(f"{name} or its corresponding CLI argument is required")
    return result


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--task")
    parser.add_argument("--seed", type=int,
                        default=int(os.environ.get("MLE_SEED", "1")))
    parser.add_argument("--official-root", type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--manifest-path", type=Path)
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--api-base",
                        default=os.environ.get("OPENAI_API_BASE",
                                               os.environ.get("OPENAI_BASE_URL",
                                                              "https://api.openai.com/v1")))
    parser.add_argument("--solution-timeout", type=float, default=60)
    parser.add_argument("--iterations", type=int, default=2)
    parser.add_argument("--token-budget", type=int,
                        default=int(os.environ.get("MLE_TOKEN_BUDGET", "60000")))


def runtime_from_args(args: argparse.Namespace) -> AgentRuntime:
    if isinstance(args.iterations, bool) or args.iterations < 0:
        raise ValueError("iterations must be a non-negative integer")
    task_id = _env_or_arg(args.task, "MLE_TASK_ID")
    official = _env_or_arg(args.official_root, "MLE_OFFICIAL_ROOT")
    data = _env_or_arg(args.data_root, "MLE_DATA_ROOT")
    model = _env_or_arg(args.model, "OPENAI_MODEL")
    audit = args.audit or Path(os.environ.get(
        "MLE_AUDIT_PATH", str(args.workspace.resolve().parent / "audit.jsonl")))
    manifest = args.manifest_path or os.environ.get("MLE_MANIFEST_PATH")
    return AgentRuntime(
        args.workspace, task_id, official, data, audit, model, args.api_base,
        manifest_path=manifest, solution_timeout=args.solution_timeout, seed=args.seed,
        token_budget=args.token_budget)


def export_runtime_environment(args: argparse.Namespace, runtime: AgentRuntime) -> None:
    """Pass non-secret runtime paths to OpenEvolve evaluator workers."""
    os.environ.update({
        "MLE_WORKSPACE": str(runtime.workspace), "MLE_TASK_ID": runtime.task_id,
        "MLE_SEED": str(runtime.seed),
        "MLE_OFFICIAL_ROOT": str(runtime.adapter.official_root),
        "MLE_DATA_ROOT": str(runtime.adapter.data_root),
        "MLE_MANIFEST_PATH": str(runtime.adapter.manifest_path),
        "MLE_AUDIT_PATH": str(runtime.audit.path),
        "MLE_TOKEN_USAGE_DIR": str(runtime.usage_dir),
        "MLE_TOKEN_BUDGET": str(runtime.token_budget) if runtime.token_budget is not None else "",
        "OPENAI_MODEL": runtime.llm.model, "OPENAI_API_BASE": runtime.llm.base_url,
        "MLE_SOLUTION_TIMEOUT": str(runtime.solution_timeout),
        "ENABLE_ARTIFACTS": "false"})


def runtime_from_environment() -> AgentRuntime:
    return AgentRuntime(
        _env_or_arg(None, "MLE_WORKSPACE"), _env_or_arg(None, "MLE_TASK_ID"),
        _env_or_arg(None, "MLE_OFFICIAL_ROOT"), _env_or_arg(None, "MLE_DATA_ROOT"),
        _env_or_arg(None, "MLE_AUDIT_PATH"), _env_or_arg(None, "OPENAI_MODEL"),
        os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1"),
        manifest_path=os.environ.get("MLE_MANIFEST_PATH"),
        solution_timeout=float(os.environ.get("MLE_SOLUTION_TIMEOUT", "60")),
        seed=int(os.environ.get("MLE_SEED", "1")),
        token_budget=int(os.environ["MLE_TOKEN_BUDGET"])
        if os.environ.get("MLE_TOKEN_BUDGET") else None)
