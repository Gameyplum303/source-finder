"""CORE (https://core.ac.uk): 400M+ records aggregated from thousands of
institutional and subject repositories and open-access journals, often with a
free full-text copy hosted by a university repository.

Requires a free API key (CORE_API_KEY); the source is skipped without one.
Results only reach users if they also pass the usual DOI-based quality gate,
so repository-only items without a DOI (theses, working papers) are dropped.
"""

from __future__ import annotations

import re

import httpx

from ..config import Settings
from ..models import Article
from ..text import as_int, clean_text, doi_link, make_synopsis, normalize_doi, safe_url
from ..upstream import fetch_json

KEY, LABEL, FIRST_PAGE = "core", "CORE", "0"
URL = "https://api.core.ac.uk/v3/search/works"
MAX_OFFSET = 1000

# CORE's query language is Elasticsearch-style; strip its operator characters
# so user text is searched as plain words and cannot alter the query.
_OPERATORS_RE = re.compile(r'[+\-=&|><!(){}\[\]^"~*?:\\/]')


def enabled(settings: Settings) -> bool:
    return bool(settings.core_api_key)


def build_query(query: str) -> str:
    return re.sub(r"\s+", " ", _OPERATORS_RE.sub(" ", query)).strip()


def _year(item: dict) -> int | None:
    year = as_int(item.get("yearPublished"))
    if year is None and isinstance(item.get("publishedDate"), str):
        year = as_int(item["publishedDate"][:4])
    return year


def _to_article(item: dict) -> Article | None:
    title = clean_text(item.get("title"), 400)
    doi = normalize_doi(item.get("doi"))
    abstract = clean_text(item.get("abstract") or "", 6000)
    synopsis = make_synopsis(abstract)
    if not (title and doi and synopsis):
        return None
    authors = [clean_text(a.get("name"), 120)
               for a in (item.get("authors") or [])[:6] if isinstance(a, dict)]
    journals = item.get("journals")
    journal = journals[0].get("title") if isinstance(journals, list) and journals \
        and isinstance(journals[0], dict) else None
    download = safe_url(item.get("downloadUrl"))
    return Article(
        title=title, url=doi_link(doi), synopsis=synopsis,
        authors=[a for a in authors if a],
        journal=clean_text(journal or item.get("publisher"), 200),
        year=_year(item),
        doi=doi,
        citations=as_int(item.get("citationCount")),
        open_access=bool(download),
        source=LABEL,
        abstract=abstract,
        # A repository copy; replaced later if OpenAlex knows a better free version.
        free_access={"url": download, "version": "", "license": "", "host": "CORE repository copy"}
        if download else None,
    )


async def search(client: httpx.AsyncClient, settings: Settings, query: str, cursor: str,
                 per_page: int) -> tuple[list[Article], str | None]:
    offset = int(cursor) if cursor.isdigit() else 0
    params = {"q": build_query(query) or "*", "limit": per_page, "offset": offset}
    headers = {"Authorization": f"Bearer {settings.core_api_key}"}
    data = await fetch_json(client, URL, params=params, headers=headers)
    results = data.get("results") if isinstance(data, dict) else None
    items = [i for i in results if isinstance(i, dict)] if isinstance(results, list) else []
    articles = [a for i in items if (a := _to_article(i))]
    total = as_int(data.get("totalHits")) if isinstance(data, dict) else None
    next_offset = offset + per_page
    has_more = bool(items) and (total is None or next_offset < total) and next_offset < MAX_OFFSET
    return articles, str(next_offset) if has_more else None
