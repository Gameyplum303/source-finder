[![Tests](https://github.com/Gameyplum303/source-finder/actions/workflows/tests.yml/badge.svg)](https://github.com/Gameyplum303/source-finder/actions/workflows/tests.yml)

# Source Finder

A website for finding reliable, peer-reviewed sources on any topic in any
field (health care, engineering, computer science, transportation, social
sciences, physical sciences and more). Type a topic (e.g. "AI mistakes in health
care" or "congestion pricing effects on traffic") and get vetted articles with a
link, title, authors, venue, year, field and a short synopsis.

## Where the articles come from

Rather than scraping publisher sites, which breaks easily, often violates their
terms, and can't tell peer-reviewed work from blog posts, the server queries the
official public APIs of large scholarly indexes (all free):

| Source | Coverage | Used for |
|---|---|---|
| [OpenAlex](https://openalex.org) | ~250M works, all disciplines | search, plus venue vetting, field and funders for every result |
| [Europe PMC](https://europepmc.org) | life sciences, plus much engineering & physical science | search (journal articles only, no preprints) |
| [Semantic Scholar](https://www.semanticscholar.org) | all disciplines, AI-written TL;DRs | search (journal & conference papers, no preprints) |
| [PubMed](https://pubmed.ncbi.nlm.nih.gov) (E-utilities) | biomedical and much applied science | conflict-of-interest statements, indexer publication types, trial registration, retraction links |

Results are merged and de-duplicated by DOI. The synopsis is Semantic Scholar's
TL;DR when available, otherwise the opening sentences of the abstract.

## Quality gate (`app/quality/gate.py`)

Every candidate, whichever database it came from, is cross-checked in OpenAlex
by DOI and shown only if **all** of these hold:

1. It is a research article or review, not an editorial, letter, comment, news item,
   erratum, preprint or study protocol.
2. Its journal **or conference proceedings** is on at least one **expert-curated list**
   whose committees review editorial and peer-review standards: MEDLINE (U.S. National
   Library of Medicine), CWTS Core (Leiden University), the Norwegian Register (levels
   1–2) or the Finnish Publication Forum (JUFO 1–3). Rated conferences are included
   because in fields like computer science they are the main peer-reviewed venues.
3. It is not retracted and has no expression of concern (OpenAlex, Europe PMC, PubMed).
4. It has a DOI and a real abstract (not publisher boilerplate), so it can be verified.

The number of results hidden by the gate is shown on the page.

## Estimated risk of bias

Each article gets a 0–100 % risk-of-bias estimate (lower is better) with a
per-factor breakdown. It adapts the domains of formal tools such as Cochrane
RoB 2, ROBINS-I and AMSTAR 2 so they work in every field:

| Factor | Weight | Lower risk | Higher risk |
|---|---|---|---|
| Study design & safeguards | 30 % | meta-analysis, systematic review, randomized experiment; blinding, multi-site, confounder adjustment, validation against real data, robustness checks | case report, narrative review, survey, case study; pilot, single-site, open-label |
| Conflicts of interest | 25 % | disclosure says no conflicts; public / non-profit funding | disclosed consulting, employment, stock, patents; industry funding; company-affiliated authors |
| Sample size / evidence base | 15 % | large samples, many pooled studies, many benchmark datasets | small or unreported samples (not applied to theory, simulations or narrative reviews) |
| Reporting quality | 20 % | acknowledges limitations, reports statistical uncertainty | promotional "spin" words; causal claims from observational data |
| Transparency | 10 % | pre-registered protocol, openly shared code/data | paywalled, nothing shared |

Study designs recognized include meta-analyses, systematic and scoping reviews,
randomized trials and experiments, quasi-experiments (difference-in-differences,
regression discontinuity, instrumental variables), clinical trials, controlled /
laboratory experiments, benchmark evaluations, method/model development,
simulations, cohort, cross-sectional/survey, qualitative and theoretical studies,
case studies, narrative reviews, position papers and case reports.

It is computed from the abstract and metadata only, so it is a screening aid,
not a full appraisal. Read the paper's methods before relying on it.

## Optional AI review (`app/ai_review.py`)

Set `ANTHROPIC_API_KEY` in the server's environment and each article gets a
**Get AI review** button. Claude (Opus 5.5, high effort) appraises the abstract
like a research methodologist, domain by domain: study design & selection,
confounding, outcome measurement, missing data, selective reporting, funding &
conflicts, and spin. It returns its own risk-of-bias percentage, strengths,
concerns and a confidence level (it only sees the abstract).

- **Cost:** reviews run only when someone clicks, roughly $0.05–0.10 each.
  Results are cached for 7 days. `AI_REVIEW_DAILY_LIMIT` (default 200) caps
  the server's daily total and `AI_REVIEW_PER_MINUTE` (default 6) limits each visitor.
- **Security:** the browser sends only a DOI, and the server reviews only articles it
  vetted in a recent search, so the endpoint can't be used to send arbitrary text to
  Claude. Abstracts are passed as delimited, untrusted data; the reply is forced into
  a JSON schema and re-validated server-side; requests must come from this site's
  own origin; the API key never leaves the server.
- If a safety classifier declines a request, the API's server-side fallback re-runs
  it on Anthropic's recommended model (`fallbacks: "default"`).

Without a key the button is simply hidden and everything else works as before.

## Run it

```bash
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then open http://127.0.0.1:8000. Optional settings are listed in `.env.example`.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

The suite runs fully offline: every upstream API is replaced by a fake
(`tests/conftest.py`), so it is fast and deterministic. It covers text
cleaning, safe XML parsing, the quality gate, every scoring factor, the search
pipeline, security headers, input validation, rate limits and the AI review
endpoint.

## Project layout

```
app/
  main.py          app factory: security middleware, routes, error handlers
  config.py        all settings, read from environment variables in one place
  search.py        search pipeline: sources → merge → verify → enrich → vet → cache
  ai_review.py     optional Claude review of an abstract
  criteria.py      vetted venue lists and excluded publication types (shared)
  models.py        the Article record and its public (browser) view
  text.py          cleaning/normalizing untrusted upstream text
  upstream.py      hardened HTTP client (timeouts, size cap, retry)
  limits.py        bounded TTL cache and sliding-window rate limiter
  sources/         one module per database (openalex, europepmc,
                   semantic_scholar, pubmed); add engines here
  quality/         gate.py + one module per bias factor (design, conflicts,
                   sample, reporting, transparency)
static/            index.html, app.js, styles.css
tests/             offline test suite
```

To add a search engine, create `app/sources/<name>.py` exposing `KEY`, `LABEL`,
`FIRST_PAGE` and `async def search(client, settings, query, cursor, per_page)`,
then add it to `SEARCH_SOURCES` in `app/sources/__init__.py`.

## Security measures

- **Safe XML parsing:** PubMed responses are parsed with `defusedxml`, which blocks
  XXE and entity-expansion ("billion laughs") attacks.
- **No scraping / SSRF surface:** the server only calls four hard-coded HTTPS APIs;
  user input is passed solely as an encoded query value. Redirects are not followed,
  requests time out, and responses are capped at 5 MB.
- **XSS:** upstream text is stripped of HTML on the server and rendered with
  `textContent` in the browser; links are allowed only if they parse as `http(s)`.
  A strict Content-Security-Policy blocks inline and third-party scripts.
- **Input validation:** queries are Unicode-normalized, stripped of control/invisible
  characters and limited to 3–200 characters. Paging tokens are strictly validated.
- **Abuse protection:** per-IP rate limiting and a 15-minute result cache.
- **Headers:** CSP, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: no-referrer`
  (your search terms aren't leaked to article sites), Permissions-Policy, HSTS over HTTPS.
- **Host allow-list** (`ALLOWED_HOSTS`) against DNS-rebinding / Host-header attacks.
- **Error handling:** generic error messages to users, details only in server logs;
  API docs endpoints are disabled.
- **Secrets:** optional API keys are read from environment variables only.
- **Paid endpoint:** the AI review endpoint is protected as described above.
- No accounts, cookies or database, so there is no stored user data to protect.

When deploying publicly, put it behind HTTPS (e.g. Caddy or nginx), set
`ALLOWED_HOSTS` to your domain, and if behind a proxy, configure uvicorn's
`--proxy-headers --forwarded-allow-ips` so rate limiting sees real client IPs.
