"""Provider selection.

``LLM_PROVIDER=auto`` (the default) resolves to the API provider when a key is
present and to ``None`` otherwise.  ``None`` is not an error state: the
extraction pipeline treats it as "use the rule-based engine", which is what lets
the repository be cloned and run end to end with no credentials.
"""

from __future__ import annotations

import logging

from app.config import settings
from app.llm.base import LLMProvider
from app.llm.openai_compatible import OpenAICompatibleProvider

logger = logging.getLogger(__name__)

_provider: LLMProvider | None = None
_resolved = False


def get_llm() -> LLMProvider | None:
    """Return the configured provider, or ``None`` for offline operation."""
    global _provider, _resolved
    if _resolved:
        return _provider

    _resolved = True
    if settings.resolved_llm_provider == "openai_compatible":
        try:
            _provider = OpenAICompatibleProvider()
            logger.info(
                "LLM provider: %s (%s)", settings.llm_base_url, settings.llm_model
            )
        except Exception as exc:
            logger.warning(
                "LLM provider unavailable (%s); running with the rule-based engine.",
                exc,
            )
            _provider = None
    else:
        logger.info("No LLM key configured; running with the rule-based engine.")
        _provider = None

    return _provider


def reset_llm_cache() -> None:
    """Test hook: forget the resolved provider."""
    global _provider, _resolved
    _provider = None
    _resolved = False
