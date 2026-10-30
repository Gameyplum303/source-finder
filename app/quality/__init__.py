"""Quality gate and risk-of-bias estimate, for any field.

Risk of bias is an *estimate* (0–100 %, higher = more risk) built from the
abstract and metadata. It adapts the domains of formal appraisal tools (Cochrane
RoB 2, ROBINS-I, AMSTAR 2) so they also make sense outside medicine. Every
factor and its reasons are returned so the score can be checked; it cannot
replace reading the paper.
"""

from __future__ import annotations

from ..models import Article
from . import conflicts, design, reporting, sample, transparency
from .gate import vet

WEIGHTS = {"design": 0.30, "conflicts": 0.25, "sample": 0.15, "reporting": 0.20,
           "transparency": 0.10}


def level_for(score: int) -> str:
    return "Low" if score < 30 else "Moderate" if score < 50 else "High"


def assess_bias(article: Article) -> None:
    """Fill article.bias with an overall risk percentage and per-factor reasons."""
    work = article.openalex or {}
    text = article.abstract.lower()
    title = article.title.lower()

    design_label, design_detail, design_risk = design.assess(article, work, text, title)
    factors = {
        "design": ("Study design & safeguards", design_detail, design_risk),
        "conflicts": ("Conflicts of interest", *conflicts.assess(article, work)),
        "sample": ("Sample size / evidence base", *sample.assess(design_label, text)),
        "reporting": ("Reporting quality", *reporting.assess(design_label, f"{title} {text}")),
        "transparency": ("Transparency", *transparency.assess(article, text)),
    }
    score = round(sum(WEIGHTS[key] * risk for key, (_, _, risk) in factors.items()))
    article.bias = {
        "score": score,
        "level": level_for(score),
        "design": design_label,
        "factors": [
            {"name": name, "detail": detail, "risk": risk, "weight": round(WEIGHTS[key] * 100)}
            for key, (name, detail, risk) in factors.items()
        ],
    }


def vet_and_score(articles: list[Article]) -> tuple[list[Article], int]:
    """Return (articles that passed the gate, number rejected)."""
    kept = [a for a in articles if vet(a)]
    for article in kept:
        assess_bias(article)
    return kept, len(articles) - len(kept)


__all__ = ["WEIGHTS", "assess_bias", "level_for", "vet", "vet_and_score"]
