"""OpenAlex (https://docs.openalex.org): ~250M works across all disciplines.

Used both as a search source and to verify every candidate by DOI, so one
uniform quality gate can be applied whichever database a result came from.
Also home to the helpers that read fields out of an OpenAlex work record.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..config import Settings
from ..criteria import VENUE_TYPES, VETTING_LISTS
from ..models import Article
from ..text import as_int, clean_text, doi_link, make_synopsis, normalize_doi, safe_url
from ..upstream import fetch_json

KEY, LABEL, FIRST_PAGE = "openalex", "OpenAlex", "1"
URL = "https://api.openalex.org/works"
FIELDS = ("ids,doi,title,type,publication_year,cited_by_count,authorships,"
          "primary_location,open_access,abstract_inverted_index,is_retracted,"
          "study_designs,funders,citation_normalized_percentile,primary_topic,best_oa_location")
MAX_PAGE = 500
LOOKUP_BATCH = 50


# --------------------------------------------------------------------------
# Reading an OpenAlex work record
# --------------------------------------------------------------------------

def source_of(work: dict) -> dict:
    location = work.get("primary_location")
    source = location.get("source") if isinstance(location, dict) else None
    return source if isinstance(source, dict) else {}


def study_designs(work: dict) -> set[str]:
    designs = work.get("study_designs")
    return {str(d.get("display_name", "")).lower()
            for d in designs if isinstance(d, dict)} if isinstance(designs, list) else set()


def field_of(work: dict) -> str:
    """The paper's field (e.g. "Computer Science") from OpenAlex's topic model."""
    topic = work.get("primary_topic")
    field = topic.get("field") if isinstance(topic, dict) else None
    return clean_text(field.get("display_name"), 80) if isinstance(field, dict) else ""


def company_affiliations(work: dict) -> list[str]:
    """Names of companies that any author is affiliated with."""
    names: list[str] = []
    for authorship in (work.get("authorships") or [])[:30]:
        if not isinstance(authorship, dict):
            continue
        for inst in authorship.get("institutions") or []:
            if isinstance(inst, dict) and inst.get("type") == "company":
                name = clean_text(inst.get("display_name"), 80)
                if name and name not in names:
                    names.append(name)
    return names


def funder_names(work: dict) -> list[str]:
    return [name for f in (work.get("funders") or [])[:20]
            if isinstance(f, dict) and (name := clean_text(f.get("display_name"), 80))]


def pmid_of(work: dict) -> str:
    ids = work.get("ids")
    raw = str(ids.get("pmid") or "") if isinstance(ids, dict) else ""
    digits = raw.rstrip("/").rsplit("/", 1)[-1]
    return digits if digits.isdigit() and len(digits) <= 10 else ""


# OpenAlex's open-access data is the same as Unpaywall's (both are run by the
# nonprofit OurResearch), so the free-copy link needs no extra API call.
_VERSIONS = {
    "publishedVersion": "published version",
    "acceptedVersion": "accepted manuscript (peer-reviewed text)",
    "submittedVersion": "submitted manuscript (before peer review)",
}


def free_copy(work: dict) -> dict | None:
    """The best legal free copy of the work, or None."""
    oa = work.get("open_access")
    location = work.get("best_oa_location")
    if not (isinstance(oa, dict) and oa.get("is_oa") and isinstance(location, dict)):
        return None
    url = safe_url(location.get("pdf_url")) or safe_url(location.get("landing_page_url"))
    if not url:
        return None
    host = location.get("source")
    return {
        "url": url,
        "version": _VERSIONS.get(location.get("version"), ""),
        "license": clean_text(location.get("license"), 40),
        "host": clean_text(host.get("display_name"), 120) if isinstance(host, dict) else "",
    }


def _abstract(inverted: Any) -> str:
    """OpenAlex stores abstracts as {word: [positions]}; rebuild the text."""
    if not isinstance(inverted, dict):
        return ""
    positions: dict[int, str] = {}
    for word, idxs in inverted.items():
        if not isinstance(word, str) or not isinstance(idxs, list):
            continue
        for i in idxs:
            if isinstance(i, int) and 0 <= i < 5000:
                positions[i] = word
    return " ".join(positions[i] for i in sorted(positions))


# --------------------------------------------------------------------------
# API calls
# --------------------------------------------------------------------------

def _params(settings: Settings) -> dict[str, Any]:
    params: dict[str, Any] = {"select": FIELDS}
    if settings.contact_email:
        params["mailto"] = settings.contact_email
    if settings.openalex_api_key:
        params["api_key"] = settings.openalex_api_key
    return params


def _to_article(work: dict) -> Article | None:
    doi = normalize_doi(work.get("doi"))
    abstract = clean_text(_abstract(work.get("abstract_inverted_index")), 6000)
    title = clean_text(work.get("title"), 400)
    synopsis = make_synopsis(abstract)
    if not (title and doi and synopsis):
        return None
    authors = [clean_text((a.get("author") or {}).get("display_name"), 120)
               for a in (work.get("authorships") or [])[:6] if isinstance(a, dict)]
    oa = work.get("open_access") or {}
    return Article(
        title=title, url=doi_link(doi), synopsis=synopsis,
        authors=[a for a in authors if a],
        journal=clean_text(source_of(work).get("display_name"), 200),
        year=as_int(work.get("publication_year")),
        doi=doi,
        citations=as_int(work.get("cited_by_count")),
        open_access=bool(oa.get("is_oa")) if isinstance(oa, dict) else False,
        source=LABEL,
        abstract=abstract,
        openalex=work,
    )


async def search(client: httpx.AsyncClient, settings: Settings, query: str, cursor: str,
                 per_page: int) -> tuple[list[Article], str | None]:
    page = int(cursor) if cursor.isdigit() and 0 < int(cursor) <= MAX_PAGE else 1
    params = _params(settings) | {
        "search": query,
        # Articles/reviews in expert-vetted journals or rated conference
        # proceedings, never retracted.
        "filter": ("type:article|review,is_retracted:false,is_paratext:false,has_abstract:true,"
                   f"primary_location.source.type:{'|'.join(VENUE_TYPES)},"
                   f"primary_location.source.listed_in:{'|'.join(VETTING_LISTS)}"),
        "per_page": per_page,
        # Plain page numbers: OpenAlex only allows cursor paging with an API key.
        "page": page,
    }
    data = await fetch_json(client, URL, params=params)
    results = data.get("results") if isinstance(data, dict) else None
    works = [w for w in results if isinstance(w, dict)] if isinstance(results, list) else []
    articles = [a for w in works if (a := _to_article(w))]
    meta = data.get("meta") if isinstance(data, dict) else None
    count = as_int(meta.get("count")) if isinstance(meta, dict) else None
    has_more = bool(works) and (count is None or page * per_page < count) and page < MAX_PAGE
    return articles, str(page + 1) if has_more else None


async def enrich(client: httpx.AsyncClient, settings: Settings, articles: list[Article]) -> None:
    """Attach OpenAlex records (venue vetting, study design, funders, …) by DOI.

    Articles that cannot be found keep openalex=None and are later rejected by
    the quality gate, since their venue cannot be verified.
    """
    # '|' and ',' are filter syntax in OpenAlex; DOIs containing them are skipped.
    pending = [a for a in articles if a.openalex is None and a.doi
               and not any(c in a.doi for c in "|,")]
    for start in range(0, len(pending), LOOKUP_BATCH):
        batch = pending[start:start + LOOKUP_BATCH]
        params = _params(settings) | {
            "filter": "doi:" + "|".join(doi_link(a.doi) for a in batch),
            "per_page": LOOKUP_BATCH,
        }
        data = await fetch_json(client, URL, params=params)
        results = data.get("results") if isinstance(data, dict) else None
        by_doi = {normalize_doi(w.get("doi")): w
                  for w in results if isinstance(w, dict)} if isinstance(results, list) else {}
        for article in batch:
            article.openalex = by_doi.get(article.doi)
