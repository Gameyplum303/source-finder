"""Factor 1: study design (evidence hierarchy) and its safeguards, for any field."""

from __future__ import annotations

import re

from ..models import Article
from ..sources.openalex import study_designs

OBSERVATIONAL = frozenset({"Cohort / longitudinal study", "Cross-sectional / survey study",
                           "Observational study", "Qualitative study", "Case study",
                           "Case report / case series"})
REVIEWS = frozenset({"Meta-analysis", "Systematic review", "Scoping review"})


def _has(pattern: str, text: str) -> bool:
    return re.search(pattern, text) is not None


def base_design(article: Article, work: dict, text: str, title: str) -> tuple[str, int]:
    """Classify the study design -> (label, base risk 0-100). Order matters:
    the strongest, most specific signals are checked first."""
    tags = article.pub_types | study_designs(work)
    if "meta analysis" in tags or _has(r"\bmeta[- ]analys", title):
        return "Meta-analysis", 10
    if "systematic review" in tags or _has(r"\bsystematic (literature )?review", title):
        return "Systematic review", 15
    if ("randomized controlled trial" in tags
            or _has(r"\brandomi[sz]ed (controlled |clinical |field )?(trial|experiment)|"
                    r"\brandom(ly)? assign|\ba/b test", text)):
        return "Randomized controlled trial / experiment", 20
    if _has(r"\bmeta[- ]analys", text) or _has(r"\bsystematic(ally)? review", text[:600]):
        return "Systematic review", 15
    if _has(r"\bscoping review|\bumbrella review", title + " " + text[:400]):
        return "Scoping review", 30
    if _has(r"\b(difference[- ]in[- ]differences?|regression discontinuity|instrumental variables?|"
            r"natural experiment|synthetic control|mendelian randomi[sz]ation)\b", text):
        return "Quasi-experimental study", 35
    if "clinical trial" in tags or _has(r"\b(clinical|controlled|pilot) trial\b|\b(open[- ]label|"
                                         r"single[- ]arm|phase (i{1,3}|[1-3])) (study|trial)\b", text):
        return "Non-randomized clinical trial", 40
    if "case report" in tags or _has(r"\bcase (report|series)\b", title + " " + text[:300]):
        return "Case report / case series", 80
    if _has(r"\b(benchmarks?|state[- ]of[- ]the[- ]art|outperform\w*|ablation)\b", text) \
            and _has(r"\b(datasets?|data sets?|benchmarks?)\b", text):
        return "Empirical / benchmark evaluation", 40
    if _has(r"\b(a|this) (comprehensive |systematic |brief )?survey (of|on)\b|\bliterature survey\b",
            title + " " + text[:300]):
        return "Narrative review", 60
    if _has(r"\b(controlled|laboratory|lab|field|wind[- ]tunnel|bench[- ]scale) (experiments?|tests?|"
            r"trials?|study)\b|\bexperimental (study|investigation|results|setup|data)\b|"
            r"\bwe (conducted|performed|carried out) (a series of )?(experiments?|tests?)", text):
        return "Controlled / laboratory experiment", 30
    if _has(r"\b(cohort|case[- ]control|longitudinal|panel data|prospective(ly)?|"
            r"retrospective(ly)?)\b", text):
        return "Cohort / longitudinal study", 45
    if _has(r"\b(cross[- ]sectional|survey|questionnaire)\b", text):
        return "Cross-sectional / survey study", 55
    if "observational study" in tags or _has(r"\bobservational\b", text):
        return "Observational study", 50
    if _has(r"\b(qualitative|semi[- ]structured interviews?|focus groups?|thematic analysis|"
            r"grounded theory|ethnograph\w*)\b", text):
        return "Qualitative study", 55
    if _has(r"\b(simulat\w+|numerical (model|study|analysis|simulation)|finite[- ]element|"
            r"agent[- ]based|in silico|computational (model|study|fluid)|cfd|monte carlo|"
            r"model(l)?ing (study|approach|framework))\b", text):
        return "Simulation / modelling study", 45
    if work.get("type") == "review" or "review" in tags or _has(r"\breview\b", title):
        return "Narrative review", 60
    if _has(r"\bwe (propose|present|develop|introduce|design)\b|\b(proposed|novel|new) (method|model|"
            r"framework|approach|algorithm|technique|architecture|system)\b|\bdata[- ]driven\b|"
            r"\b(trained|tested|validated|evaluated) (on|using|with)\b", text):
        return "Method / model development", 45
    if _has(r"\b(we prove|theorem|lemma|closed[- ]form|analytical (solution|model|framework)|"
            r"theoretical (analysis|framework|model))\b", text):
        return "Theoretical / analytical study", 40
    if _has(r"\b(case study|case studies)\b", text):
        return "Case study", 55
    if _has(r"\b(we (argue|propose that|discuss)|this (essay|commentary|perspective|position paper))\b",
            text):
        return "Conceptual / position paper", 65
    return "Study design not stated", 50


# (pattern, risk adjustment, note) applied on top of the base design.
MODIFIERS: list[tuple[str, int, str]] = [
    (r"\b(double|triple|single)[- ]blind(ed)?\b|\bblinded\b", -5, "blinded"),
    (r"\bplacebo[- ]controlled\b", -3, "placebo-controlled"),
    (r"\bopen[- ]label\b|\bunblinded\b", 8, "open-label (not blinded)"),
    (r"\bmulti[- ]?(cent(er|re)|site|national)\b", -3, "multi-site"),
    (r"\bsingle[- ](cent(er|re)|site|institution)\b", 5, "single-site"),
    (r"\b(pilot|feasibility|preliminary|proof[- ]of[- ]concept|exploratory) (study|trial|"
     r"experiment|investigation|results)\b", 10, "pilot / preliminary"),
    (r"\b(propensity score|adjusted for|multivariable|multivariate regression|controlling for|"
     r"fixed effects|covariates?)\b", -5, "adjusts for confounders"),
    (r"\bprisma\b", -3, "follows PRISMA reporting"),
    (r"\b(risk of bias|quality assessment|grade approach|certainty of (the )?evidence)\b", -3,
     "assesses quality of included studies"),
    (r"\b(validated|validation) (against|with|using) (field|real[- ]world|observed|empirical|"
     r"measured|experimental) (data|measurements|observations)\b|\bcompared (with|against|to) "
     r"(field|experimental|measured|observed) (data|measurements|results)\b", -10,
     "validated against real-world data"),
    (r"\bcalibrated\b", -4, "calibrated model"),
    (r"\bablation\b", -3, "includes ablation analysis"),
    (r"\breplicat(ed|ion|es)\b", -3, "replicated / replication"),
    (r"\bsensitivity analys[ie]s|\brobustness (checks?|tests?|analys[ie]s)", -3,
     "sensitivity / robustness checks"),
]
_SINGLE_SITE = next(p for p, _, note in MODIFIERS if note == "single-site")


def assess(article: Article, work: dict, text: str, title: str) -> tuple[str, str, int]:
    """Return (design label, explanation, risk)."""
    label, risk = base_design(article, work, text, title)
    matched = {note: delta for pattern, delta, note in MODIFIERS
               if re.search(pattern, f"{title} {text}")}
    # Abstracts often mention the opposite setting as future work ("a multicentre
    # study is needed"). The title decides; if it doesn't, an abstract naming both is ambiguous.
    if "single-site" in matched and "multi-site" in matched:
        keep = "single-site" if re.search(_SINGLE_SITE, title) else None
        for note in ("single-site", "multi-site"):
            if note != keep:
                matched.pop(note)
    risk = max(5, min(95, risk + sum(matched.values())))
    detail = label + (f"; {', '.join(matched)}." if matched else ".")
    return label, detail, risk
