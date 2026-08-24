"""API-level tests: auth, ownership, ingestion, extraction, evaluation.

The ownership tests matter more than they look.  In a multi-user document
system, "user A can read user B's paper" is the failure that ends the project,
and it is exactly the kind of bug that unit tests on the pipeline never catch.
"""

from __future__ import annotations

import io

import pytest


class TestHealth:
    def test_health_reports_the_active_configuration(self, client):
        body = client.get("/api/v1/health").json()
        assert body["status"] == "ok"
        assert body["database"] == "sqlite"
        assert body["llm_provider"] == "offline"

    def test_public_config_exposes_no_secrets(self, client):
        body = client.get("/api/v1/config").json()
        serialised = str(body).lower()
        assert "secret" not in serialised
        assert "api_key" not in serialised
        assert "abstain_threshold" in body

    def test_root_points_at_the_docs(self, client):
        assert client.get("/").json()["docs"] == "/docs"


class TestAuth:
    def test_register_then_use_the_token(self, client, auth):
        response = client.get("/api/v1/auth/me", headers=auth["headers"])
        assert response.status_code == 200
        assert response.json()["email"] == auth["email"]

    def test_duplicate_email_is_rejected(self, client, auth):
        response = client.post(
            "/api/v1/auth/register",
            json={"email": auth["email"], "password": "another-long-password"},
        )
        assert response.status_code == 409

    def test_login_with_the_wrong_password_fails(self, client, auth):
        response = client.post(
            "/api/v1/auth/login",
            json={"email": auth["email"], "password": "definitely-wrong-password"},
        )
        assert response.status_code == 401

    def test_unknown_email_gives_the_same_error(self, client):
        """No account enumeration: identical status and detail either way."""
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "nobody-here@example.org", "password": "whatever-long"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Incorrect email or password."

    def test_short_password_is_rejected(self, client):
        response = client.post(
            "/api/v1/auth/register", json={"email": "x@example.org", "password": "short"}
        )
        assert response.status_code == 422

    def test_protected_route_needs_a_token(self, client):
        assert client.get("/api/v1/documents").status_code == 401

    def test_garbage_token_is_rejected(self, client):
        response = client.get(
            "/api/v1/documents", headers={"Authorization": "Bearer not-a-jwt"}
        )
        assert response.status_code == 401


class TestIngestion:
    def test_text_ingestion_builds_an_index(self, ingested_document):
        assert ingested_document["status"] == "ready"
        assert ingested_document["n_chunks"] > 0
        assert {s["name"] for s in ingested_document["sections"]} >= {"methods", "results"}

    def test_too_short_text_is_rejected(self, client, auth):
        response = client.post(
            "/api/v1/documents/text",
            json={"title": "Tiny", "text": "Too short."},
            headers=auth["headers"],
        )
        assert response.status_code == 422

    def test_non_pdf_upload_is_refused(self, client, auth):
        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")},
            headers=auth["headers"],
        )
        assert response.status_code == 415

    def test_corrupt_pdf_gives_a_useful_error(self, client, auth):
        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("broken.pdf", io.BytesIO(b"not really a pdf"), "application/pdf")},
            headers=auth["headers"],
        )
        assert response.status_code == 422
        assert "PDF" in response.json()["detail"]

    def test_real_pdf_round_trip(self, client, auth, sample_text):
        """Exercises the actual PyMuPDF path, not just pasted text."""
        pymupdf = pytest.importorskip("pymupdf")

        document = pymupdf.open()
        for block in [sample_text[i : i + 1400] for i in range(0, len(sample_text), 1400)]:
            page = document.new_page()
            page.insert_textbox(
                pymupdf.Rect(50, 50, 545, 780), block, fontsize=9, fontname="helv"
            )
        data = document.tobytes()
        document.close()

        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("synthetic.pdf", io.BytesIO(data), "application/pdf")},
            headers=auth["headers"],
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["status"] == "ready"
        assert body["page_count"] >= 1
        assert body["n_chunks"] > 0

    def test_index_health_reports_complete(self, client, auth, ingested_document):
        body = client.get(
            f"/api/v1/documents/{ingested_document['id']}/index-health",
            headers=auth["headers"],
        ).json()
        assert body["complete"] is True
        assert body["chunks"] == body["embedded"]


class TestOwnership:
    @pytest.fixture()
    def other_user(self, client):
        import uuid

        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": f"other-{uuid.uuid4().hex[:8]}@example.org",
                "password": "another-good-password",
            },
        )
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def test_another_user_cannot_read_the_document(
        self, client, ingested_document, other_user
    ):
        response = client.get(
            f"/api/v1/documents/{ingested_document['id']}", headers=other_user
        )
        assert response.status_code == 404  # not 403 -- do not confirm it exists

    def test_another_user_cannot_extract_from_it(
        self, client, ingested_document, other_user
    ):
        response = client.post(
            f"/api/v1/documents/{ingested_document['id']}/extract",
            json={},
            headers=other_user,
        )
        assert response.status_code == 404

    def test_another_user_cannot_delete_it(self, client, ingested_document, other_user):
        assert (
            client.delete(
                f"/api/v1/documents/{ingested_document['id']}", headers=other_user
            ).status_code
            == 404
        )


class TestRetrievalEndpoint:
    def test_scores_are_exposed_for_debugging(self, client, auth, ingested_document):
        response = client.post(
            f"/api/v1/documents/{ingested_document['id']}/retrieve",
            json={"query": "how many patients were randomised", "top_k": 5},
            headers=auth["headers"],
        )
        assert response.status_code == 200
        body = response.json()
        assert body["results"]
        first = body["results"][0]
        assert {"bm25_score", "vector_score", "fused_score", "rerank_score"} <= set(first)


class TestExtraction:
    def test_end_to_end_extraction_is_grounded(self, client, auth, ingested_document):
        response = client.post(
            f"/api/v1/documents/{ingested_document['id']}/extract",
            json={"force": True},
            headers=auth["headers"],
        )
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["status"] == "completed"
        assert body["provider"] == "offline"

        # Core fields the rule engine should reach on this fixture.
        assert body["payload"]["design"]["design"]["value"] == "randomised controlled trial"
        assert "248" in (body["payload"]["population"]["sample_size"]["value"] or "")
        assert body["payload"]["design"]["registration_id"]["value"] == "NCT01234567"

        # Every answered field carries a span, and every span was verified.
        answered = set(body["confidence"])
        spanned = {span["field_path"] for span in body["spans"]}
        assert answered == spanned
        assert body["grounded_field_ratio"] == 1.0
        assert all(span["match_score"] >= 0.82 for span in body["spans"])

    def test_every_quote_appears_in_the_source(self, client, auth, ingested_document):
        document = client.get(
            f"/api/v1/documents/{ingested_document['id']}", headers=auth["headers"]
        ).json()
        extraction = client.post(
            f"/api/v1/documents/{ingested_document['id']}/extract",
            json={"force": True},
            headers=auth["headers"],
        ).json()

        raw = document["raw_text"]
        for span in extraction["spans"]:
            assert raw[span["char_start"] : span["char_end"]] == span["quote"]

    def test_abstentions_are_reported_with_a_reason(self, client, auth, ingested_document):
        body = client.post(
            f"/api/v1/documents/{ingested_document['id']}/extract",
            json={"force": True},
            headers=auth["headers"],
        ).json()
        assert body["abstentions"]
        assert all(isinstance(reason, str) for reason in body["abstentions"].values())

    def test_second_call_reuses_the_stored_extraction(
        self, client, auth, ingested_document
    ):
        first = client.post(
            f"/api/v1/documents/{ingested_document['id']}/extract",
            json={"force": True},
            headers=auth["headers"],
        ).json()
        second = client.post(
            f"/api/v1/documents/{ingested_document['id']}/extract",
            json={"force": False},
            headers=auth["headers"],
        ).json()
        assert first["id"] == second["id"]

    def test_async_extraction_runs_eagerly_without_a_broker(
        self, client, auth, ingested_document
    ):
        response = client.post(
            f"/api/v1/documents/{ingested_document['id']}/extract-async",
            headers=auth["headers"],
        )
        assert response.status_code == 202
        job_id = response.json()["id"]
        job = client.get(f"/api/v1/jobs/{job_id}", headers=auth["headers"]).json()
        assert job["status"] in ("completed", "running", "queued")


class TestEvaluationEndpoint:
    def test_dataset_declares_that_it_is_synthetic(self, client, auth):
        body = client.get("/api/v1/eval/datasets/gold_v1", headers=auth["headers"]).json()
        assert body["synthetic"] is True
        assert body["n_cases"] >= 4

    def test_run_reports_the_four_metric_families(self, client, auth):
        response = client.post(
            "/api/v1/eval/run?rule_engine=true",
            json={"name": "pytest run", "dataset": "gold_v1", "limit": 2},
            headers=auth["headers"],
        )
        assert response.status_code == 200, response.text
        metrics = response.json()["metrics"]
        assert {"extraction", "retrieval", "outcomes", "calibration"} <= set(metrics)
        assert metrics["extraction"]["hallucination_rate"] == 0.0
        assert metrics["runtime"]["dataset_is_synthetic"] is True

    def test_missing_dataset_is_a_404(self, client, auth):
        response = client.post(
            "/api/v1/eval/run",
            json={"name": "x", "dataset": "no_such_dataset"},
            headers=auth["headers"],
        )
        assert response.status_code == 404
