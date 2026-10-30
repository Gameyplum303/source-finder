"""Quality gate: an article is shown only if every check passes.

1. Found in OpenAlex by DOI, so its venue can be verified.
2. A research article or review — not an editorial, letter, comment, news
   item, erratum, preprint or study protocol.
3. Published in a journal or conference proceedings on at least one
   expert-curated list (criteria.VETTING_LISTS).
4. Not retracted and no expression of concern (OpenAlex, Europe PMC, PubMed).
"""

from __future__ import annotations

from ..criteria import EXCLUDED_TYPES, VENUE_TYPES, VETTING_LISTS
from ..models import Article
from ..sources.openalex import field_of, source_of, study_designs
from ..text import clean_text


def _top_cited(work: dict) -> str:
    percentile = work.get("citation_normalized_percentile")
    if not isinstance(percentile, dict):
        return ""
    if percentile.get("is_in_top_1_percent"):
        return "Top 1% most-cited in its field"
    if percentile.get("is_in_top_10_percent"):
        return "Top 10% most-cited in its field"
    return ""


def vet(article: Article) -> bool:
    """Apply the quality gate; on success fill article.quality and return True."""
    work = article.openalex
    if not isinstance(work, dict):
        return False
    if work.get("type") not in ("article", "review"):
        return False
    if work.get("is_retracted") or article.has_concern:
        return False
    if (article.pub_types | study_designs(work)) & EXCLUDED_TYPES:
        return False

    source = source_of(work)
    venue_type = source.get("type")
    if venue_type not in VENUE_TYPES:
        return False
    listed = source.get("listed_in")
    vetted_by = [VETTING_LISTS[k] for k in VETTING_LISTS if isinstance(listed, list) and k in listed]
    if not vetted_by:
        return False

    if not article.journal:
        article.journal = clean_text(source.get("display_name"), 200)
    article.quality = {
        "peer_reviewed": True,
        "venue_type": venue_type,
        "vetted_by": [{"label": label, "detail": detail} for label, detail in vetted_by],
        "not_retracted": True,
        "retraction_watch_checked": article.retraction_checked,
        "top_cited": _top_cited(work),
        "field": field_of(work),
    }
    return True
