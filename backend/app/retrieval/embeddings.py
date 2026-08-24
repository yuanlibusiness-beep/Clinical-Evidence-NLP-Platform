"""Embedding providers.

The platform must index and retrieve with no network access and no model
download -- otherwise CI cannot test retrieval and a reviewer cannot run the
project.  So the default provider is a **deterministic hashing embedder**: a
signed feature-hashing projection of word unigrams and bigrams with sub-linear
term weighting and L2 normalisation.  It is, in effect, TF-IDF-shaped semantics
in a fixed-width dense vector.

That is an honest trade-off, and worth stating plainly:

* it captures lexical and light morphological similarity, not paraphrase;
* it is stable across processes (BLAKE2b, not Python's randomised ``hash``);
* it costs microseconds and zero dollars.

Swapping in a real embedding model is a one-line config change
(``EMBEDDING_PROVIDER=openai_compatible``) because everything downstream depends
only on the ``Embedder`` interface.  The hybrid retriever is designed so that
BM25 carries lexical precision while the vector side carries recall, which keeps
retrieval quality respectable even on the offline path.
"""

from __future__ import annotations

import abc
import functools
import hashlib
import logging
import math
import re
from collections.abc import Sequence

import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)

_TOKEN = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class Embedder(abc.ABC):
    name: str
    dim: int

    @abc.abstractmethod
    def embed(self, texts: Sequence[str]) -> np.ndarray:
        """Return an ``(n, dim)`` float32 array of L2-normalised vectors."""

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]


class HashingEmbedder(Embedder):
    name = "hashing"

    def __init__(self, dim: int | None = None) -> None:
        self.dim = dim or settings.embedding_dim

    @staticmethod
    @functools.lru_cache(maxsize=200_000)
    def _slot(feature: str, dim: int) -> tuple:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        # Low bit picks the sign so unrelated features cancel instead of
        # accumulating, which is what keeps collisions from inflating scores.
        return value % dim, 1.0 if (value >> 63) & 1 else -1.0

    def _embed_single(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dim, dtype=np.float32)
        tokens = tokenize(text)
        if not tokens:
            return vector

        counts: dict = {}
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
        for left, right in zip(tokens, tokens[1:], strict=False):
            bigram = f"{left}_{right}"
            counts[bigram] = counts.get(bigram, 0) + 0.6  # bigrams weigh less

        for feature, count in counts.items():
            index, sign = self._slot(feature, self.dim)
            vector[index] += sign * (1.0 + math.log(count))

        norm = float(np.linalg.norm(vector))
        return vector / norm if norm > 0 else vector

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.vstack([self._embed_single(text) for text in texts]).astype(np.float32)


class OpenAICompatibleEmbedder(Embedder):
    """Any ``/v1/embeddings`` endpoint: OpenAI, Together, vLLM, TEI, Ollama."""

    name = "openai_compatible"

    def __init__(self) -> None:
        self.dim = settings.embedding_dim
        self.model = settings.embedding_model
        self.base_url = settings.llm_base_url.rstrip("/")
        self.api_key = settings.llm_api_key

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        import httpx

        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)

        vectors: list[np.ndarray] = []
        batch_size = 64
        with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
            for start in range(0, len(texts), batch_size):
                batch = list(texts[start : start + batch_size])
                response = client.post(
                    f"{self.base_url}/embeddings",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": self.model, "input": batch},
                )
                response.raise_for_status()
                payload = response.json()
                for item in sorted(payload["data"], key=lambda d: d.get("index", 0)):
                    vectors.append(np.asarray(item["embedding"], dtype=np.float32))

        matrix = np.vstack(vectors).astype(np.float32)
        if matrix.shape[1] != self.dim:
            raise ValueError(
                f"Embedding model returned dim {matrix.shape[1]} but EMBEDDING_DIM "
                f"is {self.dim}. Update the setting and re-index."
            )
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return matrix / norms


@functools.lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    if settings.embedding_provider == "openai_compatible" and settings.llm_api_key:
        logger.info("Embeddings: openai_compatible (%s)", settings.embedding_model)
        return OpenAICompatibleEmbedder()
    if settings.embedding_provider == "openai_compatible":
        logger.warning(
            "EMBEDDING_PROVIDER=openai_compatible but no API key set; "
            "falling back to the local hashing embedder."
        )
    return HashingEmbedder()


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denominator) if denominator else 0.0
