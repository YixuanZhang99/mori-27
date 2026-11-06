"""Native composed evaluation of frozen Python candidates on public MLE data."""
from __future__ import annotations

import hashlib
import copy
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from core.composition.evaluation import EvaluationContract, PrivateEvaluationData, binding_for
from core.executor.sandbox import BubblewrapSandbox
from core.executor.seccomp import seccomp_arguments
from core.executor.types import CostVec, EvalResult, EvalStatus
from zoo.mle_bench_lite.agent_common import _extract_solution_code
from zoo.mle_bench_lite.public_train import PROTOCOL, SPLITS, digest, file_digest

_PROCESS_RUNTIME_ROOT = Path(sys.prefix).resolve()


class SandboxRunner:
    """Production runner: no host credentials, network, original data or grader."""
    def __init__(self):
        self.sandbox = BubblewrapSandbox()
        self.interpreter = sys.executable
        self.runtime_root = _PROCESS_RUNTIME_ROOT

    @staticmethod
    def validate_paths(*paths):
        # bwrap needs the system interpreter/libraries, so those trees are
        # readable. Dataset, cache and private-source roots must not be there.
        visible = [Path(name).resolve() for name in ("/usr", "/bin", "/sbin", "/lib", "/lib64")]
        visible.append(_PROCESS_RUNTIME_ROOT)
        for value in paths:
            if value is None:
                continue
            path = Path(value).resolve()
            if any(path == root or root in path.parents or path in root.parents for root in visible):
                raise ValueError("benchmark data/artifacts must be outside sandbox-visible system trees")

    @property
    def manifest_binding(self):
        binding = {"kind": "bubblewrap-seccomp-csv-v1", "python": self.interpreter,
                "python_sha256": hashlib.sha256(Path(self.interpreter).read_bytes()).hexdigest(),
                "threads": {name: 2 for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")},
                "seccomp": self.sandbox.seccomp_spec()}
        if not any(self.runtime_root == Path(name).resolve() or Path(name).resolve() in self.runtime_root.parents
                   for name in ("/usr", "/bin", "/sbin", "/lib", "/lib64")):
            binding['runtime_root'] = str(self.runtime_root)
        return binding

    def execute(self, workspace, timeout):
        self.validate_paths(workspace)
        system_roots = [Path(name).resolve() for name in ("/usr", "/bin", "/sbin", "/lib", "/lib64")]
        runtime_mount = () if any(self.runtime_root == root or root in self.runtime_root.parents
                                  for root in system_roots) else (self.runtime_root,)
        command = self.sandbox.wrap([self.interpreter, "program.py"], cwd=workspace,
                                   protected_paths=("program.py", "data"), readonly_paths=runtime_mount)
        thread_settings = []
        for name, value in self.manifest_binding["threads"].items():
            thread_settings.extend(["--setenv", name, str(value)])
        separator = command.index("--")
        command[separator:separator] = thread_settings
        started = time.monotonic()
        with (workspace / "stdout.log").open("wb") as stdout, (workspace / "stderr.log").open("wb") as stderr:
            with seccomp_arguments(command, self.sandbox.seccomp_spec()) as (command, pass_fds):
                process = subprocess.Popen(command, cwd=workspace, stdout=stdout, stderr=stderr,
                                           pass_fds=pass_fds, start_new_session=True)
            timed_out = False
            try:
                returncode = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGKILL)
                returncode = process.wait()
            finally:
                # A solution can fork and exit. Stop surviving descendants before
                # reading predictions, so they cannot rewrite the frozen artifact.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        return {"returncode": returncode, "timed_out": timed_out,
                "wall_seconds": time.monotonic() - started}

    def preflight(self, *, required_modules=("numpy",)):
        """Execute trusted imports with the exact candidate sandbox/interpreter."""
        try:
            with tempfile.TemporaryDirectory(prefix="mle-runtime-probe-") as directory:
                workspace = Path(directory)
                (workspace / "data").mkdir()
                (workspace / "program.py").write_text(
                    "import importlib\n"
                    f"for name in {list(required_modules)!r}: importlib.import_module(name)\n"
                    "print('mori27-sandbox-ready')\n")
                result = self.execute(workspace, timeout=30)
                if (result["timed_out"] or result["returncode"] != 0
                        or (workspace / "stdout.log").read_text().strip() != "mori27-sandbox-ready"):
                    raise RuntimeError("sandbox readiness failed: interpreter or runtime imports unavailable")
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeError(f"sandbox readiness failed ({type(error).__name__})") from None
        return {"ready": True, "python": self.interpreter, "modules": list(required_modules)}


class PublicTrainDomain:
    evaluator_version = PROTOCOL + ':public-stderr-v1'
    measured_cost_units = ("token", "node", "eval_count", "wallclock")
    stderr_tail_bytes = 4096

    def _public_stderr(self, workspace):
        # A worker may replace the log path. Never follow its symlink on the host
        # or block on a FIFO, and never read an unbounded file into memory.
        try:
            fd = os.open(workspace / 'stderr.log', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode):
                    return '[stderr unavailable]'
                os.lseek(fd, max(0, info.st_size - self.stderr_tail_bytes), os.SEEK_SET)
                return os.read(fd, self.stderr_tail_bytes).decode('utf-8', errors='replace')
            finally:
                os.close(fd)
        except OSError:
            return '[stderr unavailable]'

    def __init__(self, bundle, candidates_root, *, solution_timeout=120, runner=None):
        if type(solution_timeout) not in (int, float) or not 0 < solution_timeout < float("inf"):
            raise ValueError("solution_timeout must be finite and positive")
        self.bundle = bundle
        self.root = Path(candidates_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.solution_timeout = solution_timeout
        # Only tests inject a trusted fixture runner; the CLI exposes no fallback.
        self.runner = runner if runner is not None else SandboxRunner()
        if isinstance(self.runner, SandboxRunner):
            self.runner.validate_paths(bundle.public_root, bundle.output_root, self.root)
        self.runner_identity = digest(self.runner.manifest_binding)
        from zoo.mle_bench_lite import public_train, agent_common
        self._implementation = {str(Path(path).resolve()): file_digest(path) for path in
                                (__file__, public_train.__file__, agent_common.__file__)}
        self.calls, self.training_invocations = [], 0
        self._frozen = {}

    @property
    def evaluation_contexts(self):
        # Task-metric recipes can use either development-only or layered
        # admission. Bind each held-out split; retain legacy proxy assembly.
        if self.bundle.dev_scoring == "task_metric":
            return {split: self.bundle.contexts[split] for split in ("dev", "admission", "final_audit")}
        return None

    @property
    def evaluation_context(self):
        return self.bundle.contexts["dev"]

    @property
    def manifest_binding(self):
        return {"kind": PROTOCOL, "dataset_identity": self.bundle.identity,
                "dataset_manifest": self.bundle.manifest, "runner": self.runner.manifest_binding,
                "implementation_sha256": self._implementation,
                "solution_timeout": self.solution_timeout,
                'public_dev_feedback': {'schema_version': 1, 'stderr_tail_bytes': self.stderr_tail_bytes},
                "prediction_reuse": "one frozen candidate training run across all local splits"}

    def validate_context(self):
        self.bundle.validate()
        if any(file_digest(path) != expected for path, expected in self._implementation.items()):
            raise ValueError("public-train evaluator implementation changed")
        if digest(self.runner.manifest_binding) != self.runner_identity:
            raise ValueError("candidate executor identity changed")

    def validate_request(self, request):
        request.validate()
        self.validate_context()
        expected = {"dev": "dev", "calibration": "true", "admission": "admission", "final_audit": "final_audit"}
        if request.split_id not in expected or request.fidelity != expected[request.split_id] \
                or request.resume_from is not None or request.seed_set not in (None, [self.bundle.seed]) \
                or request.time_limit is not None or request.budget_token is not None:
            raise ValueError("unsupported public-train evaluation request")

    def evaluation_context_for(self, request):
        self.validate_request(request)
        return self.bundle.contexts[request.split_id]

    def candidate_path(self, proposal):
        return self.root / hashlib.sha256(proposal.candidate.id.encode()).hexdigest()

    def _identity(self, proposal):
        return {"candidate_id": proposal.candidate.id,
                "artifact_sha256": hashlib.sha256(proposal.artifact.encode()).hexdigest(),
                "dataset_identity": self.bundle.identity, "runner_identity": self.runner_identity}

    def checkpoint_state(self):
        """Bind cached outcomes to the durable native evaluation terminal."""
        self.validate_context()
        entries = {}
        for candidate_id, record in self._frozen.items():
            path = self.root / hashlib.sha256(candidate_id.encode()).hexdigest()
            outcome = path / "outcome.json"
            if not outcome.is_file() or outcome.is_symlink() or json.loads(outcome.read_text()) != record:
                raise ValueError("candidate outcome differs from frozen state")
            entries[candidate_id] = {"record": copy.deepcopy(record), "outcome_sha256": file_digest(outcome)}
        return {"schema_version": 1, "dataset_identity": self.bundle.identity,
                "runner_identity": self.runner_identity, "entries": entries}

    def restore_state(self, state):
        """Restore only state supplied by the original durable terminal."""
        self.validate_context()
        if type(state) is not dict or set(state) != {"schema_version", "dataset_identity", "runner_identity", "entries"} or \
                type(state["schema_version"]) is not int or state["schema_version"] != 1 or \
                state["dataset_identity"] != self.bundle.identity or state["runner_identity"] != self.runner_identity or \
                type(state["entries"]) is not dict:
            raise ValueError("invalid public-train terminal state")
        restored = {}
        for candidate_id, entry in state["entries"].items():
            if type(candidate_id) is not str or not candidate_id or type(entry) is not dict or \
                    set(entry) != {"record", "outcome_sha256"} or type(entry["record"]) is not dict:
                raise ValueError("invalid frozen candidate state")
            record = entry["record"]
            identity = record.get("identity")
            if type(identity) is not dict or identity.get("candidate_id") != candidate_id or \
                    identity.get("dataset_identity") != self.bundle.identity or \
                    identity.get("runner_identity") != self.runner_identity:
                raise ValueError("frozen candidate identity differs")
            path = self.root / hashlib.sha256(candidate_id.encode()).hexdigest()
            outcome = path / "outcome.json"
            if path.is_symlink() or outcome.is_symlink() or not outcome.is_file() or \
                    file_digest(outcome) != entry["outcome_sha256"] or json.loads(outcome.read_text()) != record:
                raise ValueError("candidate outcome differs from terminal")
            prediction = record.get("prediction_sha256")
            if prediction is not None:
                file = path / "predictions.csv"
                if file.is_symlink() or not file.is_file() or file_digest(file) != prediction:
                    raise ValueError("frozen candidate predictions changed")
            restored[candidate_id] = copy.deepcopy(record)
        self._frozen = restored

    def restore_evidence(self, records):
        """Rebind cached bytes to original Framework evidence, not cache claims."""
        for row in records:
            payload = row["payload"]
            proposal_data, evidence = payload["proposal"], payload["evidence"]
            from core.composition.contracts import Proposal
            from core.executor.types import Candidate
            from core.composition.evaluation import decode_evidence, validate_evidence
            canonical = decode_evidence({"schema_version": 1, "evidence": evidence})
            validate_evidence(canonical)
            proposal = Proposal(Candidate(**proposal_data["candidate"]), proposal_data["artifact"])
            result = canonical.eval_result
            expected = self._identity(proposal)
            if result.contract.binding.candidate_id != proposal.candidate.id or \
                    result.contract.binding.artifact_sha256 != expected["artifact_sha256"]:
                raise ValueError("saved evaluation candidate identity differs")
            record_path = self.candidate_path(proposal) / "outcome.json"
            if result.contract.binding_source == "invocation":
                # M7 construction can fail before producing a program. Its
                # original invocation/checkpoint is validated by Framework;
                # there is no domain training output to restore or recreate.
                if (proposal.artifact or result.status is not EvalStatus.FAILED_TO_RUN or
                        result.metrics or result.cost != CostVec() or
                        result.contract.private.data or record_path.parent.exists()):
                    raise ValueError("invalid pre-training failure evidence")
                continue
            record = json.loads(record_path.read_text())
            if record.get("identity") != expected or record.get("status") != result.status.value \
                    or record.get("prediction_sha256") != result.contract.private.data.get("prediction_sha256") \
                    or record.get("execution") != result.contract.private.data.get("training_execution"):
                raise ValueError("cached training differs from original evaluation evidence")
            if record["prediction_sha256"] is not None and file_digest(
                    record_path.parent / "predictions.csv") != record["prediction_sha256"]:
                raise ValueError("frozen candidate predictions changed")
            self._frozen[proposal.candidate.id] = copy.deepcopy(record)

    def _candidate(self, proposal):
        path = self.candidate_path(proposal)
        identity = self._identity(proposal)
        if path.exists():
            record_path = path / "outcome.json"
            if not record_path.is_file():
                raise ValueError("candidate training was interrupted; automatic re-execution is disabled")
            record = json.loads(record_path.read_text())
            if record.get("identity") != identity:
                raise ValueError("cached candidate identity differs")
            if self._frozen.get(proposal.candidate.id) != record:
                raise ValueError("cached training differs from original evaluation evidence")
            if record.get("prediction_sha256") is not None and file_digest(path / "predictions.csv") != record["prediction_sha256"]:
                raise ValueError("frozen candidate predictions changed")
            return record, False
        path.mkdir()
        workspace = path / "workspace"
        workspace.mkdir()
        shutil.copytree(self.bundle.output_root, workspace / "data")
        record = {"identity": identity, "prediction_sha256": None, "status": "failed_to_run",
                  "execution": None, "error": None}
        try:
            code = _extract_solution_code(proposal.artifact)
            (workspace / "program.py").write_text(code + "\n", encoding="utf-8")
            self.training_invocations += 1
            execution = self.runner.execute(workspace, self.solution_timeout)
            record["execution"] = execution
            if execution["timed_out"]:
                record["status"] = "timeout"
                record['error'] = 'candidate execution timed out\n' + self._public_stderr(workspace)
            elif execution["returncode"] == 0:
                prediction_path = workspace / "predictions.csv"
                # Validate before copying, and then bind the immutable saved bytes.
                self.bundle.predictions(prediction_path)
                shutil.copyfile(prediction_path, path / "predictions.csv")
                record["prediction_sha256"] = file_digest(path / "predictions.csv")
                record["status"] = "ok"
            else:
                record["error"] = "candidate program exited unsuccessfully\n" + self._public_stderr(workspace)
        except (SyntaxError, ValueError, OSError) as error:
            record["error"] = f"{type(error).__name__}: {error}"
        # An identity change is an integrity failure, never a normal candidate
        # failure that search may learn from or continue past.
        self.validate_context()
        with (path / "outcome.json").open("x") as stream:
            json.dump(record, stream, sort_keys=True, allow_nan=False)
        self._frozen[proposal.candidate.id] = copy.deepcopy(record)
        return record, True

    async def evaluate(self, proposal, request):
        self.validate_request(request)
        started = time.monotonic()
        record, created = self._candidate(proposal)
        status = EvalStatus(record["status"])
        metric = {"dev": "dev/score", "calibration": "true/score",
                  "admission": "gate/score", "final_audit": "gate/score"}[request.split_id]
        metrics = {}
        if status is EvalStatus.OK:
            predictions = self.bundle.predictions(self.candidate_path(proposal) / "predictions.csv")
            metrics[metric] = self.bundle.score(predictions, request.split_id)
        # No provider is invoked here. Training occurs once; subsequent split
        # evaluations charge only their measured scoring time and one invocation.
        cost = CostVec(wall_seconds=time.monotonic() - started, eval_count=1)
        self.calls.append({"candidate_id": proposal.candidate.id, "split": request.split_id,
                           "trained": created and record["execution"] is not None})
        feedback = ("Public training validation completed. Improve generalization; output a complete Python program."
                    if status is EvalStatus.OK else "Candidate failed the public prediction protocol: " + str(record["error"]))
        return EvalResult(status, metrics, cost, fidelity=request.fidelity,
            text_feedback=feedback if request.split_id == "dev" else None,
            contract=EvaluationContract(binding_for(proposal, request, evaluator_version=self.evaluator_version,
                evaluation_context=self.bundle.contexts[request.split_id]), self.measured_cost_units,
                private=PrivateEvaluationData(data={"prediction_sha256": record["prediction_sha256"],
                    "training_execution": record["execution"], "training_newly_executed": created})))

    def materialize(self, proposal, destination, *, expected_prediction_sha256):
        self.validate_context()
        if not (self.candidate_path(proposal) / "outcome.json").is_file():
            raise ValueError("only an already evaluated successful frozen candidate may be submitted")
        record, created = self._candidate(proposal)
        if created or record["status"] != "ok":
            raise ValueError("only an already evaluated successful frozen candidate may be submitted")
        if record["prediction_sha256"] != expected_prediction_sha256:
            raise ValueError("selected predictions differ from original evaluation evidence")
        self.bundle.submission(self.bundle.predictions(self.candidate_path(proposal) / "predictions.csv"), destination)
        return record
