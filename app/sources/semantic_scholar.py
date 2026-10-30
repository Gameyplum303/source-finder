"""Semantic Scholar (https://api.semanticscholar.org): all disciplines, with
AI-written TL;DR summaries used as synopses when available."""

from __future__ import annotations

import httpx

from ..config import Settings
from ..models import Article
from ..text import as_int, clean_text, doi_link, make_synopsis, normalize_doi, normalize_pub_type
from ..upstream import fetch_json

KEY, LABEL, FIRST_PAGE = "s2", "Semantic Scholar", "0"
URL = "https://api.semanticscholar.org/graph/v1/paper/search"
MAX_OFFSET = 1000  # Semantic Scholar caps relevance search at 1000 results.


def _to_article(paper: dict) -> Article | None:
    types = paper.get("publicationTypes")
    types = types if isinstance(types, list) else []
    title = clean_text(paper.get("title"), 400)
    ids = paper.get("externalIds")
    ids = ids if isinstance(ids, dict) else {}
    doi = normalize_doi(ids.get("DOI"))
    abstract = clean_text(paper.get("abstract") or "", 6000)
    tldr = paper.get("tldr")
    summary = tldr.get("text") if isinstance(tldr, dict) else None
    synopsis = make_synopsis(summary or abstract)
    if not (title and doi and synopsis):
        return None
    journal = paper.get("journal")
    journal_name = journal.get("name") if isinstance(journal, dict) else ""
    authors = [clean_text(a.get("name"), 120)
               for a in (paper.get("authors") or [])[:6] if isinstance(a, dict)]
    return Article(
        title=title, url=doi_link(doi), synopsis=synopsis,
        authors=[a for a in authors if a],
        journal=clean_text(journal_name or paper.get("venue"), 200),
        year=as_int(paper.get("year")),
        doi=doi,
        citations=as_int(paper.get("citationCount")),
        open_access=bool(paper.get("isOpenAccess")),
        source=LABEL,
        abstract=abstract,
        pmid=str(ids.get("PubMed") or "")[:10],
        pub_types={normalize_pub_type(t) for t in types},
    )


async def search(client: httpx.AsyncClient, settings: Settings, query: str, cursor: str,
                 per_page: int) -> tuple[list[Article], str | None]:
    offset = int(cursor) if cursor.isdigit() else 0
    params = {
        "query": query,
        "offset": offset,
        "limit": per_page,
        "publicationTypes": "JournalArticle,Conference,Review,MetaAnalysis,ClinicalTrial,Study",
        "fields": ("title,abstract,tldr,year,venue,journal,authors,"
                   "externalIds,citationCount,isOpenAccess,publicationTypes"),
    }
    headers = {"x-api-key": settings.s2_api_key} if settings.s2_api_key else None
    data = await fetch_json(client, URL, params=params, headers=headers)
    papers = data.get("data") if isinstance(data, dict) else None
    papers = [p for p in papers if isinstance(p, dict)] if isinstance(papers, list) else []
    articles = [a for p in papers if (a := _to_article(p))]
    total = as_int(data.get("total")) if isinstance(data, dict) else None
    next_offset = offset + per_page
    has_more = bool(papers) and (total is None or next_offset < total) and next_offset < MAX_OFFSET
    return articles, str(next_offset) if has_more else None
