import base64
import json

import pytest
from fastapi.testclient import TestClient

from tests.conftest import JSON_HEADERS, fake_claude_response


def decode_token(token: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))


# ------------------------------------------------------------ security basics

def test_security_headers(client):
    headers = client.get("/").headers
    assert "default-src 'self'" in headers["content-security-policy"]
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    assert headers["x-frame-options"] == "DENY"
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "no-referrer"


def test_api_responses_are_not_cached_by_browsers(client):
    assert client.get("/api/search", params={"q": "sleep"}).headers["cache-control"] == "no-store"


def test_unknown_host_is_rejected(client):
    from app.main import create_app
    with TestClient(create_app(), base_url="http://evil.example") as other:
        assert other.get("/").status_code == 400


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json", "/nope"])
def test_docs_disabled_and_404_is_generic(client, path):
    resp = client.get(path)
    assert resp.status_code == 404 and resp.json() == {"error": "Not found."}


# ---------------------------------------------------------- search validation

@pytest.mark.parametrize("q", ["a", "", "   ", "!!!", "x" * 201])
def test_search_rejects_bad_queries(client, q):
    resp = client.get("/api/search", params={"q": q})
    assert resp.status_code == 400 and "error" in resp.json()


def test_search_strips_invisible_characters(client):
    assert client.get("/api/search", params={"q": "sleep​  health‮"}).json()["query"] == "sleep health"


@pytest.mark.parametrize("cursor", [
    "not-base64!!",
    base64.urlsafe_b64encode(b'{"evil": "1"}').decode(),          # unknown source
    base64.urlsafe_b64encode(b'{"openalex": "1; DROP"}').decode(),  # bad characters
    base64.urlsafe_b64encode(b"[1, 2]").decode(),                  # wrong shape
])
def test_search_rejects_tampered_page_tokens(client, cursor):
    assert client.get("/api/search", params={"q": "sleep", "cursor": cursor}).status_code == 400


# -------------------------------------------------------------- search pipeline

def test_search_pipeline_vets_dedupes_and_scores(client):
    data = client.get("/api/search", params={"q": "sleep"}).json()
    # rct1 appears in OpenAlex and Europe PMC but is shown once; the unvetted
    # journal and the retracted paper are hidden.
    assert [r["doi"] for r in data["results"]] == ["10.1000/rct1", "10.1000/epmc2"]
    assert data["rejected"] == 2
    assert data["unavailable"] == []
    assert data["ai_review"] is False

    rct, cohort = data["results"]
    assert rct["id"] == "doi:10.1000/rct1"
    assert rct["quality"]["vetted_by"][0]["label"] == "MEDLINE"
    assert rct["bias"]["design"] == "Randomized controlled trial / experiment"
    conflicts = {f["name"]: f for f in rct["bias"]["factors"]}
    assert "declared no conflicts" in conflicts["Conflicts of interest"]["detail"]   # from PubMed
    assert conflicts["Transparency"]["risk"] == 10                                    # registry link
    cohort_conflicts = {f["name"]: f for f in cohort["bias"]["factors"]}["Conflicts of interest"]
    assert "employment" in cohort_conflicts["detail"]
    assert cohort["quality"]["field"] == "Psychology"
    # Internal fields never reach the browser.
    for key in ("abstract", "openalex", "pubmed", "pub_types", "has_concern", "pmid"):
        assert key not in rct


def test_next_page_token_round_trips(client, upstream):
    first = client.get("/api/search", params={"q": "sleep"}).json()
    assert decode_token(first["next"]) == {"openalex": "2", "europepmc": "AoNEXT"}
    second = client.get("/api/search", params={"q": "sleep", "cursor": first["next"]})
    assert second.status_code == 200


def test_failed_source_is_reported_and_retried_on_next_page(client, upstream):
    upstream.s2_status = 429
    data = client.get("/api/search", params={"q": "sleep"}).json()
    assert data["unavailable"] == ["Semantic Scholar"]
    assert decode_token(data["next"])["s2"] == "0"
    assert len(data["results"]) == 2


def test_pubmed_outage_degrades_gracefully(client, upstream):
    upstream.pubmed_status = 503
    data = client.get("/api/search", params={"q": "sleep"}).json()
    assert "PubMed" in data["unavailable"]
    assert len(data["results"]) == 2


def test_all_sources_down_returns_502(client, upstream):
    upstream.down = True
    resp = client.get("/api/search", params={"q": "sleep"})
    assert resp.status_code == 502 and "error" in resp.json()


def test_repeat_search_is_served_from_cache(client, upstream):
    client.get("/api/search", params={"q": "sleep"})
    calls = len(upstream.calls)
    client.get("/api/search", params={"q": "SLEEP"})
    assert len(upstream.calls) == calls


def test_search_rate_limit(make_client):
    limited = make_client(RATE_LIMIT_PER_MINUTE="2")
    assert limited.get("/api/search", params={"q": "sleep"}).status_code == 200
    assert limited.get("/api/search", params={"q": "sleep"}).status_code == 200
    assert limited.get("/api/search", params={"q": "sleep"}).status_code == 429


# ------------------------------------------------------------------ AI review

REVIEW = {"risk_of_bias_percent": 34, "level": "Low", "study_design": "Cohort",
          "summary": "Large cohort.", "domains": [{"domain": "Confounding", "rating": "Some concerns",
                                                   "explanation": "Partly adjusted."}],
          "strengths": ["Large"], "concerns": ["Self-report"], "confidence": "Medium"}


@pytest.fixture
def ai_client(make_client):
    client = make_client(ANTHROPIC_API_KEY="test-key-not-real")
    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        return fake_claude_response(REVIEW)

    reviewer = client.app.state.reviewer
    reviewer.client.beta.messages.create = create
    client.calls = calls
    client.get("/api/search", params={"q": "sleep"})   # registers vetted DOIs
    return client


def test_ai_review_disabled_without_key(client):
    client.get("/api/search", params={"q": "sleep"})
    resp = client.post("/api/ai-review", json={"doi": "10.1000/rct1"}, headers=JSON_HEADERS)
    assert resp.status_code == 503


def test_ai_review_success_is_validated_and_cached(ai_client):
    first = ai_client.post("/api/ai-review", json={"doi": "10.1000/rct1"}, headers=JSON_HEADERS)
    second = ai_client.post("/api/ai-review", json={"doi": "10.1000/rct1"}, headers=JSON_HEADERS)
    assert first.status_code == 200 and second.status_code == 200
    review = first.json()["review"]
    assert review["score"] == 34
    assert review["level"] == "Moderate"          # recomputed from the score, not trusted
    assert len(ai_client.calls) == 1               # second call came from the cache
    request = ai_client.calls[0]
    assert request["model"] == "claude-opus-5-5"
    assert request["fallbacks"] == "default"
    assert request["output_config"]["format"]["type"] == "json_schema"
    prompt = request["messages"][0]["content"]
    assert "<abstract>" in prompt and "Readmission trial" in prompt


@pytest.mark.parametrize("headers, body, status", [
    ({"Content-Type": "application/json"}, {"doi": "10.1000/rct1"}, 403),                 # no Origin
    ({**JSON_HEADERS, "Origin": "https://evil.example"}, {"doi": "10.1000/rct1"}, 403),  # cross-site
    ({**JSON_HEADERS}, {"doi": "10.1000/rct1", "prompt": "hi"}, 400),                    # extra field
    ({**JSON_HEADERS}, {"doi": "nonsense-value"}, 400),                                  # not a DOI
    ({**JSON_HEADERS}, {"doi": "10.9999/never-searched"}, 404),                          # not vetted
])
def test_ai_review_rejects_bad_requests(ai_client, headers, body, status):
    assert ai_client.post("/api/ai-review", json=body, headers=headers).status_code == status
    assert ai_client.calls == []


def test_ai_review_rejects_form_posts(ai_client):
    resp = ai_client.post("/api/ai-review", data={"doi": "10.1000/rct1"}, headers={"Origin": "http://localhost"})
    assert resp.status_code in (400, 415)
    assert ai_client.calls == []


def test_ai_review_refusal_is_reported(ai_client):
    async def refuse(**kwargs):
        return fake_claude_response({}, stop_reason="refusal")
    ai_client.app.state.reviewer.client.beta.messages.create = refuse
    resp = ai_client.post("/api/ai-review", json={"doi": "10.1000/epmc2"}, headers=JSON_HEADERS)
    assert resp.status_code == 422


def test_ai_review_per_ip_limit(make_client):
    client = make_client(ANTHROPIC_API_KEY="test-key-not-real", AI_REVIEW_PER_MINUTE="1")

    async def create(**kwargs):
        return fake_claude_response(REVIEW)
    client.app.state.reviewer.client.beta.messages.create = create
    client.get("/api/search", params={"q": "sleep"})
    assert client.post("/api/ai-review", json={"doi": "10.1000/rct1"}, headers=JSON_HEADERS).status_code == 200
    assert client.post("/api/ai-review", json={"doi": "10.1000/epmc2"}, headers=JSON_HEADERS).status_code == 429
