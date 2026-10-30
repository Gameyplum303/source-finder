"""Factor 4: reporting quality (spin, causal overreach, uncertainty, limitations)."""

from __future__ import annotations

import re

from .design import OBSERVATIONAL

_HYPE = ["groundbreaking", "ground-breaking", "breakthrough", "revolutionary", "revolutioniz",
         "revolutionis", "unprecedented", "game-chang", "game chang", "miracle", "paradigm shift",
         "first-ever", "definitively", "conclusively", "proves", "proven to", "dramatically",
         "remarkabl", "extraordinar", "astonishing", "perfect accuracy", "no side effects",
         "transformative", "cutting-edge", "cutting edge", "unparalleled", "flawless"]
_HYPE_RE = re.compile(r"\b(?:" + "|".join(re.escape(h) for h in _HYPE) + r")[\w-]*")
# Phrases asserting cause and effect (not "causes of death" or "to determine").
_CAUSAL_RE = re.compile(r"\b(leads? to|led to|resulted in|caused|causally|causes? (an? )?(increase|"
                        r"decrease|reduction|improvement|rise|decline|harm)|proves? that)\b")
_LIMITS_RE = re.compile(r"\blimitations?\b|\blimited by\b|\binterpreted with caution|\bcaution\w*|"
                        r"\bfurther (research|studies|work|investigation)|\bcannot (establish|infer|"
                        r"determine|confirm)|\bmay not (generali[sz]e|apply)")
_UNCERTAINTY_RE = re.compile(r"\bconfidence intervals?|\b9[05]\s?% ?(ci|confidence)|\bci\b|"
                             r"\bstandard (deviation|error)|±|\berror bars?|\bp\s?[<=>]\s?0?\.\d|"
                             r"\bstatistically significant|\beffect sizes?|\bodds ratio|"
                             r"\bhazard ratio|\brelative risk|\bcredible interval")
_HEDGE_RE = re.compile(r"\b(may|might|suggests?|appears? to|associated with|uncertain\w*)\b")


def assess(design: str, text: str) -> tuple[str, int]:
    """Return (explanation, risk). `text` is the lower-cased title + abstract."""
    risk = 40
    concerns: list[str] = []
    hype = sorted({m.group(0) for m in _HYPE_RE.finditer(text)})
    if hype:
        risk += 15 * min(len(hype), 3)
        concerns.append("promotional language (" + ", ".join(f"“{h}”" for h in hype[:3]) + ")")
    if design in OBSERVATIONAL and _CAUSAL_RE.search(text):
        risk += 12
        concerns.append("causal claims from a study that cannot show cause and effect")
    good: list[str] = []
    if _LIMITS_RE.search(text):
        risk -= 15
        good.append("acknowledges limitations")
    if _UNCERTAINTY_RE.search(text):
        risk -= 10
        good.append("reports statistical uncertainty")
    if _HEDGE_RE.search(text):
        risk -= 5
        good.append("uses measured wording")

    parts = []
    if concerns:
        parts.append("Concerns: " + "; ".join(concerns) + ".")
    if good:
        listed = ", ".join(good)
        parts.append(f"Good signs: {listed}." if concerns else listed[0].upper() + listed[1:] + ".")
    if not parts:
        parts.append("Neutral wording, but limitations and uncertainty are not discussed in the abstract.")
    return " ".join(parts), max(5, min(90, risk))
