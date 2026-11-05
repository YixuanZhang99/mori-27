"""Immutable native artifact publication; no budget, retrieval or evaluation."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile

from core.composition.contracts import json_copy


class NativeArtifactBackend:
    def __init__(self, root):
        root = Path(root)
        if root.is_symlink():
            raise ValueError("artifact root cannot be a symlink")
        root.mkdir(parents=True, exist_ok=True)
        self.root = root.resolve()

    @property
    def manifest_binding(self):
        return {"schema_version": 1, "kind": "native_text_v1"}

    @staticmethod
    def _descriptor(value):
        value = json_copy(value, label="artifact descriptor")
        if type(value) is not dict or set(value) != {"schema_version", "kind", "reference", "size_bytes"} \
                or type(value["schema_version"]) is not int or value["schema_version"] != 1 \
                or value["kind"] != "native_text_v1" or type(value["reference"]) is not str \
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", value["reference"]) \
                or type(value["size_bytes"]) is not int or value["size_bytes"] < 1:
            raise ValueError("invalid immutable native artifact descriptor")
        return value

    def load(self, descriptor):
        descriptor = self._descriptor(descriptor)
        path = self.root / (descriptor["reference"][7:] + ".blob")
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size != descriptor["size_bytes"]:
                    raise ValueError("artifact type or size changed")
                raw = stream.read()
        except OSError as error:
            raise ValueError("immutable artifact is unavailable") from error
        if "sha256:" + hashlib.sha256(raw).hexdigest() != descriptor["reference"]:
            raise ValueError("immutable artifact content changed")
        return raw.decode("utf-8")

    def publish(self, artifact, *, operation):
        if type(artifact) is not str or not artifact.strip():
            raise ValueError("native publication requires nonempty artifact text")
        raw = artifact.encode("utf-8")
        descriptor = {"schema_version": 1, "kind": "native_text_v1",
            "reference": "sha256:" + hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}
        target = self.root / (descriptor["reference"][7:] + ".blob")
        if target.exists() or target.is_symlink():
            if self.load(descriptor) != artifact:
                raise ValueError("artifact publication differs from existing immutable content")
            return descriptor
        fd, name = tempfile.mkstemp(prefix=".publication-", dir=self.root)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target, follow_symlinks=False)
            except FileExistsError:
                if self.load(descriptor) != artifact:
                    raise ValueError("concurrent artifact publication differs")
            parent = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
        finally:
            temporary.unlink(missing_ok=True)
        return descriptor
