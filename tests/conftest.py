"""Shared fixtures. Tests never touch the network: every upstream API is served
by FakeUpstream through an httpx.MockTransport."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient


def inverted_index(text: str) -> dict[str, list[int]]:
    index: dict[str, list[int]] = {}
    for i, word in enumerate(text.split()):
        index.setdefault(word, []).append(i)
    return index


def make_work(doi: str, title: str, abstract: str, *, listed=("medline", "cwts-core"),
              venue_type="journal", work_type="article", retracted=False, designs=(),
              funders=(), companies=(), pmid: str | None = None, field="Medicine",
              domain="Health Sciences", is_oa=True) -> dict[str, Any]:
    """An OpenAlex work record with only the fields the app reads."""
    institutions = [{"display_name": c, "type": "company"} for c in companies]
    return {
        "ids": {"pmid": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}"} if pmid else {},
        "doi": f"https://doi.org/{doi}",
        "title": title,
        "type": work_type,
        "publication_year": 2024,
        "cited_by_count": 12,
        "authorships": [{"author": {"display_name": "Ada Lovelace"},
                         "institutions": institutions or [{"display_name": "Uni", "type": "education"}]}],
        "primary_location": {"landing_page_url": None, "source": {
            "display_name": "Journal of Testing", "type": venue_type, "listed_in": list(listed)}},
        "open_access": {"is_oa": is_oa},
        "abstract_inverted_index": inverted_index(abstract),
        "is_retracted": retracted,
        "study_designs": [{"display_name": d} for d in designs],
        "funders": [{"display_name": f} for f in funders],
        "citation_normalized_percentile": {"is_in_top_1_percent": False, "is_in_top_10_percent": True},
        "primary_topic": {"field": {"display_name": field}, "domain": {"display_name": domain}},
    }


RCT_ABSTRACT = ("In this multicenter double-blind randomized controlled trial of 1,240 patients, "
                "the intervention reduced readmissions (hazard ratio 0.8, 95% CI 0.7 to 0.9). "
                "Limitations include short follow-up.")
COHORT_ABSTRACT = ("We followed a prospective cohort of 4,000 adults, adjusted for age and income, "
                   "and found screen time was associated with poorer sleep.")
UNVETTED_ABSTRACT = "An article in a journal that no expert committee has vetted, describing results."
RETRACTED_ABSTRACT = "A cohort study whose findings were later retracted by the journal for misconduct."


def pubmed_xml(records: dict[str, dict[str, Any]]) -> bytes:
    parts = ['<?xml version="1.0"?><!DOCTYPE PubmedArticleSet><PubmedArticleSet>']
    for pmid, rec in records.items():
        types = "".join(f"<PublicationType>{t}</PublicationType>" for t in rec.get("types", []))
        agencies = "".join(f"<Grant><Agency>{a}</Agency></Grant>" for a in rec.get("agencies", []))
        corrections = "".join(f'<CommentsCorrections RefType="{r}"/>' for r in rec.get("corrections", []))
        banks = "".join(f"<DataBank><DataBankName>{b}</DataBankName></DataBank>"
                        for b in rec.get("banks", []))
        parts.append(
            f"<PubmedArticle><MedlineCitation><PMID>{pmid}</PMID><Article>"
            f"<PublicationTypeList>{types}</PublicationTypeList><GrantList>{agencies}</GrantList>"
            f"<DataBankList>{banks}</DataBankList></Article>"
            f"<CommentsCorrectionsList>{corrections}</CommentsCorrectionsList>"
            f"<CoiStatement>{rec.get('coi', '')}</CoiStatement></MedlineCitation></PubmedArticle>")
    parts.append("</PubmedArticleSet>")
    return "".join(parts).encode()


class FakeUpstream:
    """Routes requests to canned OpenAlex / Europe PMC / Semantic Scholar / PubMed data."""

    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.down = False
        self.s2_status = 200
        self.pubmed_status = 200
        self.search_works = [
            make_work("10.1000/rct1", "Readmission trial", RCT_ABSTRACT, pmid="111",
                      designs=("Randomized Controlled Trial",)),
            make_work("10.1000/unvetted", "Unvetted study", UNVETTED_ABSTRACT, listed=()),
        ]
        self.lookup_works = {
            "10.1000/epmc2": make_work("10.1000/epmc2", "Screen time cohort", COHORT_ABSTRACT, pmid="222",
                                       field="Psychology", domain="Social Sciences"),
            "10.1000/retracted": make_work("10.1000/retracted", "Retracted cohort", RETRACTED_ABSTRACT),
        }
        self.epmc_results = [
            {"title": "Readmission trial", "doi": "10.1000/rct1", "abstractText": RCT_ABSTRACT, "pmid": "111"},
            {"title": "Screen time cohort.", "doi": "10.1000/epmc2", "abstractText": COHORT_ABSTRACT,
             "pmid": "222", "pubYear": "2023", "citedByCount": 4, "isOpenAccess": "N",
             "authorList": {"author": [{"fullName": "Grace Hopper"}]},
             "journalInfo": {"journal": {"title": "Sleep Journal"}},
             "pubTypeList": {"pubType": ["Journal Article"]}},
            {"title": "Retracted cohort", "doi": "10.1000/retracted", "abstractText": RETRACTED_ABSTRACT,
             "commentCorrectionList": {"commentCorrection": [{"type": "Retraction in"}]}},
        ]
        self.pubmed_records = {
            "111": {"coi": "The authors declare no competing interests.",
                    "types": ["Journal Article", "Randomized Controlled Trial"],
                    "agencies": ["NIH HHS"], "banks": ["ClinicalTrials.gov"]},
            "222": {"coi": "J.D. is an employee of Pfizer.", "types": ["Journal Article"]},
        }

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.down:
            return httpx.Response(503)
        host, params = request.url.host, parse_qs(request.url.query.decode())
        if host == "api.openalex.org":
            flt = params.get("filter", [""])[0]
            if flt.startswith("doi:"):
                dois = [d.removeprefix("https://doi.org/") for d in flt[4:].split("|")]
                results = [self.lookup_works[d] for d in dois if d in self.lookup_works]
            else:
                results = self.search_works if params.get("page", ["1"])[0] == "1" else []
            return httpx.Response(200, json={"meta": {"count": 25}, "results": results})
        if host == "www.ebi.ac.uk":
            return httpx.Response(200, json={"nextCursorMark": "AoNEXT", "resultList": {"result": self.epmc_results}})
        if host == "api.semanticscholar.org":
            if self.s2_status != 200:
                return httpx.Response(self.s2_status)
            return httpx.Response(200, json={"total": 0, "data": []})
        if host == "api.crossref.org":
            return httpx.Response(200, json={"message": {"items": []}})
        if host == "eutils.ncbi.nlm.nih.gov":
            if self.pubmed_status != 200:
                return httpx.Response(self.pubmed_status)
            ids = params.get("id", [""])[0].split(",")
            return httpx.Response(200, content=pubmed_xml(
                {i: r for i, r in self.pubmed_records.items() if i in ids}))
        return httpx.Response(404)

    def count(self, host: str) -> int:
        return sum(1 for r in self.calls if r.url.host == host)


@pytest.fixture
def upstream() -> FakeUpstream:
    return FakeUpstream()


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    """Upstream retries pause 1.5 s; skip the wait in tests."""
    import asyncio
    real_sleep = asyncio.sleep

    async def instant(delay, *args, **kwargs):
        return await real_sleep(0)
    monkeypatch.setattr(asyncio, "sleep", instant)


@pytest.fixture
def make_client(upstream, monkeypatch):
    """Build a TestClient wired to FakeUpstream, with optional setting overrides."""
    clients = []

    def factory(**env: str) -> TestClient:
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        from app.main import create_app
        app = create_app(transport=httpx.MockTransport(upstream.handle))
        client = TestClient(app, base_url="http://localhost")
        client.__enter__()
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()


JSON_HEADERS = {"Origin": "http://localhost", "Content-Type": "application/json"}


def fake_claude_response(payload: dict, stop_reason: str = "end_turn"):
    from types import SimpleNamespace
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=json.dumps(payload))],
        usage=SimpleNamespace(input_tokens=1000, output_tokens=500),
    )
