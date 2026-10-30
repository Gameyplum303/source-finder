"""PubMed E-utilities (https://www.ncbi.nlm.nih.gov/books/NBK25501/), used for
enrichment only: conflict-of-interest statements, indexer-assigned publication
types, grant agencies, trial-registry links and retraction links."""

from __future__ import annotations

import re
from typing import Any

import defusedxml.ElementTree as DefusedET
import httpx
from defusedxml import DefusedXmlException

from ..config import Settings
from ..models import Article
from ..text import clean_text, normalize_pub_type
from ..upstream import UpstreamError, fetch_bytes
from . import openalex

LABEL = "PubMed"
URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
BATCH = 100

# "Comments/corrections" links that mean the findings are in doubt.
_CONCERNS = {"RetractionIn", "ExpressionOfConcernIn", "RetractedandRepublishedIn"}
_REGISTRIES = re.compile(r"clinicaltrials\.gov|isrctn|anzctr|chictr|drks|euctr|ctri|prospero",
                         re.IGNORECASE)


def _xml_text(node: Any) -> str:
    return clean_text("".join(node.itertext()), 3000) if node is not None else ""


def parse_pubmed_xml(body: bytes) -> dict[str, dict[str, Any]]:
    """Extract per-PMID signals from an efetch XML response.

    defusedxml refuses entity expansion and external references, so a hostile
    or compromised response cannot trigger XXE or "billion laughs" attacks.
    """
    root = DefusedET.fromstring(body)
    records: dict[str, dict[str, Any]] = {}
    for art in root.iter("PubmedArticle"):
        pmid = (art.findtext("MedlineCitation/PMID") or "").strip()
        if not pmid.isdigit():
            continue
        banks = [_xml_text(b.find("DataBankName")) for b in art.iter("DataBank")]
        records[pmid] = {
            "coi": _xml_text(art.find(".//CoiStatement")),
            "pub_types": [_xml_text(p) for p in art.iter("PublicationType")][:20],
            "agencies": [_xml_text(a) for a in art.iter("Agency")][:20],
            "registered": any(_REGISTRIES.search(b) for b in banks),
            "concern": any(c.get("RefType") in _CONCERNS for c in art.iter("CommentsCorrections")),
        }
    return records


def _pmid(article: Article) -> str:
    if article.pmid.isdigit():
        return article.pmid
    return openalex.pmid_of(article.openalex or {})


async def enrich(client: httpx.AsyncClient, settings: Settings, articles: list[Article]) -> None:
    """Attach PubMed signals to the articles that are indexed in PubMed."""
    by_pmid = {pmid: a for a in articles if (pmid := _pmid(a))}
    pmids = list(by_pmid)
    for start in range(0, len(pmids), BATCH):
        batch = pmids[start:start + BATCH]
        params: dict[str, Any] = {"db": "pubmed", "retmode": "xml", "id": ",".join(batch),
                                  "tool": "source-finder"}
        if settings.contact_email:
            params["email"] = settings.contact_email
        if settings.ncbi_api_key:
            params["api_key"] = settings.ncbi_api_key
        body = await fetch_bytes(client, URL, params=params)
        try:
            records = parse_pubmed_xml(body)
        except (DefusedET.ParseError, DefusedXmlException) as exc:
            raise UpstreamError(f"PubMed returned unusable XML: {type(exc).__name__}") from exc
        for pmid in batch:
            if record := records.get(pmid):
                article = by_pmid[pmid]
                article.pmid = pmid
                article.pubmed = record
                article.pub_types |= {normalize_pub_type(t) for t in record["pub_types"]}
                article.has_concern = article.has_concern or record["concern"]
