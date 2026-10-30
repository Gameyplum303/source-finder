"""Crossref (https://api.crossref.org), used for enrichment only: a retraction
check against Crossref's update notices, which include the hand-curated
Retraction Watch database (acquired by Crossref in 2023).

One batched request per search: `filter=updates:<doi>,updates:<doi>,...`
returns every notice (retraction, correction, …) that updates any of the DOIs.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..config import Settings
from ..models import Article
from ..text import normalize_doi
from ..upstream import fetch_json

LABEL = "Crossref retraction check"
URL = "https://api.crossref.org/works"
BATCH = 50

# Update types that mean an article's findings should not be relied on.
# (Corrections and errata are normal and do not count.)
CONCERN_TYPES = {"retraction", "partial_retraction", "withdrawal", "removal", "expression_of_concern"}


async def enrich(client: httpx.AsyncClient, settings: Settings, articles: list[Article]) -> None:
    # ',' separates filters in Crossref queries; DOIs containing it are skipped.
    by_doi = {a.doi: a for a in articles if a.doi and "," not in a.doi}
    dois = list(by_doi)
    for start in range(0, len(dois), BATCH):
        batch = dois[start:start + BATCH]
        params: dict[str, Any] = {
            "filter": ",".join(f"updates:{doi}" for doi in batch),
            "select": "DOI,update-to",
            "rows": 1000,
        }
        if settings.contact_email:
            params["mailto"] = settings.contact_email   # Crossref's "polite pool"
        data = await fetch_json(client, URL, params=params)
        message = data.get("message") if isinstance(data, dict) else None
        items = message.get("items") if isinstance(message, dict) else None
        for notice in items if isinstance(items, list) else []:
            updates = notice.get("update-to") if isinstance(notice, dict) else None
            for update in updates if isinstance(updates, list) else []:
                if not isinstance(update, dict):
                    continue
                article = by_doi.get(normalize_doi(update.get("DOI")))
                if article and str(update.get("type", "")).lower() in CONCERN_TYPES:
                    article.has_concern = True
        for doi in batch:
            by_doi[doi].retraction_checked = True
