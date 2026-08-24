"""LLM provider interface.

Kept deliberately small -- one method, one return type.  Everything that varies
between vendors (auth header, JSON mode flag, usage accounting, retry policy)
is the provider's problem; everything above this line only ever sees
``LLMResult``.  That is what makes ``LLM_BASE_URL`` swappable between Groq,
DeepSeek, OpenAI, Together and a self-hosted vLLM without touching the
extraction code.
"""

from __future__ import annotations

import abc
import json
import re
from dataclasses import dataclass, field
from typing import Any


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResult:
    text: str
    model: str
    provider: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


class LLMProvider(abc.ABC):
    name: str
    model: str

    @abc.abstractmethod
    def complete(
        self,
        *,
        system: str,
        user: str,
        json_mode: bool = False,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResult:
        ...


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_json_object(text: str) -> dict[str, Any]:
    """Recover a JSON object from a model response.

    Even in JSON mode, models prepend prose, wrap output in code fences, or
    append a trailing comment.  Rather than fail the whole extraction on
    punctuation, we peel those off in order and only then give up.
    """
    if not text or not text.strip():
        raise LLMError("Model returned an empty response.")

    candidates: list[str] = []
    stripped = text.strip()
    candidates.append(stripped)

    fenced = _FENCE.search(stripped)
    if fenced:
        candidates.append(fenced.group(1).strip())

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end > start:
        candidates.append(stripped[start : end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
            return parsed[0]

    raise LLMError(f"Could not parse JSON from model output: {text[:280]!r}")
