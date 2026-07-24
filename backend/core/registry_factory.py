"""Build an effective expert registry by applying persisted enable overrides.

The overrides let operators disable (or re-enable) experts at runtime. The
resulting registry is used by both the Manager (planning) and the executor
(execution), so a disabled expert is rejected during planning *and* execution.
"""

from __future__ import annotations

from dataclasses import replace

from backend.core.agent_registry import DEFAULT_EXPERTS, AgentRegistry
from backend.core.store import Store


def build_registry(store: Store) -> AgentRegistry:
    """Clone the default expert pool and apply persisted ``agent_overrides``."""

    overrides = store.get_overrides()
    definitions = [
        replace(definition, enabled=overrides[definition.id.value])
        if definition.id.value in overrides
        else definition
        for definition in DEFAULT_EXPERTS
    ]
    return AgentRegistry(definitions)
