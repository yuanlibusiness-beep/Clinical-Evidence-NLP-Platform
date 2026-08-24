"""Crossref.

Crossref is the DOI registry, so it is the best source for canonical metadata
(journal, year, authors) even when it has no abstract.  Abstracts, when present,
arrive as JATS XML embedded in a JSON string, which we strip to plain text.
"""

from __future__ import annotations

import logging
import re

from app.config import settings
from app.ingest.sources.base import LiteratureSource, SourceError
from app.schemas import LiteratureHit

logger = logging.getLogger(__name__)

ENDPOINT = "https://api.crossref.org/works"
_TAG = re.compile(r"<[^>]+>")


class CrossrefSource(LiteratureSource):
    name = "crossref"
    display_name = "Crossref"
    homepage = "https://www.crossref.org"

    def search(self, query: str, limit: int) -> list[LiteratureHit]:
        params = {
            "query.bibliographic": query,
            "rows": str(min(limit, 50)),
            "select": "DOI,title,abstract,author,container-title,issued,URL,type",
            "mailto": settings.contact_email,
        }
        with self._client() as client:
            try:
                response = client.get(ENDPOINT, params=params)
                response.raise_for_status()
                items = response.json().get("message", {}).get("items", [])
            except Exception as exc:
                raise SourceError(f"Crossref search failed: {exc}") from exc

        hits: list[LiteratureHit] = []
        for item in items:
            doi = item.get("DOI")
            if not doi:
                continue
            titles = item.get("title") or []
            containers = item.get("container-title") or []
            issued = (item.get("issued") or {}).get("date-parts") or [[None]]

            authors = ", ".join(
                f"{person.get('family', '')} {person.get('given', '')[:1]}".strip()
                for person in (item.get("author") or [])[:12]
                if person.get("family")
            )

            abstract = item.get("abstract")
            if abstract:
                abstract = _TAG.sub(" ", abstract)
                abstract = re.sub(r"\s{2,}", " ", abstract).strip()

            hits.append(
                LiteratureHit(
                    source=self.name,
                    external_id=doi,
                    title=(titles[0] if titles else "(untitled)").strip(),
                    abstract=abstract or None,
                    authors=authors or None,
                    journal=(containers[0] if containers else None),
                    year=self._coerce_year(issued[0][0] if issued and issued[0] else None),
                    doi=doi,
                    url=item.get("URL") or f"https://doi.org/{doi}",
                )
            )
        return hits
