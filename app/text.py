"""Helpers for cleaning and normalizing untrusted text from upstream APIs."""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import quote, urlsplit

SYNOPSIS_MAX_CHARS = 420

_TAG_RE = re.compile(r"<[^>]{0,500}>")
_WS_RE = re.compile(r"\s+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
_PLACEHOLDER_RE = re.compile(r"abstract (is )?not (available|provided)|no abstract", re.IGNORECASE)
# Abstracts that are really publisher boilerplate (CE-credit logins, paywall
# notices) carry no information about the study, so they are treated as missing.
_BOILERPLATE_RE = re.compile(
    r"username and password|log ?in to your|ce planner|continuing education credit|"
    r"this article is protected by copyright|full text of this article|"
    r"is available to subscribers|purchase (this|the) article", re.IGNORECASE)


def clean_text(value: Any, limit: int = 2000) -> str:
    """Strip markup and collapse whitespace from untrusted upstream text."""
    if not isinstance(value, str):
        return ""
    text = html.unescape(_TAG_RE.sub(" ", value[: limit * 4]))
    return _WS_RE.sub(" ", text).strip()[:limit]


def make_synopsis(text: str) -> str:
    """Shorten an abstract to its first few sentences ('' if it has no real content)."""
    text = clean_text(text, 6000)
    # Drop structured-abstract labels like "BACKGROUND:" at the very start.
    text = re.sub(r"^(abstract|background|introduction|objectives?|purpose|unlabelled|"
                  r"importance|context|aims?)\s*[:.]\s*", "", text, flags=re.IGNORECASE)
    # Some sources drop the colon after a section label ("Background Delirium is…").
    text = re.sub(r"^(Abstract|Background|Unlabelled|Objectives?)\s+(?=[A-Z])", "", text)
    if len(text) < 60 or _PLACEHOLDER_RE.search(text[:80]) or _BOILERPLATE_RE.search(text):
        return ""
    if len(text) <= SYNOPSIS_MAX_CHARS:
        return text
    out = ""
    for sentence in _SENTENCE_RE.split(text):
        if len(out) + len(sentence) + 1 > SYNOPSIS_MAX_CHARS:
            break
        out = f"{out} {sentence}".strip()
    if not out:
        out = text[:SYNOPSIS_MAX_CHARS].rsplit(" ", 1)[0] + "…"
    return out


def normalize_doi(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    doi = value.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):]
    doi = doi.lower()
    return doi if _DOI_RE.match(doi) and len(doi) <= 300 else ""


def safe_url(value: Any) -> str:
    """Return the URL only if it is a plain absolute http(s) URL, else ''.

    Blocks javascript:/data: links and characters that browsers or URL parsers
    treat inconsistently, since these URLs come from third-party data.
    """
    if not isinstance(value, str) or len(value) > 2000:
        return ""
    value = value.strip()
    if any(c in value for c in "\\\x00\n\r\t \"'<>"):
        return ""
    try:
        parts = urlsplit(value)
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return ""
    return value


def doi_link(doi: str) -> str:
    return "https://doi.org/" + quote(doi, safe="/:;()._-")


def as_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if 0 <= number < 10**7 else None


def normalize_pub_type(value: Any) -> str:
    """Map each database's publication-type vocabulary onto one lowercase form."""
    if not isinstance(value, str):
        return ""
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value)  # "CaseReport" -> "Case Report"
    text = _WS_RE.sub(" ", text.lower().replace("-", " ")).strip()[:60]
    aliases = {
        "case reports": "case report", "letters and comments": "letter",
        "review article": "review", "research article": "journal article",
    }
    return aliases.get(text, text)
