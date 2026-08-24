"""PubMed / NCBI E-utilities.

Two calls: ``esearch`` returns PMIDs for the query, ``efetch`` returns the
records as XML.  Abstracts arrive as several ``<AbstractText>`` elements with a
``Label`` attribute on structured abstracts -- we keep those labels, because
"METHODS: ..." in the abstract is a free section signal for the sectioniser.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

from app.config import settings
from app.ingest.sources.base import LiteratureSource, SourceError
from app.schemas import LiteratureHit

logger = logging.getLogger(__name__)

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


class PubMedSource(LiteratureSource):
    name = "pubmed"
    display_name = "PubMed"
    homepage = "https://pubmed.ncbi.nlm.nih.gov"

    def search(self, query: str, limit: int) -> list[LiteratureHit]:
        params = {
            "db": "pubmed",
            "term": query,
            "retmax": str(min(limit, 50)),
            "retmode": "json",
            "sort": "relevance",
        }
        if settings.pubmed_api_key:
            params["api_key"] = settings.pubmed_api_key

        with self._client() as client:
            try:
                search_response = client.get(f"{BASE}/esearch.fcgi", params=params)
                search_response.raise_for_status()
                ids = (
                    search_response.json()
                    .get("esearchresult", {})
                    .get("idlist", [])
                )
            except Exception as exc:
                raise SourceError(f"PubMed search failed: {exc}") from exc

            if not ids:
                return []

            fetch_params = {"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}
            if settings.pubmed_api_key:
                fetch_params["api_key"] = settings.pubmed_api_key
            try:
                fetch_response = client.get(f"{BASE}/efetch.fcgi", params=fetch_params)
                fetch_response.raise_for_status()
                root = ET.fromstring(fetch_response.content)
            except Exception as exc:
                raise SourceError(f"PubMed fetch failed: {exc}") from exc

        return [
            hit
            for hit in (self._parse_article(article) for article in root.iter("PubmedArticle"))
            if hit is not None
        ]

    # ------------------------------------------------------------------ parse
    def _parse_article(self, article: ET.Element) -> LiteratureHit | None:
        pmid_element = article.find(".//PMID")
        if pmid_element is None or not (pmid_element.text or "").strip():
            return None
        pmid = pmid_element.text.strip()

        title = self._text(article.find(".//ArticleTitle")) or "(untitled)"
        journal = self._text(article.find(".//Journal/Title"))
        year = self._coerce_year(
            self._text(article.find(".//JournalIssue/PubDate/Year"))
            or self._text(article.find(".//JournalIssue/PubDate/MedlineDate"))
        )

        parts: list[str] = []
        for node in article.iter("AbstractText"):
            body = self._text(node)
            if not body:
                continue
            label = (node.attrib.get("Label") or "").strip()
            parts.append(f"{label.title()}: {body}" if label else body)
        abstract = "\n\n".join(parts) or None

        authors: list[str] = []
        for author in article.iter("Author"):
            last = self._text(author.find("LastName"))
            initials = self._text(author.find("Initials"))
            if last:
                authors.append(f"{last} {initials}".strip())
        author_line = ", ".join(authors[:12]) or None
        if len(authors) > 12:
            author_line = f"{author_line} et al."

        doi = None
        for identifier in article.iter("ArticleId"):
            if identifier.attrib.get("IdType") == "doi":
                doi = (identifier.text or "").strip() or None
                break

        return LiteratureHit(
            source=self.name,
            external_id=pmid,
            title=title,
            abstract=abstract,
            authors=author_line,
            journal=journal,
            year=year,
            doi=doi,
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        )

    @staticmethod
    def _text(element: ET.Element | None) -> str | None:
        if element is None:
            return None
        # itertext() flattens inline markup such as <i> and <sup>.
        value = "".join(element.itertext()).strip()
        return value or None
