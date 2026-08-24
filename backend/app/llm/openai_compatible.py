"""OpenAI-compatible chat completions client.

Works against any ``/v1/chat/completions`` endpoint.  Verified shapes: Groq,
OpenAI, DeepSeek, Together, OpenRouter, vLLM's OpenAI server, Ollama.

Retry policy: exponential backoff with jitter on 429 and 5xx only.  A 400 means
the request itself is wrong -- retrying it just burns quota and delays the
error, so those raise immediately.  ``Retry-After`` is honoured when the server
sends it, which is what keeps a rate-limited batch from thrashing.
"""

from __future__ import annotations

import logging
import random
import time

import httpx

from app.config import settings
from app.llm.base import LLMError, LLMProvider, LLMResult

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class OpenAICompatibleProvider(LLMProvider):
    name = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.api_key = api_key or settings.llm_api_key
        self.model = model or settings.llm_model
        if not self.api_key:
            raise LLMError("LLM_API_KEY is not set.")

    def complete(
        self,
        *,
        system: str,
        user: str,
        json_mode: bool = False,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResult:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": (
                settings.llm_temperature if temperature is None else temperature
            ),
            "max_tokens": max_tokens or settings.llm_max_output_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        started = time.perf_counter()
        last_error: Exception | None = None

        with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
            for attempt in range(1, settings.llm_max_retries + 1):
                try:
                    response = client.post(
                        f"{self.base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                except httpx.RequestError as exc:
                    last_error = exc
                    self._sleep(attempt, None)
                    continue

                if response.status_code in RETRYABLE_STATUS:
                    last_error = LLMError(
                        f"{response.status_code}: {response.text[:200]}"
                    )
                    if attempt == settings.llm_max_retries:
                        break
                    self._sleep(attempt, response.headers.get("Retry-After"))
                    continue

                if response.status_code >= 400:
                    # Non-retryable: bad key, bad model name, malformed request.
                    raise LLMError(
                        f"LLM request rejected ({response.status_code}): "
                        f"{response.text[:300]}"
                    )

                body = response.json()
                try:
                    text = body["choices"][0]["message"]["content"] or ""
                except (KeyError, IndexError, TypeError) as exc:
                    raise LLMError(f"Unexpected response shape: {body}") from exc

                usage = body.get("usage") or {}
                return LLMResult(
                    text=text,
                    model=body.get("model", self.model),
                    provider=self.name,
                    prompt_tokens=int(usage.get("prompt_tokens") or 0),
                    completion_tokens=int(usage.get("completion_tokens") or 0),
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    raw=body,
                )

        raise LLMError(
            f"LLM call failed after {settings.llm_max_retries} attempts: {last_error}"
        )

    @staticmethod
    def _sleep(attempt: int, retry_after: str | None) -> None:
        if retry_after:
            try:
                time.sleep(min(float(retry_after), 30.0))
                return
            except ValueError:
                pass
        delay = min(2.0 ** attempt, 20.0) * (0.7 + random.random() * 0.6)
        logger.info("Retrying LLM call in %.1fs (attempt %d)", delay, attempt)
        time.sleep(delay)
