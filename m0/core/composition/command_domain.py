"""Content-bound native evaluation commands for the configured worktree executor."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

from core.composition.evaluation import COST_UNITS, validate_request
from core.executor.workspace import protected_manifest, safe_relative


def digest(value):
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                                ensure_ascii=False, allow_nan=False).encode()).hexdigest()


class CommandDomain:
    """The command must return a canonical, producer-bound evaluation envelope.

    Invocation arguments are request.json and response.json. The request includes
    all EvalRequest fields, concrete split paths, the candidate artifact and the
    expected producer binding. `git_worktree` is required to execute this domain.
    """
    required_executor = "git_worktree"
    def __init__(self, command, *, evaluator_version, data_dir, split_paths,
                 fidelities=("dev", "admission", "final_audit"),
                 measured_cost_units=("token", "eval_count", "node"), time_limit=120,
                 supports_resume=False):
        if type(command) not in (list, tuple) or not command or any(type(x) is not str or not x for x in command):
            raise ValueError("command requires a nonempty argv list")
        if type(evaluator_version) is not str or not evaluator_version.strip():
            raise ValueError("evaluator_version is required")
        if type(split_paths) is not dict or "dev" not in split_paths or any(
                type(k) is not str or not k.strip() or type(v) is not str for k, v in split_paths.items()):
            raise ValueError("split_paths must declare content-bound dev and optional held-out splits")
        if type(fidelities) not in (list, tuple) or not fidelities or any(
                type(x) is not str or not x.strip() for x in fidelities) or len(set(fidelities)) != len(fidelities):
            raise ValueError("fidelities must be distinct nonempty names")
        if type(measured_cost_units) not in (list, tuple) or not {"token", "eval_count"} <= set(measured_cost_units) \
                or any(type(x) is not str or x not in COST_UNITS for x in measured_cost_units) \
                or len(set(measured_cost_units)) != len(measured_cost_units):
            raise ValueError("command must explicitly measure token and evaluation costs")
        if type(time_limit) is not int or time_limit <= 0 or type(supports_resume) is not bool:
            raise ValueError("invalid command limits or resume declaration")
        executable = command[0]
        if not Path(executable).is_absolute():
            if "/" in executable:
                raise ValueError("use an absolute executable or a PATH name, plus protected relative script arguments")
            executable = shutil.which(executable)
            if executable is None:
                raise ValueError("command executable is not available on PATH")
        executable = str(Path(executable).absolute())
        if not Path(executable).is_file():
            raise ValueError("command executable must be an existing file")
        self.command, self.evaluator_version = (executable, *command[1:]), evaluator_version
        self._command_files = {part: "sha256:" + hashlib.sha256(Path(part).read_bytes()).hexdigest()
                               for part in self.command if Path(part).is_absolute() and Path(part).is_file()}
        self.data_dir = str(Path(data_dir).resolve())
        if not Path(self.data_dir).is_dir():
            raise ValueError("data_dir must exist")
        self.split_paths, self.fidelities = dict(split_paths), tuple(fidelities)
        self.measured_cost_units = tuple(measured_cost_units)
        self.time_limit, self.supports_resume = time_limit, supports_resume
        self._manifests = {key: protected_manifest(self.data_dir, (path,)) for key, path in self.split_paths.items()}
        # Renaming an identical dataset must not pretend it is a held-out split.
        self._contexts = {key: digest(sorted(manifest.values())) for key, manifest in self._manifests.items()}

    @property
    def evaluation_context(self):
        return self._contexts["dev"]

    @property
    def manifest_binding(self):
        return {"kind": "worktree_command_v1", "command": list(self.command),
            "command_files": dict(self._command_files),
            "evaluator_version": self.evaluator_version, "data_dir": self.data_dir,
            "split_paths": dict(self.split_paths), "evaluation_contexts": dict(self._contexts),
            "fidelities": list(self.fidelities), "measured_cost_units": list(self.measured_cost_units),
            "time_limit": self.time_limit, "supports_resume": self.supports_resume}

    def validate_context(self):
        if any(not Path(path).is_file() or "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected
               for path, expected in self._command_files.items()):
            raise ValueError("command executable or script content changed")
        if any(protected_manifest(self.data_dir, (path,)) != self._manifests[key]
               for key, path in self.split_paths.items()):
            raise ValueError("command dataset content changed")

    def validate_request(self, request):
        validate_request(request)
        self.validate_context()
        if request.fidelity not in self.fidelities or request.split_id not in self.split_paths:
            raise ValueError("unsupported command fidelity or split")
        if request.resume_from is not None and not self.supports_resume:
            raise ValueError("command does not support resume_from")

    def evaluation_context_for(self, request):
        self.validate_request(request)
        return self._contexts[request.split_id]

    def split_path_for(self, request):
        self.validate_request(request)
        return str(safe_relative(Path(self.data_dir), self.split_paths[request.split_id]))

    async def evaluate(self, proposal, request):
        raise RuntimeError("CommandDomain requires the git_worktree executor and an explicit bound operation")
