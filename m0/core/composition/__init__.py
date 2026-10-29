"""Typed component contracts and explicit runtime assembly."""

from core.composition.contracts import (AssemblyConfig, BuildContext, ComponentSpec,
                                       Decision, OperatorRequest, Proposal)
from core.composition.registry import Registry

__all__ = ["AssemblyConfig", "BuildContext", "ComponentSpec", "Decision",
           "OperatorRequest", "Proposal", "Registry"]
