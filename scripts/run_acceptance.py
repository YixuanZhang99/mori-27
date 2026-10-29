#!/usr/bin/env python3
"""Run v65 in a disposable copy with fresh evidence and bounded execution.

Cleanup covers the verifier process group. Workers that deliberately create a
new session are outside that scope; hosted CI's disposable VM is the final
isolation boundary for those processes.
"""
from __future__ import annotations

import argparse
import codecs
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
VERIFIER_VERSION = "v65"
HISTORY = (f"verifier/{VERIFIER_VERSION}/LAST_RUN.json",
           f"verifier/runs/{VERIFIER_VERSION}.jsonl")
VERIFIER_COMMAND = f"python3 verifier/{VERIFIER_VERSION}/verify.py"
CONTROL_FILES = (".github/workflows/ci.yml", "Makefile", "scripts/run_acceptance.py")
MAX_LOG_BYTES = 32 * 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def history_snapshot() -> dict[str, str | None]:
    """Bind existing history and the absence of a new version's first records."""
    source = ROOT / "m0"
    names = set(HISTORY)
    for pattern in ("verifier/v*/LAST_RUN.json", "verifier/runs/*.jsonl"):
        names.update(str(path.relative_to(source)) for path in source.glob(pattern))
    return {name: digest(source / name) for name in sorted(names)}


def _stop_process_group(process: subprocess.Popen[bytes]) -> None:
    """Reap the verifier and terminate remaining members of its own session."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass
    # The leader can exit before a child that ignores SIGTERM. Address the group
    # again even if process.poll() already has an exit code.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=5)
    if process.stdout is not None:
        process.stdout.close()


def _stream_process(process: subprocess.Popen[bytes], log, timeout: float) -> int:
    """Drain fixed-size chunks; neither an unterminated line nor output can grow unbounded."""
    assert process.stdout is not None
    deadline = time.monotonic() + timeout
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    written = 0
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while selector.get_map() or process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(process.args, timeout)
            if not selector.get_map():
                time.sleep(min(0.1, remaining))
                continue
            for key, _ in selector.select(timeout=min(0.2, remaining)):
                chunk = os.read(key.fileobj.fileno(), READ_CHUNK_BYTES)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                if written + len(chunk) > MAX_LOG_BYTES:
                    available = MAX_LOG_BYTES - written
                    log.write(chunk[:available])
                    log.flush()
                    raise RuntimeError(f"Verifier output exceeded {MAX_LOG_BYTES} bytes")
                written += len(chunk)
                log.write(chunk)
                log.flush()
                print(decoder.decode(chunk), end="", flush=True)
        print(decoder.decode(b"", final=True), end="", flush=True)
    return process.wait(timeout=1)


def _passing_checks(checks: object) -> bool:
    if not isinstance(checks, list) or not checks:
        return False
    if not all(isinstance(item, dict) and item.get("passed") is True
               and isinstance(item.get("check"), str) and item["check"]
               for item in checks):
        return False
    return len({item["check"] for item in checks}) == len(checks)


def _signal_interrupt(signum: int, _frame) -> None:
    raise InterruptedError(f"Acceptance interrupted by signal {signum}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/linux-acceptance")
    parser.add_argument("--timeout", type=float, default=1800,
                        help="Overall verifier deadline in seconds (default: 1800)")
    args = parser.parse_args(argv)
    if not 0 < args.timeout < float("inf"):
        parser.error("--timeout must be a finite positive number")

    # A unique directory prevents a failed or interrupted run from exposing an
    # earlier run's success. If the filesystem cannot create it, fail immediately.
    output_base = args.output.resolve()
    output_base.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    output = Path(tempfile.mkdtemp(prefix=timestamp + "-", dir=output_base))
    errors: list[str] = []
    before: dict[str, str | None] = {}
    copy: Path | None = None
    scratch = None
    process = None
    previous_journal: bytes | None = None
    new_journal: bytes | None = None
    returncode = None
    timed_out = False
    started = time.monotonic()
    original_sigterm = None
    if threading.current_thread() is threading.main_thread():
        original_sigterm = signal.signal(signal.SIGTERM, _signal_interrupt)
    try:
        before = history_snapshot()
        environment = {key: value for key, value in os.environ.items()
                       if "API_KEY" not in key.upper() and not key.upper().endswith("_TOKEN")}
        environment.update(PYTHONDONTWRITEBYTECODE="1",
                           PYTEST_ADDOPTS="--strict-markers --fail-on-skip")
        scratch = tempfile.TemporaryDirectory(prefix="mori27-acceptance-")
        copy = Path(scratch.name) / "m0"
        shutil.copytree(ROOT / "m0", copy, ignore=shutil.ignore_patterns(
            ".venv", "__pycache__", ".pytest_cache", "*.egg-info", "build", "dist"))
        # v65 inspects the active repository workflow rather than m0's archived
        # nested workflow. Keep that source context beside the isolated copy.
        for name in CONTROL_FILES:
            source = ROOT / name
            if source.is_file():
                destination = copy.parent / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
        # Historical success is never an output from this invocation.
        (copy / HISTORY[0]).unlink(missing_ok=True)
        previous_journal = ((copy / HISTORY[1]).read_bytes()
                            if (copy / HISTORY[1]).exists() else b"")
        environment["PYTHONPATH"] = str(copy)
        with (output / "console.log").open("wb") as log:
            process = subprocess.Popen([sys.executable, f"verifier/{VERIFIER_VERSION}/verify.py"],
                cwd=copy, env=environment, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, start_new_session=True)
            returncode = _stream_process(process, log, args.timeout)
    except (Exception, KeyboardInterrupt, SystemExit) as exc:
        timed_out = isinstance(exc, subprocess.TimeoutExpired)
        errors.append(f"{type(exc).__name__}: {exc}")
    finally:
        # Restore the caller's handler before cleanup; the verifier deadline is
        # shorter than the CI job timeout so normal cleanup has time to complete.
        if original_sigterm is not None:
            signal.signal(signal.SIGTERM, original_sigterm)
        if process is not None:
            try:
                _stop_process_group(process)
                if returncode is None:
                    returncode = process.returncode
            except Exception as exc:
                errors.append(f"Process cleanup failed: {type(exc).__name__}: {exc}")
        if copy is not None:
            for name in HISTORY:
                try:
                    if (copy / name).exists():
                        shutil.copy2(copy / name, output / Path(name).name)
                except OSError as exc:
                    errors.append(f"Could not preserve {name}: {exc}")
            try:
                journal = (copy / HISTORY[1]).read_bytes()
                if previous_journal is None or not journal.startswith(previous_journal):
                    errors.append("Verifier rewrote its historical journal prefix")
                else:
                    new_journal = journal[len(previous_journal):]
                    (output / "new-runs.jsonl").write_bytes(new_journal)
            except OSError as exc:
                errors.append(f"Could not read verifier journal: {exc}")
        if scratch is not None:
            try:
                scratch.cleanup()
            except OSError as exc:
                errors.append(f"Temporary workspace cleanup failed: {exc}")

    unchanged = False
    try:
        unchanged = len(before) >= len(HISTORY) and before == history_snapshot()
        if not unchanged:
            errors.append("Source history could not be verified unchanged")
    except OSError as exc:
        errors.append(f"Could not verify source history: {exc}")

    certificate_passed = False
    certificate_checks = None
    try:
        certificate = json.loads((output / "LAST_RUN.json").read_text(encoding="utf-8"))
        certificate_passed = (isinstance(certificate, dict)
                              and certificate.get("version") == VERIFIER_VERSION
                              and certificate.get("passed") is True
                              and _passing_checks(certificate.get("checks")))
        if not certificate_passed:
            errors.append(f"Fresh {VERIFIER_VERSION} certificate does not contain passing checks")
        elif isinstance(certificate, dict):
            certificate_checks = certificate["checks"]
    except (OSError, ValueError) as exc:
        errors.append(f"Fresh certificate is missing or malformed: {type(exc).__name__}: {exc}")

    journal_passed = False
    try:
        entries = [json.loads(line) for line in (new_journal or b"").splitlines() if line.strip()]
        if len(entries) != 1:
            raise ValueError(f"Expected exactly one new journal entry, got {len(entries)}")
        entry = entries[0]
        journal_passed = (isinstance(entry, dict)
                          and type(entry.get("exit_code")) is int
                          and entry["exit_code"] == 0
                          and entry.get("command") == VERIFIER_COMMAND
                          and _passing_checks(entry.get("checks"))
                          and entry["checks"] == certificate_checks)
        if not journal_passed:
            errors.append("Fresh journal entry is not passing or does not match the certificate")
    except (ValueError, UnicodeError) as exc:
        errors.append(f"Fresh journal is missing or malformed: {type(exc).__name__}: {exc}")

    if returncode != 0:
        errors.append(f"Verifier did not exit successfully: {returncode}")
    success = (returncode == 0 and certificate_passed and journal_passed
               and unchanged and not errors)
    summary = {"run_id": output.name, "verifier_version": VERIFIER_VERSION,
               "verifier_exit_code": returncode,
               "certificate_passed": certificate_passed,
               "new_journal_passed": journal_passed,
               "source_history_unchanged": unchanged,
               "timeout_seconds": args.timeout, "timed_out": timed_out,
               "elapsed_seconds": round(time.monotonic() - started, 3),
               "cleanup_scope": "verifier process group; independently detached workers require runner isolation",
               "error": errors[0] if errors else None, "errors": errors, "passed": success}
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**summary, "artifacts": str(output)}, indent=2))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
