"""Europe PMC.

Broader than PubMed (preprints, agricola, patents) and, unlike PubMed, exposes
open-access full text.  ``isOpenAccess`` is carried through because a full-text
paper produces far better extractions than an abstract alone.
"""

from __future__ import annotations

import logging

from app.ingest.sources.base import LiteratureSource, SourceError
from app.schemas import LiteratureHit

logger = logging.getLogger(__name__)

ENDPOINT = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
FULLTEXT = "https://www.ebi.ac.uk/europepmc/webservices/rest/{source}/{pmcid}/fullTextXML"


class EuropePmcSource(LiteratureSource):
    name = "europepmc"
    display_name = "Europe PMC"
    homepage = "https://europepmc.org"

    def search(self, query: str, limit: int) -> list[LiteratureHit]:
        params = {
            "query": query,
            "format": "json",
            "pageSize": str(min(limit, 50)),
            "resultType": "core",
        }
        with self._client() as client:
            try:
                response = client.get(ENDPOINT, params=params)
                response.raise_for_status()
                results = response.json().get("resultList", {}).get("result", [])
            except Exception as exc:
                raise SourceError(f"Europe PMC search failed: {exc}") from exc

        hits: list[LiteratureHit] = []
        for record in results:
            identifier = record.get("id") or record.get("pmid") or record.get("doi")
            if not identifier:
                continue
            hits.append(
                LiteratureHit(
                    source=self.name,
                    external_id=str(identifier),
                    title=(record.get("title") or "(untitled)").strip(),
                    abstract=(record.get("abstractText") or None),
                    authors=record.get("authorString"),
                    journal=record.get("journalTitle"),
                    year=self._coerce_year(record.get("pubYear")),
                    doi=record.get("doi"),
                    url=(
                        f"https://europepmc.org/article/"
                        f"{record.get('source', 'MED')}/{identifier}"
                    ),
                )
            )
        return hits

    def fetch_full_text(self, pmcid: str, source: str = "PMC") -> str:
        """Best-effort open-access full text; returns '' when unavailable."""
        with self._client() as client:
            try:
                response = client.get(FULLTEXT.format(source=source, pmcid=pmcid))
                response.raise_for_status()
            except Exception as exc:
                logger.info("No open-access full text for %s: %s", pmcid, exc)
                return ""

        import xml.etree.ElementTree as ET

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError:
            return ""

        pieces: list[str] = []
        for section in root.iter("sec"):
            title_node = section.find("title")
            if title_node is not None and (title_node.text or "").strip():
                pieces.append(f"\n\n{title_node.text.strip()}\n")
            for paragraph in section.iter("p"):
                text = "".join(paragraph.itertext()).strip()
                if text:
                    pieces.append(text)
        return "\n\n".join(pieces).strip()
