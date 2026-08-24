"""Source registry and the federated search that fans out across it.

Behaviour that matters in review:

* Sources are queried **concurrently**, so adding a fourth database costs
  latency only if it is the slowest one.
* A failing source is reported in ``errors`` and the rest of the result set is
  still returned.  One flaky upstream must not fail the user's search.
* Results are **deduplicated across sources** by DOI first, then by a normalised
  title, keeping the record with the richest abstract -- the same paper indexed
  in PubMed and Crossref should appear once.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.ingest.sources.base import LiteratureSource, SourceError
from app.ingest.sources.crossref import CrossrefSource
from app.ingest.sources.europepmc import EuropePmcSource
from app.ingest.sources.pubmed import PubMedSource
from app.schemas import LiteratureHit

logger = logging.getLogger(__name__)

REGISTRY: dict[str, type[LiteratureSource]] = {
    PubMedSource.name: PubMedSource,
    EuropePmcSource.name: EuropePmcSource,
    CrossrefSource.name: CrossrefSource,
}

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def available_sources() -> list[dict[str, str]]:
    return [
        {
            "name": cls.name,
            "display_name": cls.display_name,
            "homepage": cls.homepage,
        }
        for cls in REGISTRY.values()
    ]


def _title_key(title: str) -> str:
    return _NON_ALNUM.sub("", title.lower())[:120]


def _richness(hit: LiteratureHit) -> int:
    return len(hit.abstract or "") + (50 if hit.doi else 0)


def deduplicate(hits: list[LiteratureHit]) -> list[LiteratureHit]:
    best: dict[str, LiteratureHit] = {}
    order: list[str] = []

    for hit in hits:
        key = f"doi:{hit.doi.lower()}" if hit.doi else f"title:{_title_key(hit.title)}"
        if key not in best:
            best[key] = hit
            order.append(key)
        elif _richness(hit) > _richness(best[key]):
            best[key] = hit

    return [best[key] for key in order]


def search_all(
    query: str, sources: list[str], limit: int
) -> tuple[list[LiteratureHit], dict[str, str]]:
    selected = [name for name in sources if name in REGISTRY]
    if not selected:
        return [], {"_": f"No known sources in {sources!r}"}

    hits: list[LiteratureHit] = []
    errors: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=min(len(selected), 6)) as pool:
        futures = {
            pool.submit(REGISTRY[name]().search, query, limit): name
            for name in selected
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                hits.extend(future.result())
            except SourceError as exc:
                logger.warning("Source %s failed: %s", name, exc)
                errors[name] = str(exc)
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Source %s crashed", name)
                errors[name] = f"Unexpected error: {exc}"

    deduped = deduplicate(hits)
    deduped.sort(key=lambda hit: (-(hit.year or 0), hit.title.lower()))
    return deduped[: limit * len(selected)], errors


__all__ = [
    "REGISTRY",
    "LiteratureSource",
    "SourceError",
    "available_sources",
    "deduplicate",
    "search_all",
]
