"""Per-invocation provider metering for every configured execution component."""
from __future__ import annotations

from core.llm import UsageError, reset_usage, take_usage


class MeteredProvider:
    """Preserve each known charge even when a hook makes multiple calls.

    ``last_usage`` keeps the legacy per-call consumption contract. ``usage_total``
    is monotonic and cannot be consumed, allowing the driver to meter an entire
    policy/skill hook independently of how often it invokes the provider.
    """
    def __init__(self, provider):
        if not callable(provider):
            raise ValueError("configured provider must be callable")
        self._provider = provider
        self._usage_total = 0
        self._unresolved_usage = False
        self.last_usage = {"total_tokens": 0}

    @property
    def raw_provider(self):
        return self._provider

    @property
    def usage_total(self):
        if self._unresolved_usage:
            raise UsageError("provider has unresolved invocation usage")
        return self._usage_total

    @property
    def known_usage_total(self):
        """Diagnostic known subtotal, never a settlement total after unknown usage."""
        return self._usage_total

    def __getattr__(self, name):
        provider = object.__getattribute__(self, "_provider")
        return getattr(provider, name)

    def __call__(self, *args, **kwargs):
        durable = self.__dict__.get("durable_store")
        if durable is not None:
            return durable.provider_call(self, self._invoke, args, kwargs)
        return self._invoke(*args, **kwargs)

    def _invoke(self, *args, **kwargs):
        if self._unresolved_usage:
            raise UsageError("provider has unresolved invocation usage")
        self.last_usage = None
        reset_usage(self._provider)
        try:
            return self._provider(*args, **kwargs)
        finally:
            try:
                used = take_usage(self._provider)
            except UsageError:
                self._unresolved_usage = True
                raise
            self._usage_total += used
            self.last_usage = {"total_tokens": used}
