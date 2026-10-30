"""Durable operation-bound real git worktrees with explicit sandbox boundaries."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import asdict, fields, replace
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import shutil
import subprocess
import sys
import time
import uuid

from core.composition.command_domain import CommandDomain, digest
from core.composition.command_worker import atomic, canonical, read
from core.composition.contracts import Proposal, json_copy
from core.composition.evaluation import (binding_for, decode_evidence, encode_evidence,
                                         measured_costs, validate_evidence)
from core.executor.evaluation_contract import EvaluationContract
from core.executor.process_identity import process_alive, start_ticks
from core.executor.sandbox import BubblewrapSandbox
from core.executor.seccomp import (SECCOMP_BWRAP_MEMFD, seccomp_policy_summary,
                                   validate_seccomp_delivery, validate_seccomp_policy)
from core.executor.types import CostVec, EvalResult, EvalStatus
from core.executor.workspace import GitWorktree, protected_manifest, safe_relative, verify_manifest
from core.llm import UsageError


class MeasuredCommandError(ValueError):
    """Rejected invocation with a genuine, independently parseable producer meter.

    The runtime must settle these costs before rejecting the result. This class
    does not attest that the result identity or score is valid.
    """
    def __init__(self, message, cost, measured_cost_units, *, raw_response_path, wall_seconds):
        super().__init__(message)
        self.cost, self.measured_cost_units = cost, tuple(measured_cost_units)
        self.raw_response_path, self.wall_seconds = str(raw_response_path), wall_seconds


@contextmanager
def _lease(path):
    with Path(path).open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("another coordinator owns this worktree operation") from error
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def _git(repo, *args):
    result = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *args],
                            cwd=repo, capture_output=True, text=True)
    if result.returncode:
        raise ValueError("git worktree operation failed: " + (result.stderr or result.stdout)[-2000:])
    return result.stdout.strip()


def _file_digest(path):
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate response JSON key")
            result[key] = value
        return result
    def nonfinite(value):
        raise ValueError("nonfinite response JSON number")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)


class WorktreeCommandExecutor:
    durable_operation_recovery = True
    _identity_wait_seconds = 10

    def __init__(self, base_repo, run_root, store, *, base_ref="HEAD", artifact_path="candidate.txt",
                 protected_paths=(), sandbox="bubblewrap", resource_limits=None):
        if type(base_ref) is not str or not base_ref or base_ref.startswith("-"):
            raise ValueError("base_ref requires a commit or ref")
        if sandbox not in {"bubblewrap", "none"}:
            raise ValueError("sandbox must be bubblewrap or explicit trusted-local none")
        if type(protected_paths) not in (list, tuple) or any(type(x) is not str for x in protected_paths):
            raise ValueError("protected_paths must contain relative paths")
        self.workspace = GitWorktree(base_repo, run_root)
        self.base_commit = _git(self.workspace.base_repo, "rev-parse", "--verify", base_ref + "^{commit}")
        self.artifact_path, self.protected_paths = artifact_path, tuple(protected_paths)
        safe_relative(self.workspace.base_repo, artifact_path)
        if artifact_path.split("/")[0] == ".autoresearch-command" or any(
                artifact_path == path or artifact_path.startswith(path + "/") or path.startswith(artifact_path + "/")
                for path in self.protected_paths):
            raise ValueError("candidate artifact overlaps a protected or control path")
        self.protected = protected_manifest(self.workspace.base_repo, self.protected_paths)
        self.sandbox_name = sandbox
        self.sandbox = BubblewrapSandbox() if sandbox == "bubblewrap" else None
        self.resource_limits = json_copy(resource_limits or {})
        if set(self.resource_limits) - {"memory_bytes", "file_bytes", "process_count"} or any(
                type(value) is not int or value <= 0 for value in self.resource_limits.values()):
            raise ValueError("invalid worktree resource limits")
        if start_ticks(os.getpid()) is None:
            raise RuntimeError("worktree adoption requires a stable OS process identity")
        self.store = store
        self.root = store.path.parent.resolve() / "worktree-operations"
        self.root.mkdir(parents=True, exist_ok=True)
        self.worker = Path(__file__).with_name("command_worker.py").resolve()
        self.policy = self.sandbox.seccomp_spec() if self.sandbox else None
        self.delivery = SECCOMP_BWRAP_MEMFD if self.policy else None
        self._children = {}

    @property
    def manifest_binding(self):
        return {"kind": "git_worktree_command_v1", "base_repo": str(self.workspace.base_repo),
            "base_commit": self.base_commit, "run_root": str(self.workspace.run_root),
            "artifact_path": self.artifact_path, "protected": dict(self.protected),
            "protected_paths": list(self.protected_paths), "sandbox": self.sandbox_name,
            "security_boundary": "linux_bubblewrap_seccomp" if self.sandbox else "trusted_local_no_sandbox",
            "process_identity_platform": sys.platform,
            "supervisor_python": {"path": sys.executable, "sha256": _file_digest(sys.executable)},
            "resource_limits": dict(self.resource_limits), "seccomp": seccomp_policy_summary(self.policy),
            "seccomp_delivery": self.delivery, "worker_sha256": _file_digest(self.worker),
            "seccomp_sha256": _file_digest(self.worker.parents[1] / "executor" / "seccomp.py"),
            "identity_sha256": _file_digest(self.worker.parents[1] / "executor" / "process_identity.py")}

    def validate_context(self):
        verify_manifest(self.workspace.base_repo, self.protected, self.protected_paths)
        if self.policy:
            validate_seccomp_policy(self.policy)
        validate_seccomp_delivery(self.policy, self.delivery)

    def validate_domain(self, domain):
        if not isinstance(domain, CommandDomain):
            raise ValueError("git_worktree requires a CommandDomain")
        domain.validate_context()
        for relative in domain.split_paths.values():
            dataset = safe_relative(Path(domain.data_dir), relative).resolve()
            if dataset == self.workspace.base_repo or self.workspace.base_repo in dataset.parents:
                raise ValueError("evaluation splits must be outside the candidate base repository")
        for argument in domain.command[1:]:
            path = Path(argument)
            if path.is_absolute() or argument.startswith("-"):
                continue
            target = self.workspace.base_repo / path
            if target.is_file():
                safe_relative(self.workspace.base_repo, argument)
                if argument != self.artifact_path and not any(
                        argument == protected or argument.startswith(protected + "/") for protected in self.protected_paths):
                    raise ValueError("relative command script/input must be a protected base file or the bound candidate artifact")

    @staticmethod
    def _operation(operation):
        operation = json_copy(operation, label="bound worktree operation")
        if type(operation) is not dict or set(operation) != {
                "run_id", "cycle", "phase", "intent_id", "fingerprint", "manifest_sha256"} \
                or type(operation["cycle"]) is not int or operation["cycle"] < 0 \
                or any(type(operation[key]) is not str or not operation[key].strip()
                       for key in ("run_id", "phase", "intent_id", "fingerprint", "manifest_sha256")):
            raise ValueError("invalid bound worktree operation identity")
        if operation["phase"] not in {"dev", "dev_baseline", "admission", "final", "final_audit", "calibration"}:
            raise ValueError("unsupported bound evaluation phase")
        return operation

    def operation_path(self, operation):
        operation = self._operation(operation)
        return self.root / hashlib.sha256(operation["intent_id"].encode()).hexdigest()

    def _event_once(self, kind, key, payload):
        rows = [row["payload"] for row in self.store.read(kind) if row["payload"].get("operation_key") == key]
        payload = {"operation_key": key, **payload}
        if rows:
            if len(rows) != 1 or rows[0] != payload:
                raise ValueError("duplicate or changed worktree operation evidence")
            return
        self.store.append(kind, payload)

    async def execute(self, proposal, request, domain):
        raise RuntimeError("git_worktree execution requires execute_bound with its reserved operation")

    async def execute_bound(self, proposal, request, domain, operation):
        return await asyncio.to_thread(self._execute, proposal, request, domain, operation)

    def _execute(self, proposal, request, domain, operation):
        if not isinstance(proposal, Proposal) or not isinstance(domain, CommandDomain):
            raise ValueError("worktree execution needs Proposal and CommandDomain")
        self.validate_domain(domain)
        proposal.candidate.validate(); domain.validate_request(request); self.validate_context()
        operation = self._operation(operation)
        expected = binding_for(proposal, request, evaluator_version=domain.evaluator_version,
                               evaluation_context=domain.evaluation_context_for(request))
        binding = {"operation": operation, "proposal": asdict(proposal), "request": asdict(request),
                   "evaluation_binding": asdict(expected), "executor": self.manifest_binding,
                   "domain": domain.manifest_binding}
        binding = json.loads(canonical(binding))
        directory = self.operation_path(operation)
        directory.mkdir(exist_ok=True)
        with _lease(directory / "coordinator.lock"):
            marker = directory / "operation.json"
            if marker.exists():
                recorded = read(marker)
                if recorded.get("binding") != binding or recorded.get("binding_sha256") != digest(binding):
                    raise ValueError("worktree operation request, manifest, candidate or budget binding changed")
            else:
                suffix = hashlib.sha256(str(directory).encode()).hexdigest()
                recorded = {"schema_version": 1, "binding": binding, "binding_sha256": digest(binding),
                    "execution_token": uuid.uuid4().hex, "worktree_ref": "candidate/" + suffix,
                    "created_epoch": int(time.time()),
                    "worktree_path": str(self.workspace.run_root / ("candidate-" + suffix))}
                atomic(marker, recorded)
            self._event_once("worktree_operation_prepared", directory.name, recorded)
            self._prepare(directory, recorded, proposal, request, domain)
            completion = self._wait(directory, recorded)
            return self._complete(directory, recorded, completion, expected, domain)

    def _prepare(self, directory, recorded, proposal, request, domain):
        # A persisted launch intent forbids all rebuilding or replacement calls.
        if (directory / "launch.json").exists():
            return
        root, ref = Path(recorded["worktree_path"]), recorded["worktree_ref"]
        if not root.exists():
            base = request.resume_from or self.base_commit
            if request.resume_from is not None and not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", base):
                raise ValueError("worktree resume_from must be an immutable git commit")
            _git(self.workspace.base_repo, "worktree", "add", "--quiet", "--no-checkout", "-b", ref, str(root), base)
        self._adopt(recorded)
        if _git(root, "rev-parse", "HEAD") != (request.resume_from or self.base_commit):
            raise ValueError("candidate worktree base commit changed before execution")
        self._materialize_base(directory, root, request.resume_from or self.base_commit)
        verify_manifest(root, self.protected, self.protected_paths)
        artifact = safe_relative(root, self.artifact_path)
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(proposal.artifact, encoding="utf-8")
        control = root / ".autoresearch-command"
        if control.is_symlink():
            raise ValueError("worktree control directory cannot be a symlink")
        control.mkdir(exist_ok=True)
        request_path, response_path = control / "request.json", control / "response.json"
        payload = {"schema_version": 1, "operation_key": directory.name,
            "execution_token": recorded["execution_token"], "binding": recorded["binding"]["evaluation_binding"],
            "operation": recorded["binding"]["operation"], "candidate": asdict(proposal.candidate),
            "artifact": proposal.artifact, "artifact_path": self.artifact_path, "request": asdict(request),
            "data_dir": domain.data_dir, "split_path": domain.split_path_for(request)}
        atomic(request_path, payload)
        args = [*domain.command, str(request_path), str(response_path)]
        if self.sandbox:
            args = self.sandbox.wrap(args, root, (*self.protected_paths, ".autoresearch-command/request.json"),
                                     "", {})
            # Only the active split is visible; mounting data_dir wholesale lets
            # a dev candidate inspect admission/final data before its gate.
            boundary = args.index("--")
            visible = Path(domain.split_path_for(request))
            mounts = []
            self.sandbox._directories(mounts, visible)
            mounts.extend(["--ro-bind", str(visible), str(visible)])
            args[boundary:boundary] = mounts
        spec = {"args": args, "cwd": str(root), "request_path": str(request_path),
            "response_path": str(response_path), "request_sha256": _file_digest(request_path),
            "execution_token": recorded["execution_token"], "time_limit": request.time_limit or domain.time_limit,
            "resource_limits": self.resource_limits, "seccomp_policy": self.policy,
            "seccomp_delivery": self.delivery, "binding_sha256": recorded["binding_sha256"]}
        atomic(directory / "spec.json", {"spec": spec, "spec_sha256": digest(spec)})
        # This fsynced marker comes before Popen. A crash in this narrow gap is
        # unresolved, never authorization to repeat a potentially paid command.
        launch = {"execution_token": recorded["execution_token"], "spec_sha256": digest(spec)}
        atomic(directory / "launch.json", launch)
        self._event_once("worktree_launch_intent", directory.name, launch)
        bootstrap = "import runpy,sys; p=sys.argv[1]; sys.argv=[p]+sys.argv[2:]; runpy.run_path(p,run_name='__main__')"
        self._children[directory.name] = subprocess.Popen([sys.executable, "-I", "-c", bootstrap,
            str(self.worker), str(directory / "spec.json")], cwd=root, env=dict(os.environ),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    def _materialize_base(self, directory, root, base):
        """Check out exact blobs without executing smudge filters or checkout hooks."""
        descriptor = {"base_commit": base, "tree": _git(root, "rev-parse", base + "^{tree}")}
        marker = directory / "materialized.json"
        if marker.exists():
            if read(marker) != descriptor:
                raise ValueError("worktree base materialization identity changed")
            return
        # Only this operation's validated, unlaunched worktree can reach here.
        for child in root.iterdir():
            if child.name == ".git":
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        listing = subprocess.check_output(["git", "ls-tree", "-r", "-z", base], cwd=root)
        for entry in listing.split(b"\0"):
            if not entry:
                continue
            description, raw_name = entry.split(b"\t", 1)
            mode, kind, oid = description.decode("ascii").split()
            if kind != "blob" or mode not in {"100644", "100755", "120000"}:
                raise ValueError("worktree base contains unsupported submodule or special entry")
            path = safe_relative(root, os.fsdecode(raw_name))
            path.parent.mkdir(parents=True, exist_ok=True)
            data = subprocess.check_output(["git", "cat-file", "blob", oid], cwd=root)
            if mode == "120000":
                path.symlink_to(os.fsdecode(data))
            else:
                path.write_bytes(data)
                path.chmod(0o755 if mode == "100755" else 0o644)
        atomic(marker, descriptor)

    def _adopt(self, recorded):
        root = self.workspace.adopt(recorded["worktree_ref"], recorded["worktree_path"])
        common = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
        expected = _git(self.workspace.base_repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if common != expected:
            raise ValueError("worktree belongs to another git repository")
        return root

    @staticmethod
    def _identity(value, recorded, spec_sha):
        if type(value) is not dict or set(value) != {"pid", "start_ticks", "execution_token", "spec_sha256"} \
                or type(value["pid"]) is not int or value["pid"] <= 0 \
                or type(value["start_ticks"]) is not int or value["start_ticks"] < 0 \
                or value["execution_token"] != recorded["execution_token"] or value["spec_sha256"] != spec_sha:
            raise ValueError("durable process identity binding mismatch")
        return value

    def _wait(self, directory, recorded):
        envelope = read(directory / "spec.json")
        spec, spec_sha = envelope["spec"], envelope["spec_sha256"]
        try:
            self._event_once("worktree_launch_intent", directory.name, read(directory / "launch.json"))
            if digest(spec) != spec_sha or spec["binding_sha256"] != recorded["binding_sha256"] \
                    or read(directory / "launch.json") != {"execution_token": recorded["execution_token"], "spec_sha256": spec_sha} \
                    or spec["seccomp_policy"] != self.policy or spec["seccomp_delivery"] != self.delivery:
                raise ValueError("durable process specification or security policy changed")
            validate_seccomp_delivery(spec["seccomp_policy"], spec["seccomp_delivery"])
            if spec["seccomp_policy"]:
                validate_seccomp_policy(spec["seccomp_policy"])
        except (ValueError, OSError, KeyError) as error:
            self._stop_bound_processes(directory, recorded)
            raise UsageError("worktree process recovery blocked by changed security specification") from error
        deadline = time.monotonic() + self._identity_wait_seconds
        while not (directory / "supervisor.json").exists():
            if time.monotonic() >= deadline:
                raise UsageError("launch intent has no stable process identity; refusing replacement")
            time.sleep(0.02)
        owner = self._identity(read(directory / "supervisor.json"), recorded, spec_sha)
        self._event_once("worktree_process_started", directory.name, owner)
        if not (directory / "authorized.json").exists():
            if not process_alive(owner["pid"], owner["start_ticks"]):
                raise UsageError("supervisor disappeared before authorization; no replacement is allowed")
            atomic(directory / "authorized.json", owner)
        elif read(directory / "authorized.json") != owner:
            raise ValueError("supervisor authorization changed")
        while not (directory / "process-result.json").exists():
            if not process_alive(owner["pid"], owner["start_ticks"]):
                target_path = directory / "target.json"
                if target_path.exists():
                    target = self._identity(read(target_path), recorded, spec_sha)
                    if process_alive(target["pid"], target["start_ticks"]):
                        try:
                            os.killpg(target["pid"], signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                raise UsageError("detached command disappeared without a durable result; usage remains unresolved")
            time.sleep(0.02)
        result = read(directory / "process-result.json")
        required = {"returncode", "timeout", "wrapper_error", "execution_token", "spec_sha256", "request_sha256",
                    "response_sha256", "supervisor", "target", "wall_seconds"}
        if type(result) is not dict or set(result) != required or result["supervisor"] != owner \
                or result["execution_token"] != recorded["execution_token"] or result["spec_sha256"] != spec_sha \
                or result["request_sha256"] != spec["request_sha256"] or type(result["returncode"]) is not int \
                or type(result["timeout"]) is not bool or type(result["wall_seconds"]) not in (int, float) \
                or not math.isfinite(result["wall_seconds"]) or result["wall_seconds"] < 0:
            raise UsageError("invalid durable process completion")
        if result["target"] is not None:
            target = self._identity(result["target"], recorded, spec_sha)
            if read(directory / "target.json") != target or read(directory / "target-authorized.json") != target:
                raise UsageError("target process identity differs from its authorization")
        child = self._children.pop(directory.name, None)
        if child is not None:
            child.wait(timeout=5)
        self._event_once("worktree_process_completed", directory.name, result)
        return result

    def _stop_bound_processes(self, directory, recorded):
        launches = [row["payload"] for row in self.store.read("worktree_launch_intent")
                    if row["payload"].get("operation_key") == directory.name]
        if len(launches) != 1 or launches[0].get("execution_token") != recorded["execution_token"]:
            return
        for name in ("supervisor", "target"):
            path = directory / (name + ".json")
            try:
                identity = self._identity(read(path), recorded, launches[0]["spec_sha256"])
                if process_alive(identity["pid"], identity["start_ticks"]):
                    if name == "target":
                        os.killpg(identity["pid"], signal.SIGKILL)
                    else:
                        os.kill(identity["pid"], signal.SIGKILL)
            except (OSError, ValueError):
                continue

    @staticmethod
    def _meter(envelope, domain):
        try:
            result = envelope["evidence"]["evidence"]["eval_result"]
            if type(result["cost"]) is not dict or set(result["cost"]) != {field.name for field in fields(CostVec)}:
                raise UsageError("physical cost fields must be complete")
            cost = CostVec(**result["cost"])
            contract = result["contract"]
            if type(contract["measured_cost_units"]) is not list:
                raise UsageError("invalid measurement coverage declaration")
            coverage = tuple(contract["measured_cost_units"])
            # A meter probe has no producer binding and never leaves this method.
            # No missing result identity is filled from the caller's expectation.
            probe = EvalResult(EvalStatus.INVALID, cost=cost, contract=EvaluationContract(
                None, coverage, token_accounting=contract["token_accounting"]))
            measured_costs(probe, domain.measured_cost_units)
            return cost, coverage
        except (KeyError, TypeError, ValueError, UsageError) as error:
            raise UsageError("command response lacks a trustworthy complete cost meter") from error

    def _commit(self, directory, recorded, root, candidate_id):
        """Deterministic commit plan survives a crash on either side of update-ref."""
        parent = recorded["binding"]["request"]["resume_from"] or self.base_commit
        plan = {"parent": parent, "tree": self._raw_tree(root), "message": "evaluate " + candidate_id,
                "created_epoch": recorded["created_epoch"]}
        atomic(directory / "commit-plan.json", plan)
        self._event_once("worktree_commit_plan", directory.name, plan)
        env = dict(os.environ)
        for role in ("AUTHOR", "COMMITTER"):
            env["GIT_" + role + "_NAME"] = "AutoResearch"
            env["GIT_" + role + "_EMAIL"] = "autoresearch@localhost.invalid"
            env["GIT_" + role + "_DATE"] = "@" + str(recorded["created_epoch"]) + " +0000"
        process = subprocess.run(["git", "-c", "commit.gpgSign=false", "commit-tree", plan["tree"], "-p", parent, "-m", plan["message"]],
                                 cwd=root, env=env, capture_output=True, text=True)
        if process.returncode:
            raise ValueError("cannot persist evaluated artifact commit")
        head = process.stdout.strip()
        current = _git(root, "rev-parse", "HEAD")
        if current == parent:
            _git(root, "update-ref", "refs/heads/" + recorded["worktree_ref"], head, parent)
        elif current != head:
            raise ValueError("worktree head differs from its frozen artifact commit plan")
        atomic(directory / "artifact-commit.json", {"head": head, "tree": plan["tree"], "parent": parent})
        return head

    def _raw_tree(self, root):
        """Write raw Git objects without invoking filters, hooks or candidate code.

        Internal requests/responses include private producer data and never enter
        the public artifact commit. Symlinks are stored as link text, not followed.
        """
        def object_id(args, data):
            process = subprocess.run(["git", *args], cwd=root, input=data, capture_output=True)
            if process.returncode:
                raise ValueError("cannot persist raw worktree artifact object")
            return process.stdout.decode("ascii").strip()
        def tree(path):
            entries = []
            for item in sorted(path.iterdir(), key=lambda item: os.fsencode(item.name)):
                if item.name == ".git" or path == root and item.name == ".autoresearch-command":
                    continue
                metadata = item.lstat()
                if stat.S_ISDIR(metadata.st_mode):
                    oid = tree(item)
                    mode, kind = "040000", "tree"
                elif stat.S_ISLNK(metadata.st_mode):
                    oid = object_id(["hash-object", "--no-filters", "-w", "--stdin"], os.fsencode(os.readlink(item)))
                    mode, kind = "120000", "blob"
                elif stat.S_ISREG(metadata.st_mode):
                    descriptor = os.open(item, os.O_RDONLY | os.O_NOFOLLOW)
                    with os.fdopen(descriptor, "rb") as stream:
                        opened = os.fstat(stream.fileno())
                        if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
                            raise ValueError("artifact file changed while snapshotting")
                        oid = object_id(["hash-object", "--no-filters", "-w", "--stdin"], stream.read())
                    mode, kind = "100755" if metadata.st_mode & 0o111 else "100644", "blob"
                else:
                    raise ValueError("artifact tree contains an unsupported special file")
                entries.append(f"{mode} {kind} {oid}\t".encode() + os.fsencode(item.name) + b"\0")
            return object_id(["mktree", "-z"], b"".join(entries))
        return tree(root)

    def _complete(self, directory, recorded, result, expected, domain):
        raw_path = directory / "raw-response.json"
        if result["response_sha256"] is None or not raw_path.is_file() or raw_path.is_symlink() \
                or _file_digest(raw_path) != result["response_sha256"]:
            raise UsageError("command response is missing or changed; measured usage is unknown")
        try:
            envelope = _strict_json(raw_path.read_bytes())
        except (ValueError, UnicodeError) as error:
            raise UsageError("command response is not strict JSON; measured usage is unknown") from error
        cost, coverage = self._meter(envelope, domain)
        try:
            if type(envelope) is not dict or set(envelope) != {
                    "schema_version", "operation_key", "execution_token", "request_sha256", "evidence"} \
                    or type(envelope["schema_version"]) is not int or envelope["schema_version"] != 1 \
                    or envelope["operation_key"] != directory.name \
                    or envelope["execution_token"] != recorded["execution_token"] \
                    or envelope["request_sha256"] != result["request_sha256"]:
                raise ValueError("command response invocation binding mismatch")
            evidence = decode_evidence(envelope["evidence"], expected_binding=expected,
                                       required_cost_units=domain.measured_cost_units)
            if (result["returncode"] != 0 or result["timeout"]) and evidence.eval_result.status is EvalStatus.OK:
                raise ValueError("failed command cannot attest successful evaluation")
            saved = directory / "completion.json"
            if saved.exists():
                completed = read(saved)
                if type(completed) is not dict or set(completed) != {"response_sha256", "evidence", "wall_seconds"} \
                        or completed["response_sha256"] != result["response_sha256"] \
                        or completed["wall_seconds"] != result["wall_seconds"]:
                    raise ValueError("completed command response changed")
                saved_evidence = decode_evidence(completed["evidence"], expected_binding=expected,
                                                required_cost_units=domain.measured_cost_units)
                if replace(saved_evidence, branch_ref=evidence.branch_ref) != evidence \
                        or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", saved_evidence.branch_ref or "") \
                        or _git(self.workspace.base_repo, "cat-file", "-t", saved_evidence.branch_ref) != "commit":
                    raise ValueError("cached completion differs from the original producer response")
                artifact = read(directory / "artifact-commit.json")
                plan = read(directory / "commit-plan.json")
                plans = [row["payload"] for row in self.store.read("worktree_commit_plan")
                         if row["payload"].get("operation_key") == directory.name]
                if plans != [{"operation_key": directory.name, **plan}] \
                        or artifact != {"head": saved_evidence.branch_ref, "tree": plan["tree"], "parent": plan["parent"]} \
                        or _git(self.workspace.base_repo, "rev-parse", artifact["head"] + "^{tree}") != plan["tree"] \
                        or _git(self.workspace.base_repo, "rev-parse", artifact["head"] + "^") != plan["parent"]:
                    raise ValueError("cached artifact commit differs from its durable creation plan")
                evidence = saved_evidence
            else:
                root = self._adopt(recorded)
                if not (directory / "commit-plan.json").exists() and _git(root, "rev-parse", "HEAD") != (
                        recorded["binding"]["request"]["resume_from"] or self.base_commit):
                    raise ValueError("candidate worktree base commit changed during execution")
                verify_manifest(root, self.protected, self.protected_paths)
                if safe_relative(root, self.artifact_path).read_text(encoding="utf-8") != recorded["binding"]["proposal"]["artifact"]:
                    raise ValueError("evaluated candidate artifact changed during execution")
                head = self._commit(directory, recorded, root, evidence.candidate_id)
                evidence = replace(evidence, branch_ref=head)
                completed = {"response_sha256": result["response_sha256"], "evidence": encode_evidence(evidence),
                             "wall_seconds": result["wall_seconds"]}
                atomic(saved, completed)
            self._event_once("worktree_evidence", directory.name, completed)
            return evidence
        except (ValueError, OSError, RuntimeError) as error:
            rejection = {"reason": type(error).__name__ + ": " + str(error), "cost": asdict(cost),
                "measured_cost_units": list(coverage), "response_sha256": result["response_sha256"]}
            self._event_once("worktree_rejected_result", directory.name, rejection)
            raise MeasuredCommandError(str(error), cost, coverage, raw_response_path=raw_path,
                                       wall_seconds=result["wall_seconds"]) from error

    def cleanup(self, operation):
        """Explicitly release a completed worktree after the caller settles/checkpoints."""
        directory = self.operation_path(operation)
        with _lease(directory / "coordinator.lock"):
            if not (directory / "completion.json").exists():
                raise ValueError("cannot clean an unfinished or rejected operation")
            recorded = read(directory / "operation.json")
            root = Path(recorded["worktree_path"])
            if root.exists():
                self._adopt(recorded)
                self.workspace.destroy(recorded["worktree_ref"])
            self._event_once("worktree_cleaned", directory.name, {"worktree_ref": recorded["worktree_ref"]})

    def operation_metadata(self, operation):
        """Read durable execution timing; an adopting owner's wait is not usage."""
        directory = self.operation_path(operation)
        recorded = read(directory / "operation.json")
        if recorded["binding"]["operation"] != self._operation(operation):
            raise ValueError("operation metadata binding mismatch")
        result = read(directory / "process-result.json")
        rows = [row["payload"] for row in self.store.read("worktree_process_completed")
                if row["payload"].get("operation_key") == directory.name]
        if rows != [{"operation_key": directory.name, **result}]:
            raise ValueError("operation timing lacks its validated durable completion")
        completed = read(directory / "completion.json") if (directory / "completion.json").exists() else None
        return {"operation_key": directory.name, "execution_token": recorded["execution_token"],
            "wall_seconds": result["wall_seconds"], "worktree_ref": recorded["worktree_ref"],
            "branch_ref": completed["evidence"]["evidence"]["branch_ref"] if completed else None,
            "raw_response_path": str(directory / "raw-response.json"),
            "security_boundary": recorded["binding"]["executor"]["security_boundary"]}
