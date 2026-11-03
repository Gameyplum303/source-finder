"""Scholarly databases, queried through their official free APIs.

Instead of scraping publisher websites (brittle, often against their terms of
service, and unable to tell a peer-reviewed article from a blog post), we query
the public APIs of large scholarly indexes.

To add a search engine: create a module exposing KEY, LABEL, FIRST_PAGE and
`async def search(client, settings, query, cursor, per_page)` (plus optional
`enabled(settings)` if it needs a key), then list it in SEARCH_SOURCES.
Enrichment-only services (no search) expose `enrich()` and LABEL instead.

All text coming back from upstream is untrusted: it is cleaned with
text.clean_text here, and the frontend renders it with textContent only.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Awaitable, Callable

import httpx

from ..config import Settings
from ..models import Article
from . import core, crossref, europepmc, openalex, pubmed, semantic_scholar

SearchFn = Callable[[httpx.AsyncClient, Settings, str, str, int],
                    Awaitable[tuple[list[Article], "str | None"]]]


def _always(settings: Settings) -> bool:
    return True


@dataclass(frozen=True)
class Source:
    key: str          # stable id used in paging tokens
    label: str        # shown to users when the source is unavailable
    first_page: str   # paging position of the first page (page / cursorMark / offset)
    search: SearchFn
    enabled: Callable[[Settings], bool] = _always


SEARCH_SOURCES: dict[str, Source] = {
    m.KEY: Source(m.KEY, m.LABEL, m.FIRST_PAGE, m.search, getattr(m, "enabled", _always))
    for m in (openalex, europepmc, semantic_scholar, core)
}


def active_sources(settings: Settings) -> dict[str, Source]:
    """The search sources usable with the current settings (e.g. CORE needs a key)."""
    return {key: src for key, src in SEARCH_SOURCES.items() if src.enabled(settings)}


__all__ = ["SEARCH_SOURCES", "Source", "active_sources", "core", "crossref", "europepmc",
           "openalex", "pubmed", "semantic_scholar"]
