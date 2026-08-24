"""Okapi BM25 over a single document's chunks.

Written out rather than pulled from a library for two reasons: the corpus here
is one paper (tens to low hundreds of chunks, so an in-memory index is free),
and the IDF variant matters.  We use the Lucene/"BM25+" style non-negative IDF

    idf(q) = ln(1 + (N - df + 0.5) / (df + 0.5))

instead of the textbook form, which goes negative for terms appearing in more
than half the chunks.  With a corpus this small, negative IDF would actively
punish chunks for containing the paper's own topic words -- precisely the terms
a clinical query is made of.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from app.retrieval.embeddings import tokenize

K1 = 1.5
B = 0.75

# Function words plus the boilerplate of academic prose. Removing them keeps
# "effect of aspirin on mortality" from matching on "of" and "on".
STOPWORDS = frozenset(
    ["a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "for", "from", "has", "have", "had", "he", "her", "his", "if", "in", "into", "is", "it", "its", "of", "on", "or", "our", "that", "the", "their", "then", "there", "these", "they", "this", "to", "was", "were", "will", "with", "we", "you", "your", "which", "who", "whom", "whose", "while", "when", "where", "what", "how", "why", "not", "no", "nor", "so", "such", "than", "too", "very", "can", "could", "may", "might", "must", "shall", "should", "would", "do", "does", "did", "done", "being", "study", "studies", "paper", "article", "research", "using", "used", "use", "results", "result", "conclusion", "conclusions", "objective", "objectives", "background", "methods", "method", "aim", "aims", "purpose"]
)


@dataclass
class Bm25Index:
    doc_ids: list[str]
    doc_lengths: list[int]
    average_length: float
    term_frequencies: list[Counter]
    document_frequency: dict[str, int]

    @property
    def size(self) -> int:
        return len(self.doc_ids)


def _terms(text: str) -> list[str]:
    return [token for token in tokenize(text) if token not in STOPWORDS and len(token) > 1]


def build_index(doc_ids: Sequence[str], texts: Sequence[str]) -> Bm25Index:
    if len(doc_ids) != len(texts):
        raise ValueError("doc_ids and texts must be the same length")

    term_frequencies: list[Counter] = []
    lengths: list[int] = []
    document_frequency: dict[str, int] = {}

    for text in texts:
        terms = _terms(text)
        counter = Counter(terms)
        term_frequencies.append(counter)
        lengths.append(len(terms))
        for term in counter:
            document_frequency[term] = document_frequency.get(term, 0) + 1

    average = (sum(lengths) / len(lengths)) if lengths else 0.0
    return Bm25Index(
        doc_ids=list(doc_ids),
        doc_lengths=lengths,
        average_length=average or 1.0,
        term_frequencies=term_frequencies,
        document_frequency=document_frequency,
    )


def score(index: Bm25Index, query: str, top_k: int = 30) -> list[tuple[str, float]]:
    if index.size == 0:
        return []

    query_terms = _terms(query)
    if not query_terms:
        return []

    total = index.size
    idf = {
        term: math.log(
            1.0
            + (total - index.document_frequency.get(term, 0) + 0.5)
            / (index.document_frequency.get(term, 0) + 0.5)
        )
        for term in set(query_terms)
    }

    scored: list[tuple[str, float]] = []
    for position, doc_id in enumerate(index.doc_ids):
        frequencies = index.term_frequencies[position]
        length = index.doc_lengths[position] or 1
        norm = K1 * (1 - B + B * length / index.average_length)

        total_score = 0.0
        for term in query_terms:
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue
            total_score += idf[term] * (frequency * (K1 + 1)) / (frequency + norm)

        if total_score > 0:
            scored.append((doc_id, total_score))

    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:top_k]
