"""S9: real local-code/HTTP fixtures, never external benchmark performance."""
from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from core.composition.contracts import Proposal
from core.executor.types import Candidate, EvalRequest, EvalStatus
from zoo.mle_bench_lite.composed_agent import build_profile, run_agent, task_description
from zoo.mle_bench_lite.composed_domain import PublicTrainDomain, SandboxRunner
from zoo.mle_bench_lite.public_train import PublicTrainBundle, SPLITS, TASK_SPECS, write_csv

TASK = "spooky-author-identification"


def fixture_public(path, task=TASK, *, duplicate_id=False, rows_per_class=20):
    path.mkdir(parents=True)
    spec = TASK_SPECS[task]
    if spec["kind"] == "classification":
        classes = ["A", "B", "C"]
        train = [{"id": str(index), "x": str(index), spec["target"]: classes[index % 3]}
                 for index in range(rows_per_class * 3)]
        sample = [{"id": str(index), **{name: 1 / 3 for name in classes}} for index in range(4)]
        train_columns = ["id", "x", spec["target"]]
        sample_columns = ["id", *classes]
    else:
        train = [{"id": str(index), "x": str(index), **{name: str(index / 10 + 1)
                 for name in spec["targets"]}} for index in range(60)]
        sample = [{"id": str(index), **{name: "0" for name in spec["targets"]}} for index in range(4)]
        train_columns = ["id", "x", *spec["targets"]]
        sample_columns = ["id", *spec["targets"]]
    if duplicate_id:
        train[1]["id"] = train[0]["id"]
    write_csv(path / "train.csv", train_columns, train)
    write_csv(path / "test.csv", ["id", "x"], [{"id": str(index), "x": str(index + 1000)} for index in range(4)])
    write_csv(path / "sample_submission.csv", sample_columns, sample)
    return path


class TrustedFixtureRunner:
    """Portable fixture only: executes test-authored scripts, not a sandbox."""
    manifest_binding = {"kind": "trusted-test-fixture-no-isolation"}

    def execute(self, workspace, timeout):
        started = time.monotonic()
        result = subprocess.run([sys.executable, "program.py"], cwd=workspace,
            env={"PATH": os.environ.get("PATH", "")}, capture_output=True, timeout=timeout)
        (workspace / "stdout.log").write_bytes(result.stdout)
        (workspace / "stderr.log").write_bytes(result.stderr)
        return {"returncode": result.returncode, "timed_out": False,
                "wall_seconds": time.monotonic() - started}


def program(bundle, cycle=0, *, forbidden_path=None):
    """Synthetic controlled model outputs let real scores trigger a false positive."""
    predictions = {row_id: [1 / 3] * 3 for row_id in bundle.expected_ids}
    correct_count = (1, 3, 5, 6)[cycle]
    true_prob = (.6, .7, .05, .95)[cycle]
    for split in SPLITS:
        for offset, index in enumerate(bundle.indices[split]):
            target = bundle.output_columns.index(bundle.labels[index])
            probability = (.8 if offset < correct_count else .1) if split == "dev" else true_prob
            values = [(1 - probability) / 2] * 3
            values[target] = probability
            predictions[bundle.local_ids[index]] = values
    guard = f"assert not Path({str(forbidden_path)!r}).exists()\n" if forbidden_path else ""
    return ("import csv, os\nfrom pathlib import Path\n"
            "assert 'OPENAI_API_KEY' not in os.environ\n" + guard +
            f"predictions = {predictions!r}\n"
            "with open('predictions.csv', 'w', newline='') as stream:\n"
            "    writer=csv.writer(stream)\n    writer.writerow(['row_id','A','B','C'])\n"
            "    for row_id, values in predictions.items(): writer.writerow([row_id,*values])\n")


class CodeService:
    """Actual OpenAI-compatible HTTP service serving labelled test completions."""
    def __init__(self, codes, *, require_feedback=False):
        self.codes, self.requests = codes, []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                index = len(outer.requests)
                outer.requests.append(data)
                content = outer.codes[min(index, len(outer.codes) - 1)]
                if require_feedback and index == 3 and "proxy_improved_true_regressed" not in data["messages"][0]["content"]:
                    content = outer.codes[0]
                body = json.dumps({"id": "offline-fixture", "model": "fixture-snapshot",
                    "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}}).encode()
                self.send_response(200); self.send_header("Content-Length", str(len(body)))
                self.end_headers(); self.wfile.write(body)

            def log_message(self, *_args):
                pass
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=5)


@pytest.mark.parametrize("task", list(TASK_SPECS))
def test_public_training_split_is_disjoint_content_bound_and_handles_overlapping_official_ids(tmp_path, task):
    public = fixture_public(tmp_path / "public", task)
    bundle = PublicTrainBundle(public, tmp_path / "inputs", task, 7)
    reconstructed = PublicTrainBundle(public, tmp_path / "inputs", task, 7)
    assert bundle.identity == reconstructed.identity
    assert len(set(bundle.contexts.values())) == 4
    indices = [index for rows in bundle.indices.values() for index in rows]
    assert len(indices) == len(set(indices)) == 60
    assert set(bundle.local_ids.values()).isdisjoint(bundle.test_ids.values())
    predict_text = (bundle.output_root / "predict.csv").read_text()
    assert "author" not in predict_text and "species" not in predict_text
    assert "formation_energy" not in predict_text
    assert set(bundle.output_root.iterdir()) == {bundle.output_root / name for name in ("train.csv", "predict.csv", "protocol.json")}
    if bundle.spec["kind"] == "regression":
        predictions = {row_id: [2., 3.] for row_id in bundle.expected_ids}
        assert bundle.score(predictions, "dev") < 0
        assert bundle.score(predictions, "calibration") < 0
    else:
        predictions = {row_id: [1 / 3] * 3 for row_id in bundle.expected_ids}
    bundle.submission(predictions, tmp_path / "submission.csv")
    with (tmp_path / "submission.csv").open() as stream:
        assert [row["id"] for row in csv.DictReader(stream)] == ["0", "1", "2", "3"]


@pytest.mark.parametrize("problem", ["duplicate", "small_class", "source_mutation", "derived_mutation", "symlink"])
def test_public_data_preflight_and_drift_fail_before_execution(tmp_path, problem):
    public = fixture_public(tmp_path / "public", duplicate_id=problem == "duplicate",
                            rows_per_class=4 if problem == "small_class" else 20)
    if problem in ("duplicate", "small_class"):
        with pytest.raises(ValueError):
            PublicTrainBundle(public, tmp_path / "inputs", TASK, 1)
        return
    bundle = PublicTrainBundle(public, tmp_path / "inputs", TASK, 1)
    target = public / "train.csv" if problem == "source_mutation" else bundle.output_root / "train.csv"
    if problem == "symlink":
        target.unlink(); target.symlink_to(public / "train.csv")
    else:
        target.write_text(target.read_text() + "\n")
    with pytest.raises(ValueError):
        bundle.validate()


def test_native_domain_trains_once_scores_all_splits_and_detects_changed_predictions(tmp_path):
    bundle = PublicTrainBundle(fixture_public(tmp_path / "public"), tmp_path / "inputs", TASK, 1)
    domain = PublicTrainDomain(bundle, tmp_path / "candidates", runner=TrustedFixtureRunner())
    proposal = Proposal(Candidate("candidate-1"), program(bundle))
    evidence = [asyncio.run(domain.evaluate(proposal, EvalRequest(fidelity="true" if split == "calibration" else split,
                    split_id=split))) for split in SPLITS]
    assert all(result.status is EvalStatus.OK for result in evidence)
    assert domain.training_invocations == 1
    assert sum(result.cost.eval_count for result in evidence) == 4
    assert sum(result.cost.tokens_in + result.cost.tokens_out for result in evidence) == 0
    assert all(result.cost.wall_seconds > 0 for result in evidence)
    assert {result.contract.binding.evaluation_context for result in evidence} == set(bundle.contexts.values())
    assert evidence[0].metrics["dev/score"] != evidence[1].metrics["true/score"]
    domain.materialize(proposal, tmp_path / "submission.csv", expected_prediction_sha256=
                       evidence[0].contract.private.data["prediction_sha256"])
    prediction_path = domain.candidate_path(proposal) / "predictions.csv"
    prediction_path.write_text(prediction_path.read_text() + "\n")
    with pytest.raises(ValueError, match="predictions changed"):
        asyncio.run(domain.evaluate(proposal, EvalRequest("dev")))
    assert domain.training_invocations == 1


@pytest.mark.parametrize("artifact", ["not python!", "raise RuntimeError('failed')", "open('predictions.csv','w').write('wrong')"])
def test_invalid_or_failed_candidate_does_not_become_success_or_reexecute(tmp_path, artifact):
    bundle = PublicTrainBundle(fixture_public(tmp_path / "public"), tmp_path / "inputs", TASK, 1)
    domain = PublicTrainDomain(bundle, tmp_path / "candidates", runner=TrustedFixtureRunner())
    proposal = Proposal(Candidate("broken"), artifact)
    result = asyncio.run(domain.evaluate(proposal, EvalRequest("dev")))
    count = domain.training_invocations
    assert result.status is EvalStatus.FAILED_TO_RUN and not result.metrics and result.cost.eval_count == 1
    assert asyncio.run(domain.evaluate(proposal, EvalRequest("dev"))).status is EvalStatus.FAILED_TO_RUN
    assert domain.training_invocations == count
    with pytest.raises(ValueError):
        domain.materialize(proposal, tmp_path / "submission.csv", expected_prediction_sha256=None)


def test_full_framework_real_http_python_anchor_negative_feedback_crossover_and_resume(tmp_path, monkeypatch):
    workspace = tmp_path / "run/workspace"
    fixture_public(workspace / "data")
    bundle = PublicTrainBundle(workspace / "data", tmp_path / "preview", TASK, 7)
    service = CodeService([program(bundle, cycle) for cycle in range(4)], require_feedback=True)
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-secret-never-in-child")
    kwargs = dict(workspace=workspace, task_id=TASK, model="fixture-alias", api_base=service.url,
                  token_budget=10000, seed=7, iterations=3, variant="full", runner=TrustedFixtureRunner())
    try:
        summary = run_agent(**kwargs)
        resumed = run_agent(**kwargs, resume=True)
    finally:
        service.close()
    assert len(service.requests) == 4
    assert summary["token_usage"]["total_tokens"] == 72
    assert resumed["token_usage"] == summary["token_usage"]
    assert summary["actual_model"] == "fixture-snapshot"
    assert summary["details"]["training_invocations"] == 4
    assert resumed["details"]["training_invocations"] == 0
    result = summary["details"]["result"]
    assert result["proxy_validity"]["mode"] == "degraded"
    assert result["population"]["rng_state"]["calls"] == 2
    assert result["best_prompt"] == program(bundle, 3)
    text = "\n".join(request["messages"][0]["content"] for request in service.requests)
    assert "[composed-crossover" in text and "proxy_improved_true_regressed" in text
    assert "fixture-secret-never-in-child" not in text
    assert summary["external_benchmark_score_produced"] is False
    assert (workspace / "submission.csv").is_file()
    assert summary["details"]["physical_ledger"]["open_intents"] == []
    # Three normal gate calls (false-positive candidate is vetoed before gating),
    # one sealed audit, four proxy evaluations and four calibration anchors.
    assert summary["details"]["evaluation_calls"] == 12
    assert summary["details"]["physical_ledger"]["global"]["used"]["eval_count"] == 12


@pytest.mark.parametrize("tamper", ["prediction_and_cache", "cache_status", "provider_settings", "executor_settings"])
def test_completed_resume_rejects_changed_original_evidence_or_contract_before_new_calls(tmp_path, monkeypatch, tamper):
    workspace = tmp_path / "run/workspace"
    fixture_public(workspace / "data")
    bundle = PublicTrainBundle(workspace / "data", tmp_path / "preview", TASK, 7)
    service = CodeService([program(bundle)])
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-secret")
    options = dict(workspace=workspace, task_id=TASK, model="fixture-alias", api_base=service.url,
                   token_budget=10000, seed=7, iterations=0, variant="full", runner=TrustedFixtureRunner())
    try:
        summary = run_agent(**options)
        artifacts = workspace.parent / "agent_artifacts"
        journal_path = artifacts / "composed/x1.jsonl"
        journal_before = journal_path.read_bytes()
        submission_before = (workspace / "submission.csv").read_bytes()
        selected = hashlib.sha256(summary["selected_candidate_id"].encode()).hexdigest()
        record_path = artifacts / "composed_candidates" / selected / "outcome.json"
        record = json.loads(record_path.read_text())
        if tamper == "prediction_and_cache":
            predictions = record_path.parent / "predictions.csv"
            predictions.write_text(predictions.read_text() + "\n")
            record["prediction_sha256"] = "sha256:" + hashlib.sha256(predictions.read_bytes()).hexdigest()
            record_path.write_text(json.dumps(record))
        elif tamper == "cache_status":
            record["status"] = "failed_to_run"
            record_path.write_text(json.dumps(record))
        elif tamper == "provider_settings":
            options["max_completion_tokens"] = 12
        else:
            options["solution_timeout"] = 5
        with pytest.raises(ValueError, match="original|contract"):
            run_agent(**options, resume=True)
        assert len(service.requests) == 1
        assert journal_path.read_bytes() == journal_before
        assert (workspace / "submission.csv").read_bytes() == submission_before
    finally:
        service.close()


def test_integrity_change_during_training_propagates_instead_of_becoming_candidate_feedback(tmp_path):
    bundle = PublicTrainBundle(fixture_public(tmp_path / "public"), tmp_path / "inputs", TASK, 1)
    class MutatingFixtureRunner(TrustedFixtureRunner):
        def execute(self, workspace, timeout):
            result = super().execute(workspace, timeout)
            source = bundle.public_root / "train.csv"
            source.write_text(source.read_text() + "\n")
            return result
    domain = PublicTrainDomain(bundle, tmp_path / "candidates", runner=MutatingFixtureRunner())
    with pytest.raises(ValueError, match="dataset content changed"):
        asyncio.run(domain.evaluate(Proposal(Candidate("mutate"), program(bundle)), EvalRequest("dev")))
    assert not list((tmp_path / "candidates").glob("*/outcome.json"))


@pytest.mark.parametrize("path", ["/usr/local/share/mle/data", "/usr/private", "/lib/private", "/bin/data"])
def test_production_rejects_data_inside_system_trees_visible_to_the_sandbox(path):
    with pytest.raises(ValueError, match="sandbox-visible"):
        SandboxRunner.validate_paths(path)


@pytest.mark.linux
def test_actual_composed_cli_uses_full_profile_http_and_bubblewrap(tmp_path, monkeypatch):
    workspace = tmp_path / "run/workspace"
    fixture_public(workspace / "data")
    bundle = PublicTrainBundle(workspace / "data", tmp_path / "preview", TASK, 7)
    service = CodeService([program(bundle, cycle) for cycle in range(4)], require_feedback=True)
    env = dict(os.environ, OPENAI_API_KEY="cli-fixture-secret",
               PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    command = [sys.executable, "-m", "zoo.mle_bench_lite.composed_agent", "--workspace", str(workspace),
               "--task", TASK, "--seed", "7", "--model", "fixture-alias", "--api-base", service.url,
               "--token-budget", "10000", "--iterations", "3", "--variant", "full"]
    try:
        result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    finally:
        service.close()
    assert result.returncode == 0, result.stderr
    summary = json.loads((workspace.parent / "agent_artifacts/agent_run.json").read_text())
    assert len(service.requests) == 4 and summary["token_usage"]["total_tokens"] == 72
    assert summary["details"]["result"]["proxy_validity"]["mode"] == "degraded"
    assert summary["details"]["result"]["population"]["rng_state"]["calls"] == 2
    assert summary["details"]["evaluation_calls"] == 12
    assert summary["external_benchmark_score_produced"] is False


def test_baseline_uses_same_data_budget_and_gate_without_population_or_anchor(tmp_path, monkeypatch):
    workspace = tmp_path / "run/workspace"
    fixture_public(workspace / "data")
    bundle = PublicTrainBundle(workspace / "data", tmp_path / "preview", TASK, 7)
    service = CodeService([program(bundle, cycle) for cycle in range(4)])
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-secret")
    try:
        summary = run_agent(workspace=workspace, task_id=TASK, model="fixture-alias", api_base=service.url,
            token_budget=10000, seed=7, iterations=3, variant="baseline", runner=TrustedFixtureRunner())
    finally:
        service.close()
    assert summary["dataset_identity"] == bundle.identity
    assert summary["token_usage"]["total_tokens"] == 72
    assert summary["profile"]["admission"]["name"] == "layered"
    assert "proxy_validity" not in summary["profile"]["budget"]["options"]
    assert summary["profile"]["frontier"]["name"] == "tree"
    assert "[reflective improve" in service.requests[1]["messages"][0]["content"]


@pytest.mark.linux
def test_linux_actual_bubblewrap_keeps_original_labels_credentials_and_private_files_outside(tmp_path, monkeypatch):
    public = fixture_public(tmp_path / "official-public")
    secret = tmp_path / "official-private/answers.txt"
    secret.parent.mkdir(); secret.write_text("PRIVATE_BENCHMARK_CANARY")
    bundle = PublicTrainBundle(public, tmp_path / "inputs", TASK, 7)
    monkeypatch.setenv("OPENAI_API_KEY", "SECRET_API_CANARY")
    code = program(bundle, forbidden_path=secret) + f"assert not Path({str(public / 'train.csv')!r}).exists()\n"
    domain = PublicTrainDomain(bundle, tmp_path / "candidates")
    result = asyncio.run(domain.evaluate(Proposal(Candidate("linux"), code), EvalRequest("dev")))
    assert result.status is EvalStatus.OK
    assert "PRIVATE_BENCHMARK_CANARY" not in task_description(bundle)


@pytest.mark.parametrize("argument,value", [("variant", "invented"), ("token_budget", 0), ("seed", -1),
                                            ("iterations", -1), ("capacity", 1), ("anchor_every", 0)])
def test_profile_rejects_invalid_configuration(argument, value):
    options = dict(variant="full", token_budget=1000, seed=1, iterations=3)
    options[argument] = value
    with pytest.raises(ValueError):
        build_profile(**options)
