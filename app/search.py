"""The search pipeline: query every source, merge, verify, vet and score.

    sources (in parallel) -> interleave + dedupe by DOI -> OpenAlex verification
    -> PubMed enrichment -> quality gate + risk of bias -> cached payload
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import Settings
from .limits import TTLCache
from .models import Article
from .quality import vet_and_score
from .sources import SEARCH_SOURCES, active_sources, crossref, openalex, pubmed
from .upstream import UpstreamError

log = logging.getLogger("source_finder.search")

MIN_QUERY_LEN, MAX_QUERY_LEN = 3, 200
MAX_TOKEN_LEN = 2048
PER_SOURCE = 10
CACHE_TTL = 15 * 60
PARTIAL_CACHE_TTL = 2 * 60   # answers missing a source are retried soon
_CURSOR_VALUE_RE = re.compile(r"^[A-Za-z0-9*+/=_.\-]{1,512}$")


class SearchError(Exception):
    """A search could not be served; the message is safe to show users."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------
# Input validation
# --------------------------------------------------------------------------

def clean_query(raw: str) -> str | None:
    """Normalize the search text; return None if it is not acceptable."""
    text = unicodedata.normalize("NFKC", raw)
    # Remove control / format characters (including zero-width and bidi tricks).
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C")
    text = re.sub(r"\s+", " ", text).strip()
    if not (MIN_QUERY_LEN <= len(text) <= MAX_QUERY_LEN) or not any(ch.isalnum() for ch in text):
        return None
    return text


def encode_page_token(cursors: dict[str, str]) -> str | None:
    if not cursors:
        return None
    raw = json.dumps(cursors, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_page_token(token: str) -> dict[str, str] | None:
    """Parse the opaque paging token; reject anything unexpected."""
    if len(token) > MAX_TOKEN_LEN:
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    except (binascii.Error, ValueError):
        return None
    if not isinstance(data, dict) or not data:
        return None
    if not all(k in SEARCH_SOURCES and isinstance(v, str) and _CURSOR_VALUE_RE.match(v)
               for k, v in data.items()):
        return None
    return data


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------

@dataclass
class SearchResult:
    payload: dict[str, Any]
    articles: list[Article] = field(default_factory=list)   # vetted, for AI review


def interleave(per_source: list[list[Article]]) -> list[Article]:
    """Round-robin across sources so the top mixes each one's best hits; drop duplicate DOIs."""
    seen: set[str] = set()
    merged: list[Article] = []
    for i in range(max((len(lst) for lst in per_source), default=0)):
        for lst in per_source:
            if i < len(lst) and lst[i].doi not in seen:
                seen.add(lst[i].doi)
                merged.append(lst[i])
    return merged


class SearchService:
    def __init__(self, client: httpx.AsyncClient, settings: Settings):
        self.client, self.settings = client, settings
        self.cache: TTLCache[SearchResult] = TTLCache(max_items=500, ttl=CACHE_TTL)

    async def search(self, raw_query: str, page_token: str = "") -> SearchResult:
        query = clean_query(raw_query)
        if query is None:
            raise SearchError(f"Please enter a topic between {MIN_QUERY_LEN} and "
                              f"{MAX_QUERY_LEN} characters.", 400)
        if page_token:
            cursors = decode_page_token(page_token)
            if cursors is None:
                raise SearchError("Invalid page token. Please start a new search.", 400)
        else:
            cursors = {key: src.first_page for key, src in active_sources(self.settings).items()}
        # Ignore positions for sources that are switched off (e.g. CORE without a key).
        cursors = {k: v for k, v in cursors.items() if k in active_sources(self.settings)}
        if not cursors:
            raise SearchError("No search sources are available.", 502)

        cache_key = json.dumps([query.lower(), sorted(cursors.items())])
        if (cached := self.cache.get(cache_key)) is not None:
            return cached

        result = await self._run(query, cursors)
        complete = not result.payload["unavailable"]
        self.cache.put(cache_key, result, CACHE_TTL if complete else PARTIAL_CACHE_TTL)
        return result

    async def _run(self, query: str, cursors: dict[str, str]) -> SearchResult:
        keys = list(cursors)
        outcomes = await asyncio.gather(
            *(SEARCH_SOURCES[k].search(self.client, self.settings, query, cursors[k], PER_SOURCE)
              for k in keys),
            return_exceptions=True,
        )
        per_source: list[list[Article]] = []
        next_cursors: dict[str, str] = {}
        unavailable: list[str] = []
        for key, outcome in zip(keys, outcomes):
            if isinstance(outcome, BaseException):
                self._log_failure(key, outcome)
                unavailable.append(SEARCH_SOURCES[key].label)
                next_cursors[key] = cursors[key]   # retry it on "Load more"
                continue
            articles, next_cursor = outcome
            per_source.append(articles)
            if next_cursor:
                next_cursors[key] = next_cursor
        if len(unavailable) == len(keys):
            raise SearchError("The article databases could not be reached. Please try again shortly.", 502)

        candidates = interleave(per_source)
        # OpenAlex verification is required (unverified articles are dropped).
        try:
            await openalex.enrich(self.client, self.settings, candidates)
        except UpstreamError as exc:
            log.warning("OpenAlex verification failed: %s", exc)
            unavailable.append("OpenAlex verification")
        # PubMed and Crossref add signals in parallel; if either fails, results
        # are still shown with less information (and the failure is reported).
        optional = (pubmed, crossref)
        outcomes = await asyncio.gather(
            *(m.enrich(self.client, self.settings, candidates) for m in optional),
            return_exceptions=True)
        for module, outcome in zip(optional, outcomes):
            if isinstance(outcome, BaseException):
                self._log_failure(module.LABEL, outcome)
                unavailable.append(module.LABEL)
        passed, rejected = vet_and_score(candidates)
        for article in passed:
            article.free_access = openalex.free_copy(article.openalex or {}) or article.free_access

        return SearchResult(
            payload={
                "query": query,
                "results": [a.to_dict() for a in passed],
                "rejected": rejected,
                "next": encode_page_token(next_cursors),
                "unavailable": unavailable,
            },
            articles=passed,
        )

    @staticmethod
    def _log_failure(key: str, exc: BaseException) -> None:
        # Details go to the server log only; users just see which source failed.
        if isinstance(exc, UpstreamError):
            log.warning("source %s failed: %s", key, exc)
        else:
            log.error("source %s crashed", key, exc_info=exc)
