"""Test configuration.

The environment is set **before** any application module is imported, because
``app.config.settings`` is a module-level singleton: importing it first would
bind the developer's real ``.env`` and the tests would run against whatever
database happens to be configured.  This ordering is load-bearing -- do not move
the imports above ``os.environ``.

Every test gets a fresh file-backed SQLite database in a temp directory, which
keeps the suite hermetic and lets it run with no services at all.
"""

from __future__ import annotations

import os
import tempfile

TEST_DB_DIR = tempfile.mkdtemp(prefix="cenp-tests-")

os.environ.update(
    {
        "ENVIRONMENT": "ci",
        "DEBUG": "false",
        "DATABASE_URL": f"sqlite:///{os.path.join(TEST_DB_DIR, 'test.db')}",
        # >= 32 bytes: shorter HMAC keys make PyJWT warn, and a suite that warns
        # on every request trains you to ignore warnings.
        "JWT_SECRET": "test-secret-not-for-production-0123456789abcdef",
        "LLM_PROVIDER": "offline",
        "LLM_API_KEY": "",
        "EMBEDDING_PROVIDER": "hashing",
        "EXTERNAL_SEARCH_ENABLED": "false",
        "CELERY_TASK_ALWAYS_EAGER": "true",
        "CALIBRATION_PATH": os.path.join(TEST_DB_DIR, "calibration.json"),
        "OTEL_ENABLED": "false",
    }
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine, init_db  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _database():
    init_db()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture()
def auth(client):
    """Register a unique user and return ready-to-use auth headers."""
    import uuid

    email = f"tester-{uuid.uuid4().hex[:10]}@example.org"
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery", "full_name": "Tester"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return {
        "headers": {"Authorization": f"Bearer {body['access_token']}"},
        "user": body["user"],
        "email": email,
    }


SAMPLE_PAPER = """\
Effect of nightly melatonin on sleep onset latency in adults with delayed sleep phase: \
a randomised controlled trial

Background
Delayed sleep phase disorder affects a substantial minority of young adults and \
current behavioural treatment is slow to take effect.

Methods
We conducted a single-centre, double-blind, randomised controlled trial at one sleep \
clinic in Leeds. A total of 248 patients with delayed sleep phase disorder were randomly \
assigned (1:1) to receive melatonin 2 mg nightly or matching placebo. Participants were \
eligible if they were aged 18 to 35 years. Exclusion criteria included shift work and \
current use of hypnotics. The primary outcome was change in sleep onset latency at 8 \
weeks. The mean age was 24.6 years (SD 4.2) and 55.0 % were female. The trial is \
registered with ClinicalTrials.gov, NCT01234567.

Results
Over a median follow-up of 8.1 weeks, sleep onset latency fell by 34 minutes in the \
melatonin group and by 11 minutes in the placebo group (mean difference -23 minutes, \
95% CI -31 to -15, p < 0.001). Adverse events were reported in 4.0 % versus 3.2 % of \
participants (p = 0.71).

Discussion
Our study has several limitations: the follow-up was short and the sample was drawn \
from a single clinic, which limits generalisability.

Conclusion
In conclusion, nightly melatonin reduced sleep onset latency at 8 weeks in adults with \
delayed sleep phase disorder.
"""


@pytest.fixture()
def sample_text() -> str:
    """A synthetic paper. Invented study, invented numbers -- fixture only."""
    return SAMPLE_PAPER


@pytest.fixture()
def ingested_document(client, auth, sample_text):
    response = client.post(
        "/api/v1/documents/text",
        json={"title": "Melatonin RCT (synthetic fixture)", "text": sample_text},
        headers=auth["headers"],
    )
    assert response.status_code == 201, response.text
    return response.json()
