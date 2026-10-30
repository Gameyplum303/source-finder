"""Factor 5: transparency (pre-registration, open code/data, open access)."""

from __future__ import annotations

import re

from ..models import Article

_REGISTRATION_RE = re.compile(
    r"\b(nct\d{8}|isrctn\d+|crd\d{8,}|prospero|chictr[-\w]*|actrn\d+|drks\d+|euctr|ctri/|"
    r"osf\.io/\w+|aspredicted|pre-?registered|prospectively registered|trial registration|"
    r"registered report)\b")
_OPEN_MATERIALS_RE = re.compile(
    r"github\.com|gitlab\.com|zenodo|figshare|dryad|osf\.io|\bcode (is|are) (publicly |openly |freely )?"
    r"available|\bopen[- ]source(d)? (code|implementation|software|tool)|\bdata (is|are) "
    r"(publicly |openly |freely )?available|\bpublicly available (data|dataset|code)|"
    r"\breplication (package|files|code|materials)|\bwe (release|make available|share) (our|the) "
    r"(code|data|dataset)")


def assess(article: Article, text: str) -> tuple[str, int]:
    """Return (explanation, risk). `text` is the lower-cased abstract."""
    if _REGISTRATION_RE.search(text) or (article.pubmed or {}).get("registered"):
        return "Study protocol was registered in advance, reducing selective reporting.", 10
    if _OPEN_MATERIALS_RE.search(text):
        return "Code or data are openly shared, so results can be checked and reproduced.", 15
    if article.open_access:
        return "Full text is free to read; no pre-registration or shared code/data mentioned.", 35
    return "Paywalled; no pre-registration or shared code/data mentioned in the abstract.", 55
