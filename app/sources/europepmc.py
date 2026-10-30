"""Europe PMC (https://europepmc.org/RestfulWebService): life sciences plus much
engineering and physical science, with correction/retraction links."""

from __future__ import annotations

import re

import httpx

from ..config import Settings
from ..models import Article
from ..text import as_int, clean_text, doi_link, make_synopsis, normalize_doi, normalize_pub_type
from ..upstream import fetch_json

KEY, LABEL, FIRST_PAGE = "europepmc", "Europe PMC", "*"
URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

# Correction notices that mean the article's findings are in doubt.
_CONCERNS = ("retraction in", "expression of concern in", "retracted and republished in")
_EXCLUDED_TYPES = ("retracted publication", "preprint", "editorial", "letter",
                   "comment", "news", "published erratum")


def build_query(query: str) -> str:
    """Wrap the user's text in parentheses and AND it with our filters.

    Grouping/quote characters are removed so input cannot close the group early
    and escape the peer-review filters (e.g. `x) OR (SRC:PPR`).
    """
    safe_query = re.sub(r"[()\[\]{}\"\\]", " ", query).strip() or "*"
    exclusions = " ".join(f'NOT PUB_TYPE:"{t}"' for t in _EXCLUDED_TYPES)
    return (f'({safe_query}) AND SRC:MED AND PUB_TYPE:"journal article" '
            f"AND HAS_ABSTRACT:Y AND HAS_DOI:Y {exclusions}")


def _to_article(item: dict) -> Article | None:
    title = clean_text(item.get("title"), 400).rstrip(".")
    doi = normalize_doi(item.get("doi"))
    abstract = clean_text(item.get("abstractText") or "", 6000)
    synopsis = make_synopsis(abstract)
    if not (title and doi and synopsis):
        return None
    author_list = (item.get("authorList") or {}).get("author") or []
    authors = [clean_text(a.get("fullName"), 120) for a in author_list[:6] if isinstance(a, dict)]
    journal_info = item.get("journalInfo") or {}
    journal = (journal_info.get("journal") or {}) if isinstance(journal_info, dict) else {}
    pub_types = (item.get("pubTypeList") or {}).get("pubType") or []
    corrections = (item.get("commentCorrectionList") or {}).get("commentCorrection") or []
    has_concern = isinstance(corrections, list) and any(
        isinstance(c, dict) and str(c.get("type", "")).lower() in _CONCERNS for c in corrections)
    return Article(
        title=title, url=doi_link(doi), synopsis=synopsis,
        authors=[a for a in authors if a],
        journal=clean_text(journal.get("title") if isinstance(journal, dict) else "", 200),
        year=as_int(item.get("pubYear")),
        doi=doi,
        citations=as_int(item.get("citedByCount")),
        open_access=item.get("isOpenAccess") == "Y",
        source=LABEL,
        abstract=abstract,
        pmid=str(item.get("pmid") or "")[:10],
        pub_types={normalize_pub_type(t) for t in pub_types} if isinstance(pub_types, list) else set(),
        has_concern=has_concern,
    )


async def search(client: httpx.AsyncClient, settings: Settings, query: str, cursor: str,
                 per_page: int) -> tuple[list[Article], str | None]:
    params = {
        "query": build_query(query),
        "format": "json",
        "resultType": "core",
        "pageSize": per_page,
        "cursorMark": cursor or FIRST_PAGE,
    }
    data = await fetch_json(client, URL, params=params)
    result_list = (data.get("resultList") or {}).get("result") if isinstance(data, dict) else None
    items = [i for i in result_list if isinstance(i, dict)] if isinstance(result_list, list) else []
    articles = [a for i in items if (a := _to_article(i))]
    next_cursor = data.get("nextCursorMark") if isinstance(data, dict) else None
    if not articles or not isinstance(next_cursor, str) or next_cursor == cursor:
        next_cursor = None
    return articles, next_cursor
