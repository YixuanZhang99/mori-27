"""Per-invocation provider metering for every configured execution component."""
from __future__ import annotations

from core.llm import ProviderBudgetExhausted, UsageError, reset_usage, take_usage


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
        durable = self.__dict__.get("_governed_store", self.__dict__.get("durable_store"))
        binding = self.__dict__.get("invocation_binding")
        if binding is not None:
            self.current_invocation_binding = {**binding, "ordinal": self.invocation_ordinal}
            factory = self.__dict__.get("external_context_factory")
            if factory is not None:
                self.current_external_context = factory(self.invocation_ordinal, args, kwargs)
                self.current_invocation_binding.update(schema_version=2,
                    external_context=self.current_external_context.to_dict())
            self.invocation_ordinal += 1
        try:
            if durable is not None:
                return durable.provider_call(self, self._invoke, args, kwargs)
            return self._invoke(*args, **kwargs)
        finally:
            self.__dict__.pop("current_invocation_binding", None)
            self.__dict__.pop("current_external_context", None)

    def _invoke(self, *args, **kwargs):
        if self._unresolved_usage:
            raise UsageError("provider has unresolved invocation usage")
        guard = self.__dict__.get("admission_guard")
        if guard is not None:
            self.last_usage = {"total_tokens": 0}
            try:
                guard()
            except ProviderBudgetExhausted:
                recover = self.__dict__.get("external_recover")
                if recover is not None:
                    context = self.current_external_context
                    outcome = recover(context, context.argument_sha256)
                    if outcome.outcome != "known_refused" or outcome.usage != {"total_tokens": 0}:
                        raise UsageError("pre-dispatch refusal lacks independent zero-cost evidence")
                raise
        self.last_usage = None
        reset_usage(self._provider)
        try:
            external = self.__dict__.get("external_invoke")
            if external is not None:
                return external(self.current_external_context, args, kwargs)
            return self._provider(*args, **kwargs)
        finally:
            try:
                used = take_usage(self._provider)
            except UsageError:
                self._unresolved_usage = True
                raise
            self._usage_total += used
            self.last_usage = {"total_tokens": used}
            measurement = self.__dict__.get("governance_measurement")
            if measurement is not None:
                measurement(used)
