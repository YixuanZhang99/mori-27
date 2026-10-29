"""Durable detached-process journal with PID-reuse and orphan guards."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import uuid
from pathlib import Path

from core.executor.process_identity import process_alive, start_ticks
from core.executor.seccomp import (SECCOMP_BWRAP_MEMFD, SECCOMP_POLICY_VERSION,
                                   seccomp_policy_summary,
                                   validate_seccomp_delivery, validate_seccomp_policy)
from core.x1.store import AppendOnlyStore


def _read_json(path: str | Path) -> dict | None:
    source = Path(path)
    if not source.exists():
        return None
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("process journal JSON must contain an object")
    return payload


class ProcessJournal:
    def __init__(self, store: AppendOnlyStore):
        self.store = store
        self.root = store.path.parent / "executor-processes"
        self.root.mkdir(parents=True, exist_ok=True)

    def launch(self, args: list[str], cwd: Path, env: dict,
               time_limit: int | None, metadata: dict,
               resource_limits: dict | None = None,
               seccomp_policy: dict | None = None,
               seccomp_delivery: str | None = None) -> tuple[subprocess.Popen, dict]:
        if seccomp_policy is not None:
            validate_seccomp_policy(seccomp_policy)
            if seccomp_delivery is None:
                seccomp_delivery = SECCOMP_BWRAP_MEMFD  # v56 caller compatibility
        validate_seccomp_delivery(seccomp_policy, seccomp_delivery)
        execution_id = uuid.uuid4().hex
        directory = self.root / execution_id
        directory.mkdir()
        paths = {name + "_path": str(directory / f"{name}.json")
                 for name in ("spec", "result", "target")}
        stdout_path, stderr_path = directory / "stdout.txt", directory / "stderr.txt"
        spec = {"args": args, "cwd": str(cwd), "time_limit": time_limit,
                "resource_limits": resource_limits or {},
                "seccomp_policy": seccomp_policy,
                "seccomp_delivery": seccomp_delivery,
                "stdout_path": str(stdout_path), "stderr_path": str(stderr_path),
                "result_path": paths["result_path"], "target_path": paths["target_path"]}
        Path(paths["spec_path"]).write_text(json.dumps(spec, ensure_ascii=False),
                                            encoding="utf-8")
        wrapper = Path(__file__).with_name("process_wrapper.py")
        # The wrapper inherits env; credentials and other environment values are
        # deliberately absent from the on-disk spec and append-only journal.
        bootstrap = ("import runpy,sys; script=sys.argv[1]; "
                     "sys.argv=[script]+sys.argv[2:]; "
                     "runpy.run_path(script, run_name='__main__')")
        proc = subprocess.Popen([sys.executable, "-c", bootstrap,
                                 str(wrapper), paths["spec_path"]],
                                cwd=cwd, env=env, start_new_session=True)
        record = {**metadata, "execution_id": execution_id,
                  "seccomp_policy": seccomp_policy_summary(seccomp_policy),
                  "seccomp_delivery": seccomp_delivery,
                  "wrapper_pid": proc.pid, "wrapper_start_ticks": start_ticks(proc.pid),
                  **paths, "stdout_path": str(stdout_path),
                  "stderr_path": str(stderr_path)}
        if record["wrapper_start_ticks"] is None:
            proc.kill()
            proc.wait()
            raise RuntimeError("process recovery requires a stable OS start identity")
        self.store.append("executor_process_started", record)
        return proc, record

    def completed_result(self, record: dict) -> dict:
        """Read a durable result without appending another terminal event."""
        result = _read_json(record["result_path"])
        if result is None:
            raise ValueError("process result is missing")
        returncode = result.get("returncode")
        timeout = result.get("timeout")
        if isinstance(returncode, bool) or not isinstance(returncode, int) \
                or not isinstance(timeout, bool):
            raise ValueError("invalid process result payload")
        return {"returncode": returncode, "timeout": timeout,
                "stdout": Path(record["stdout_path"]).read_text(encoding="utf-8"),
                "stderr": Path(record["stderr_path"]).read_text(encoding="utf-8"),
                "wrapper_error": result.get("wrapper_error")}

    def _completed(self, record: dict, recovered: bool) -> dict:
        completed = self.completed_result(record)
        self.store.append("executor_process_finished", {
            "execution_id": record["execution_id"],
            "candidate_id": record["candidate_id"], "attempt": record["attempt"],
            "returncode": completed["returncode"], "timeout": completed["timeout"],
            "recovered": recovered})
        return completed

    def wait(self, proc: subprocess.Popen, record: dict) -> dict:
        proc.wait()
        return self._completed(record, recovered=False)

    def fail(self, record: dict, detail: str) -> None:
        """Close an unrecoverable attempt without inventing a target result."""
        self.store.append("executor_process_finished", {
            "execution_id": record["execution_id"],
            "candidate_id": record["candidate_id"], "attempt": record["attempt"],
            "returncode": None, "timeout": False, "recovered": True,
            "lost": True, "detail": detail})

    @staticmethod
    def terminate_target(record: dict) -> None:
        try:
            target = _read_json(record["target_path"]) or {}
        except (OSError, ValueError):
            return
        target_pid = target.get("pid")
        if isinstance(target_pid, int) and not isinstance(target_pid, bool) \
                and process_alive(target_pid, target.get("start_ticks")):
            try:
                os.killpg(target_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    @staticmethod
    def _validate_recovery_policy(record: dict) -> None:
        """Bind unfinished operations to the full canonical persisted policy."""
        spec = _read_json(record["spec_path"]) if record.get("spec_path") else None
        policy = spec.get("seccomp_policy") if spec is not None else None
        summary = record.get("seccomp_policy")
        if policy is None and summary is None:
            # Explicitly unfiltered executions keep their existing recovery contract.
            validate_seccomp_delivery(None, record.get("seccomp_delivery"))
            if spec is not None:
                validate_seccomp_delivery(None, spec.get("seccomp_delivery"))
            return
        if spec is None:
            raise ValueError("seccomp recovery requires its durable full policy spec")
        validate_seccomp_policy(policy)
        if summary != seccomp_policy_summary(policy):
            raise ValueError("seccomp journal summary differs from its durable policy")
        delivery = validate_seccomp_delivery(policy, spec.get("seccomp_delivery"))
        if delivery != record.get("seccomp_delivery"):
            raise ValueError("seccomp journal delivery differs from its durable policy")

    def _block_policy_recovery(self, record: dict, error: Exception) -> None:
        # Stop the wrapper first so it cannot deliberately launch another target.
        # Both kills require the original OS start identity; a reused PID is never
        # sufficient authorization to signal an unrelated process.
        if process_alive(record["wrapper_pid"], record.get("wrapper_start_ticks")):
            try:
                os.kill(record["wrapper_pid"], signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.terminate_target(record)
        detail = f"seccomp recovery refused; explicit reconciliation required: {error}"
        previous = [row for row in self.store.read("executor_process_recovery_blocked")
                    if row["payload"].get("execution_id") == record["execution_id"]]
        if not previous:
            self.store.append("executor_process_recovery_blocked", {
                "execution_id": record["execution_id"],
                "candidate_id": record["candidate_id"], "attempt": record["attempt"],
                "required_policy_version": SECCOMP_POLICY_VERSION,
                "recorded_seccomp_policy": record.get("seccomp_policy"),
                "detail": detail})
        # No terminal result is invented and no reserve can be settled or released
        # by an ordinary lost-process fallback. Evidence remains available for review.
        raise RuntimeError(detail) from error

    def recover(self, record: dict) -> dict:
        if record["execution_id"] in self.finished_ids():
            # Already-completed historical executions remain readable under the
            # policy they actually used; never rewrite their record as current.
            return {"status": "finished", **self.completed_result(record)}
        try:
            self._validate_recovery_policy(record)
        except (OSError, ValueError, RuntimeError, UnicodeError) as error:
            self._block_policy_recovery(record, error)
        if Path(record["result_path"]).exists():
            try:
                return {"status": "finished", **self._completed(record, recovered=True)}
            except (OSError, ValueError, UnicodeError) as exc:
                if process_alive(record["wrapper_pid"], record.get("wrapper_start_ticks")):
                    try:
                        os.kill(record["wrapper_pid"], signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                self.terminate_target(record)
                return {"status": "lost", "execution_id": record["execution_id"],
                        "detail": f"invalid durable process result: {exc}"}
        if process_alive(record["wrapper_pid"], record.get("wrapper_start_ticks")):
            return {"status": "pending", "execution_id": record["execution_id"]}
        self.terminate_target(record)
        return {"status": "lost", "execution_id": record["execution_id"],
                "detail": "detached wrapper exited without an atomic result"}

    def started(self, execution_ref: str | None = None) -> list[dict]:
        return [record["payload"] for record in self.store.read("executor_process_started")
                if execution_ref is None
                or record["payload"].get("execution_ref") == execution_ref]

    def finished_ids(self) -> set[str]:
        return {record["payload"]["execution_id"]
                for record in self.store.read("executor_process_finished")}

    def unfinished(self, execution_ref: str | None = None) -> list[dict]:
        finished = self.finished_ids()
        return [record for record in self.started(execution_ref)
                if record["execution_id"] not in finished]
