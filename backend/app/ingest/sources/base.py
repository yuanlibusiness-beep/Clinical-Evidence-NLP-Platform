"""Contract shared by every literature source.

Adding a database means implementing ``search`` and registering the class -- no
call site changes.  Every source is responsible for mapping its own payload onto
``LiteratureHit`` and for failing softly: a source that is down must degrade the
result set, never the request.
"""

from __future__ import annotations

import abc
import logging

import httpx

from app.config import settings
from app.schemas import LiteratureHit

logger = logging.getLogger(__name__)


class SourceError(RuntimeError):
    pass


class LiteratureSource(abc.ABC):
    name: str = "base"
    #: Shown in the UI so a reader knows where a record came from.
    display_name: str = "Base"
    homepage: str = ""

    @abc.abstractmethod
    def search(self, query: str, limit: int) -> list[LiteratureHit]:
        ...

    # -------------------------------------------------------------- helpers
    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=settings.http_timeout_seconds,
            headers={
                "User-Agent": (
                    f"clinical-evidence-nlp/1.0 (mailto:{settings.contact_email})"
                ),
                "Accept": "application/json",
            },
            follow_redirects=True,
        )

    @staticmethod
    def _coerce_year(value) -> int | None:
        try:
            year = int(str(value)[:4])
        except (TypeError, ValueError):
            return None
        return year if 1800 < year < 2100 else None
