from __future__ import annotations

import os


def _enabled(name: str) -> bool:
    value = os.getenv(name, "false")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def catalog_agent_enabled() -> bool:
    """Whether CatalogAgent may own catalog responses (default: disabled)."""
    return _enabled("AGENTFLOW_CATALOG_ENABLED")


def policy_rag_agent_enabled() -> bool:
    """Whether PolicyRAGAgent may own FAQ responses (default: disabled)."""
    return _enabled("AGENTFLOW_POLICY_RAG_ENABLED")


def tryon_agent_enabled() -> bool:
    """Whether TryOnAgent may own try-on responses (default: disabled)."""
    return _enabled("AGENTFLOW_TRYON_ENABLED")


def product_advisor_agent_enabled() -> bool:
    """Whether ProductAdvisorAgent may own product consultation responses."""
    return _enabled("AGENTFLOW_PRODUCT_ADVISOR_ENABLED")


def execution_mode() -> str:
    """Return the runtime ownership mode: shadow or takeover."""
    value = os.getenv("AGENTFLOW_EXECUTION_MODE", "shadow").strip().lower()
    return value if value in {"shadow", "takeover"} else "shadow"
