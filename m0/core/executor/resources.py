"""Explicit POSIX resource limits inherited by an external evaluation process tree."""
from __future__ import annotations

from dataclasses import dataclass
import resource


@dataclass(frozen=True)
class ResourcePolicy:
    """Optional per-process limits; this is not a cgroup or aggregate quota."""

    memory_bytes: int | None = None
    file_bytes: int | None = None
    process_count: int | None = None

    def __post_init__(self) -> None:
        for name in ("memory_bytes", "file_bytes", "process_count"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool)
                                      or not isinstance(value, int) or value <= 0):
                raise ValueError(f"{name} must be a positive integer or None")
        required = {"memory_bytes": "RLIMIT_AS", "file_bytes": "RLIMIT_FSIZE",
                    "process_count": "RLIMIT_NPROC"}
        missing = [constant for field, constant in required.items()
                   if getattr(self, field) is not None and not hasattr(resource, constant)]
        if missing:
            raise RuntimeError(f"resource policy is unsupported: {', '.join(missing)}")

    def as_dict(self) -> dict[str, int]:
        """Return only configured non-sensitive limits for the durable process spec."""
        return {name: value for name in ("memory_bytes", "file_bytes", "process_count")
                if (value := getattr(self, name)) is not None}
