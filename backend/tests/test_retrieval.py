"""Retrieval: BM25, embeddings, fusion, reranking, and the hybrid stack."""

from __future__ import annotations

import numpy as np

from app.retrieval import bm25
from app.retrieval.embeddings import HashingEmbedder, cosine
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.rerank import FeatureReranker, RerankCandidate


class TestBm25:
    corpus = {
        "a": "Patients were randomly assigned to receive melatonin 2 mg nightly.",
        "b": "Sleep onset latency fell by 34 minutes in the melatonin group.",
        "c": "The study was conducted at a single sleep clinic in Leeds.",
    }

    def _index(self):
        return bm25.build_index(list(self.corpus), list(self.corpus.values()))

    def test_ranks_the_relevant_document_first(self):
        results = bm25.score(self._index(), "sleep onset latency minutes")
        assert results[0][0] == "b"

    def test_idf_is_never_negative(self):
        """A term in every chunk must not push scores below zero."""
        index = bm25.build_index(["x", "y"], ["melatonin trial", "melatonin cohort"])
        for _doc_id, score in bm25.score(index, "melatonin"):
            assert score >= 0

    def test_stopword_only_query_returns_nothing(self):
        assert bm25.score(self._index(), "the of and was") == []

    def test_empty_index_is_safe(self):
        assert bm25.score(bm25.build_index([], []), "anything") == []


class TestHashingEmbedder:
    def test_vectors_are_unit_length(self):
        vectors = HashingEmbedder(dim=128).embed(["one text", "another text"])
        assert vectors.shape == (2, 128)
        assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)

    def test_deterministic_across_instances(self):
        """Stable hashing matters: embeddings persist across process restarts."""
        first = HashingEmbedder(dim=128).embed_one("randomised controlled trial")
        second = HashingEmbedder(dim=128).embed_one("randomised controlled trial")
        assert np.allclose(first, second)

    def test_related_text_scores_higher_than_unrelated(self):
        embedder = HashingEmbedder(dim=512)
        query = embedder.embed_one("sleep onset latency in adults")
        near = embedder.embed_one("sleep onset latency fell by 34 minutes in adults")
        far = embedder.embed_one("carbon fibre propeller layup and finite element analysis")
        assert cosine(query, near) > cosine(query, far)

    def test_empty_text_gives_a_zero_vector(self):
        assert np.count_nonzero(HashingEmbedder(dim=64).embed_one("")) == 0


class TestFusion:
    def test_a_document_ranked_by_both_lists_wins(self):
        fused = reciprocal_rank_fusion(
            {
                "bm25": [("a", 9.0), ("b", 8.0), ("c", 1.0)],
                "vector": [("b", 0.9), ("c", 0.8), ("a", 0.1)],
            }
        )
        assert fused[0].doc_id == "b"

    def test_records_ranks_and_raw_scores(self):
        fused = reciprocal_rank_fusion({"bm25": [("a", 5.0)]})
        assert fused[0].ranks["bm25"] == 1
        assert fused[0].raw_scores["bm25"] == 5.0

    def test_scale_of_raw_scores_is_irrelevant(self):
        """The point of RRF: a list with huge scores cannot dominate."""
        small = reciprocal_rank_fusion(
            {"a": [("x", 0.001), ("y", 0.0005)], "b": [("y", 1e6), ("x", 1.0)]}
        )
        big = reciprocal_rank_fusion(
            {"a": [("x", 1000.0), ("y", 500.0)], "b": [("y", 1e12), ("x", 1000.0)]}
        )
        assert [item.doc_id for item in small] == [item.doc_id for item in big]


class TestFeatureReranker:
    def test_prefers_the_chunk_that_covers_the_query(self):
        candidates = [
            RerankCandidate("a", "The clinic is located in central Leeds.", "methods", 0.01),
            RerankCandidate(
                "b",
                "The mean age was 24.6 years and 55.0 % of participants were female.",
                "methods",
                0.01,
            ),
        ]
        ranked = FeatureReranker().rerank("mean age of participants years", candidates, 2)
        assert ranked[0].chunk_id == "b"

    def test_explanation_is_returned(self):
        ranked = FeatureReranker().rerank(
            "sample size", [RerankCandidate("a", "A total of 248 patients were randomised.", "methods")], 1
        )
        assert "coverage" in ranked[0].explain

    def test_empty_candidates(self):
        assert FeatureReranker().rerank("anything", [], 5) == []


class TestHybridRetriever:
    def test_finds_the_chunk_holding_the_answer(self, client, auth, ingested_document, db):
        retriever = HybridRetriever(db, ingested_document["id"])
        results = retriever.retrieve("how many patients were randomised", top_k=5)
        assert results
        assert any("248" in hit.text for hit in results)

    def test_results_are_ranked_from_one(self, db, ingested_document):
        results = HybridRetriever(db, ingested_document["id"]).retrieve("melatonin dose", top_k=3)
        assert [hit.rank for hit in results] == list(range(1, len(results) + 1))

    def test_section_filter_is_respected(self, db, ingested_document):
        results = HybridRetriever(db, ingested_document["id"]).retrieve(
            "primary outcome", top_k=5, section_filter=["results"]
        )
        assert all(hit.section_name == "results" for hit in results)

    def test_unknown_document_returns_nothing(self, db):
        assert HybridRetriever(db, "does-not-exist").retrieve("anything") == []
