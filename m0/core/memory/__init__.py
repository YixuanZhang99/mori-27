"""Scoped memory extension (M5)."""
from core.memory.store import MemoryError, ScopedMemory
from core.memory.types import MemoryEntry, ScopeContext

__all__ = ["MemoryEntry", "MemoryError", "ScopeContext", "ScopedMemory"]
