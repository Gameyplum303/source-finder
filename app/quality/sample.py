"""Factor 3: sample size / evidence base."""

from __future__ import annotations

import re

from .design import REVIEWS

# A number, allowing "1,234" / "1 234" (incl. thin spaces) and "1.2 million".
_SEPARATORS = r"[,\N{THIN SPACE}\N{NARROW NO-BREAK SPACE} ]"
_NUM = (rf"(\d{{1,3}}(?:{_SEPARATORS}\d{{3}})+|\d+(?:\.\d+)?)"
        r"(?:\s*(million|thousand|k)\b)?")
_UNITS = (r"patients|participants|subjects|individuals|adults|children|adolescents|youths?|"
          r"women|men|people|persons|respondents|volunteers|students|teachers|employees|workers|"
          r"households|families|firms|companies|organi[sz]ations|cities|countries|regions|"
          r"municipalities|schools|hospitals|clinicians|physicians|doctors|nurses|users|customers|"
          r"consumers|cases|records|admissions|encounters|visits|interviews|responses|"
          r"vehicles|drivers|pedestrians|cyclists|passengers|trips|journeys|crashes|accidents|"
          r"intersections|roads|images|videos|documents|tweets|posts|transactions|observations|"
          r"measurements|samples|specimens|sites|sensors|devices|buildings|games|sessions|"
          r"utterances|sentences|queries|programs|repositories|apps")
_SAMPLE_RE = re.compile(rf"\bn\s*=\s*{_NUM}|\b{_NUM}\s+(?:[a-z-]+\s+){{0,3}}(?:{_UNITS})\b")
_STUDY_WORDS = r"(?:studies|trials|articles|papers|publications|rcts|reviews)"
_STUDIES_RE = re.compile(rf"\b{_NUM}\s+(?:[a-z-]+\s+){{0,2}}{_STUDY_WORDS}\b")
# "15 studies were included" / "included 15 randomized trials": the final count,
# as opposed to the thousands of records screened during the search.
_INCLUDED_RE = re.compile(
    rf"\b{_NUM}\s+(?:[a-z-]+\s+){{0,2}}{_STUDY_WORDS}\s+(?:were\s+|was\s+)?"
    rf"(?:included|eligible|selected|met|retained|analy[sz]ed)"
    rf"|\binclud(?:ed|ing)\s+(?:a\s+total\s+of\s+)?{_NUM}\s+(?:[a-z-]+\s+){{0,2}}{_STUDY_WORDS}\b"
    rf"|\b{_NUM}\s+(?:[a-z-]+\s+){{0,2}}(?:met|fulfilled)\s+(?:the\s+|our\s+)?(?:inclusion|eligibility)")
_DATASETS_RE = re.compile(rf"\b{_NUM}\s+(?:[a-z-]+\s+){{0,2}}(?:datasets|data sets|benchmarks)\b")
_SCALES = {"million": 1_000_000, "thousand": 1000, "k": 1000}

NOT_APPLICABLE = frozenset({"Narrative review", "Theoretical / analytical study",
                            "Conceptual / position paper", "Simulation / modelling study"})


def numbers(regex: re.Pattern, text: str) -> list[int]:
    """All numbers matched by `regex`, whose groups come in (digits, scale) pairs."""
    found = []
    for match in regex.finditer(text):
        groups = match.groups()
        for i in range(0, len(groups), 2):
            if not groups[i]:
                continue
            try:
                value = float(re.sub(_SEPARATORS, "", groups[i]))
            except ValueError:
                continue
            value *= _SCALES.get(groups[i + 1] or "", 1)
            if 0 < value < 10**10:
                found.append(int(value))
            break
    return found


def assess(design: str, text: str) -> tuple[str, int]:
    """Return (explanation, risk)."""
    if design in REVIEWS:
        included = numbers(_INCLUDED_RE, text)
        counts = included or numbers(_STUDIES_RE, text)
        if not counts:
            return "Number of included studies not stated in the abstract.", 40
        # Without an explicit "included" count, take the smallest figure, since
        # the larger ones are usually records screened (the conservative choice).
        n = max(included) if included else min(counts)
        return f"Pools evidence from {n:,} studies.", 15 if n >= 30 else 30 if n >= 10 else 50
    if design in NOT_APPLICABLE:
        return f"Not applicable to this kind of study ({design.lower()}).", 40
    if design == "Case report / case series":
        return "Very few cases; results may not generalize.", 85
    if design == "Empirical / benchmark evaluation" and (datasets := numbers(_DATASETS_RE, text)):
        n = max(datasets)
        return f"Evaluated on {n} datasets/benchmarks.", 20 if n >= 5 else 30 if n >= 3 else 45
    sizes = numbers(_SAMPLE_RE, text)
    if not sizes:
        return "Sample size not reported in the abstract.", 50
    n = max(sizes)
    for limit, risk, note in ((5000, 10, "very large"), (1000, 20, "large"), (300, 30, "moderate"),
                              (100, 45, "modest"), (30, 65, "small")):
        if n >= limit:
            return f"Sample of about {n:,} ({note} sample).", risk
    return f"Sample of about {n:,} (very small sample).", 80
