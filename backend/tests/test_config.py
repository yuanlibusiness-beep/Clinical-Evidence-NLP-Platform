"""Regression: the README tells users to ``cp .env.example .env`` and boot.

pydantic-settings decodes ``list[str]`` env values as JSON by default, so a plain
``CORS_ORIGINS=http://localhost:3000`` (as written in .env.example and
docker-compose.yml) used to crash the API on startup.
"""

from __future__ import annotations

import pytest

from app.config import Settings


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://localhost:3000", ["http://localhost:3000"]),
        ('["http://localhost:3000"]', ["http://localhost:3000"]),
        ("http://a.example, http://b.example", ["http://a.example", "http://b.example"]),
    ],
)
def test_cors_origins_accepts_plain_csv_and_json(monkeypatch, raw, expected):
    monkeypatch.setenv("CORS_ORIGINS", raw)
    assert Settings(_env_file=None).cors_origins == expected


def test_env_example_boots(tmp_path):
    from pathlib import Path

    example = Path(__file__).resolve().parents[2] / ".env.example"
    settings = Settings(_env_file=str(example))
    assert settings.cors_origins == ["http://localhost:3000"]
