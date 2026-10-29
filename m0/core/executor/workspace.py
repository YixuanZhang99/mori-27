"""Low-cost isolated git-worktree backend and protected-path manifests."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import threading
import uuid
from pathlib import Path

from core.executor.types import ArtifactRef


def _run(args: list[str], cwd: Path | None = None) -> str:
    proc = subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False)
    if proc.returncode:
        detail = (proc.stderr or proc.stdout).strip()
        raise RuntimeError(f"git command failed: {detail[-1000:]}")
    return proc.stdout.strip()


def safe_relative(root: Path, relative: str) -> Path:
    if not relative or relative == ".":
        raise ValueError("protected and required paths must name a file or directory")
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts or ".git" in rel.parts:
        raise ValueError(f"unsafe workspace-relative path: {relative}")
    path = root / rel
    current = path
    while current != root:
        if current.is_symlink():
            raise ValueError(f"symlink is not allowed in governed paths: {relative}")
        current = current.parent
    return path


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def protected_manifest(root: str | Path, protected_paths: tuple[str, ...] | list[str]) -> dict[str, str]:
    """Hash protected files/directories without following symlinks."""
    base = Path(root).resolve()
    manifest: dict[str, str] = {}
    for relative in sorted(protected_paths):
        path = safe_relative(base, relative)
        if not path.exists():
            raise ValueError(f"protected path is missing: {relative}")
        paths = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
        if not paths:
            raise ValueError(f"protected path contains no files: {relative}")
        for item in paths:
            if item.is_symlink():
                raise ValueError(f"protected symlink is forbidden: {item.relative_to(base)}")
            key = item.relative_to(base).as_posix()
            manifest[key] = _file_digest(item)
    return manifest


def verify_manifest(root: str | Path, expected: dict[str, str],
                    protected_paths: tuple[str, ...] | list[str]) -> None:
    actual = protected_manifest(root, protected_paths)
    if actual != expected:
        changed = sorted(key for key in set(actual) | set(expected)
                         if actual.get(key) != expected.get(key))
        raise ValueError("protected paths modified: " + ", ".join(changed))


class GitWorktree:
    """Fork candidates onto persistent branches; destroy only the working copy."""

    def __init__(self, base_repo: str | Path, run_root: str | Path):
        self.base_repo = Path(base_repo).resolve()
        self.run_root = Path(run_root).resolve()
        if self.run_root == self.base_repo or self.base_repo in self.run_root.parents:
            raise ValueError("run_root must be outside base_repo")
        self.run_root.mkdir(parents=True, exist_ok=True)
        if not (self.base_repo / ".git").exists():
            raise ValueError("base_repo must be a git repository")
        self._paths: dict[ArtifactRef, Path] = {}
        self._lock = threading.RLock()

    def fork(self, base: ArtifactRef) -> ArtifactRef:
        if not base or base.startswith("-"):
            raise ValueError("base must be a git commit or branch ref")
        with self._lock:
            _run(["git", "rev-parse", "--verify", f"{base}^{{commit}}"], cwd=self.base_repo)
            branch = "candidate/" + uuid.uuid4().hex
            path = self.run_root / re.sub(r"[^a-zA-Z0-9_.-]", "-", branch)
            _run(["git", "worktree", "add", "--quiet", "-b", branch, str(path), base],
                 cwd=self.base_repo)
            self._paths[branch] = path
            return branch

    def path_for(self, ref: ArtifactRef) -> Path:
        with self._lock:
            if ref not in self._paths:
                raise ValueError("unknown active worktree ref")
            return self._paths[ref]

    def adopt(self, ref: ArtifactRef, path: str | Path) -> Path:
        """Re-adopt an existing candidate worktree after an owner restart."""
        with self._lock:
            if not ref.startswith("candidate/") or ".." in ref:
                raise ValueError("only candidate worktree branches can be adopted")
            expected = (self.run_root / re.sub(r"[^a-zA-Z0-9_.-]", "-", ref)).resolve()
            actual = Path(path).resolve()
            if actual != expected or not actual.is_dir():
                raise ValueError("worktree path does not match the recorded candidate ref")
            top = Path(_run(["git", "rev-parse", "--show-toplevel"], cwd=actual)).resolve()
            branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=actual)
            if top != actual or branch != ref:
                raise ValueError("worktree path and branch identity do not match")
            _run(["git", "rev-parse", "--verify", f"refs/heads/{ref}"], cwd=self.base_repo)
            self._paths[ref] = actual
            return actual

    def commit(self, ref: ArtifactRef, message: str,
               force_paths: tuple[str, ...] = ()) -> ArtifactRef:
        with self._lock:
            path = self.path_for(ref)
            _run(["git", "add", "-A"], cwd=path)
            for relative in force_paths:
                target = safe_relative(path, relative)
                if target.exists():
                    _run(["git", "add", "-f", "--", relative], cwd=path)
            changed = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=path,
                                     check=False).returncode
            if changed:
                _run(["git", "commit", "--quiet", "-m", message], cwd=path)
            return _run(["git", "rev-parse", "HEAD"], cwd=path)

    def manifest(self, ref: ArtifactRef, protected_paths) -> dict[str, str]:
        return protected_manifest(self.path_for(ref), protected_paths)

    def destroy(self, ref: ArtifactRef) -> None:
        with self._lock:
            path = self._paths.pop(ref, None)
            if path is None:
                return
            try:
                _run(["git", "worktree", "remove", "--force", str(path)], cwd=self.base_repo)
            finally:
                if path.exists():
                    shutil.rmtree(path)
        # The candidate branch and commit remain: EvidenceRecord.branch_ref must
        # continue to resolve after the working directory is gone.

    def audit_manifest(self, ref: ArtifactRef) -> dict[str, str]:
        """Return a stable branch/commit descriptor for append-only evidence."""
        with self._lock:
            return {"branch_ref": ref,
                    "head": _run(["git", "rev-parse", ref], cwd=self.base_repo),
                    "descriptor_sha256": hashlib.sha256(
                        json.dumps({"branch": ref}, sort_keys=True).encode()).hexdigest()}
