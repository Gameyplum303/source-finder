"""Factor 2: conflicts of interest (disclosure statement, funders, affiliations)."""

from __future__ import annotations

import re

from ..models import Article
from ..sources.openalex import company_affiliations, funder_names

COMPANY_RE = re.compile(
    r"\b(inc|ltd|llc|gmbh|corp|corporation|plc|company|pharma\w*|therapeutics|biotech\w*|"
    r"technologies|google|deepmind|microsoft|amazon|apple|meta platforms|ibm|nvidia|openai|"
    r"tesla|uber|waymo|toyota|volkswagen|bmw|ford|general motors|boeing|airbus|siemens|philips|"
    r"samsung|huawei|intel|qualcomm|exxon|shell|bp|chevron|pfizer|novartis|roche|merck|"
    r"astrazeneca|johnson\s*&\s*johnson|sanofi|glaxosmithkline|gsk|bayer|amgen|eli lilly|"
    r"abbvie|bristol[- ]myers|medtronic|nestl[eé]|coca[- ]cola|pepsico|philip morris)\b",
    re.IGNORECASE)

# Only funders whose names say they are public/non-profit are treated as such;
# anything else (e.g. "Swiss Re", a company with no corporate suffix) is "unclear".
PUBLIC_RE = re.compile(
    r"\b(universit\w*|college|school|institut\w*|academy|academia|ministry|ministerio|minist[eè]re|"
    r"department of|national|federal|government|council|commission|agency|foundation|fund\b|"
    r"trust|society|association|nih|nsf|nserc|cihr|sshrc|erc|dfg|anr|epsrc|ukri|nihr|"
    r"wellcome|gates|horizon 2020|european (union|commission|research)|nextgenerationeu|"
    r"state|province|region\w*|city of|county|hhs|nasa|doe|darpa|bundes\w*|"
    r"forschung\w*|consejo|conicet|cnpq|capes|fapesp|jsps|nsfc|kakenhi|nrf|tamkeen|"
    r"hospital|health service|nhs|research centre|research center|laborator\w*|"
    r"faraday institution|max planck|helmholtz|fraunhofer|cnrs|inserm|csic)\b",
    re.IGNORECASE)

_NO_COI_RE = re.compile(
    r"\b(no|none|nothing|not have any)\b[^.]{0,60}\b(conflicts?|competing|financial (interests?|"
    r"relationships?)|disclos\w*)|\bdeclare[sd]? (that )?(there (is|are) )?no\b|"
    r"\bnothing to disclose\b|\bnone declared\b|^\s*none\.?\s*$", re.IGNORECASE)

_TIES: list[tuple[str, str]] = [
    ("employment", r"\b(employee|employed by|employment|works? (for|at))\b"),
    ("consulting / advisory roles", r"\bconsult(ant|ing|ancy|s|ed)\b|\badvisory (board|role)|"
                                    r"\badvis[eo]r (to|for)\b"),
    ("speaker fees / honoraria", r"\bhonorari|\bspeaker('s)? (fees|bureau)|\bpersonal fees\b|"
                                 r"\blecture fees\b"),
    ("stock or equity", r"\b(stock|shares|equity|shareholder|stockholder)\b"),
    ("patents / royalties", r"\b(patents?|royalt\w+)\b"),
    ("industry grants", r"\b(grants?|research support|funding|support) from\b"),
]


def analyze_statement(statement: str) -> tuple[list[str], bool]:
    """Return (types of financial ties disclosed, declared-no-conflicts?)."""
    text = statement.lower()
    ties = [label for label, pattern in _TIES if re.search(pattern, text)]
    # Grants alone only count when a company is named (public grants are not a COI).
    if "industry grants" in ties and not COMPANY_RE.search(statement):
        ties.remove("industry grants")
    return ties, bool(_NO_COI_RE.search(statement)) and not ties


def assess(article: Article, work: dict) -> tuple[str, int]:
    """Return (explanation, risk)."""
    pubmed = article.pubmed or {}
    companies = company_affiliations(work)
    funders = list(dict.fromkeys(funder_names(work) + [a for a in pubmed.get("agencies", []) if a]))
    industry = [f for f in funders if COMPANY_RE.search(f)]
    public = [f for f in funders if f not in industry and PUBLIC_RE.search(f)]
    unclear = [f for f in funders if f not in industry and f not in public]

    statement = pubmed.get("coi", "")
    ties, declared_none = analyze_statement(statement) if statement else ([], False)

    reasons: list[str] = []
    risk = 0
    if ties:
        risk = 60 if len(ties) == 1 else 70 if len(ties) == 2 else 80
        reasons.append("Authors disclosed financial ties (" + ", ".join(ties) + ")")
    if industry:
        risk = max(risk, 75)
        reasons.append("funded by " + ", ".join(industry[:3]))
    if companies:
        risk = max(risk, 70)
        reasons.append("author(s) affiliated with " + ", ".join(companies[:3]))
    if reasons:
        return "Potential conflict of interest: " + "; ".join(reasons) + ".", risk

    if declared_none:
        detail = "Authors declared no conflicts of interest"
        if public or unclear:
            detail += "; funded by " + ", ".join((public + unclear)[:3])
        return detail + ".", 10 if public and not unclear else 15
    if unclear:
        return ("Funded by " + ", ".join((public + unclear)[:3])
                + "; funder type unclear and no conflict-of-interest statement found."), 35
    if public:
        return ("Funded by public or non-profit sources (" + ", ".join(public[:3])
                + "); no conflict-of-interest statement found."), 25
    if statement and re.search(r"\b(grants?|funding|support(ed)?)\b", statement, re.IGNORECASE):
        return "Disclosure lists only non-industry funding; no financial ties to companies.", 20
    if statement:
        return "A conflict-of-interest statement exists but is unclear.", 35
    return "No funding or conflict-of-interest information found, so this cannot be checked.", 50
