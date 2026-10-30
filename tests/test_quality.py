import pytest

from app.quality import vet_and_score
from app.models import Article
from tests.conftest import RCT_ABSTRACT, make_work


def article(abstract="A study of things in people that reports findings clearly and well.",
            title="A study", pubmed=None, pub_types=(), has_concern=False, open_access=False,
            **work_kwargs) -> Article:
    work = make_work("10.1000/x", title, abstract, **work_kwargs)
    return Article(title=title, url="https://doi.org/10.1000/x", synopsis="s", doi="10.1000/x",
                   abstract=abstract, openalex=work, pubmed=pubmed, pub_types=set(pub_types),
                   has_concern=has_concern, open_access=open_access)


def score(a: Article) -> dict:
    passed, rejected = vet_and_score([a])
    assert passed, "article unexpectedly failed the quality gate"
    return a.bias


def factor(a: Article, name: str) -> dict:
    return next(f for f in score(a)["factors"] if f["name"] == name)


# ---------------------------------------------------------------- quality gate

def test_gate_accepts_vetted_journal_and_fills_quality():
    a = article()
    assert vet_and_score([a]) == ([a], 0)
    assert a.quality["venue_type"] == "journal"
    assert [v["label"] for v in a.quality["vetted_by"]] == ["MEDLINE", "CWTS Core"]
    assert a.quality["field"] == "Medicine"
    assert a.quality["top_cited"] == "Top 10% most-cited in its field"


def test_gate_accepts_vetted_conference():
    a = article(venue_type="conference", listed=("cwts-core", "norway-2"))
    assert vet_and_score([a])[0] == [a]
    assert a.quality["venue_type"] == "conference"


@pytest.mark.parametrize("kwargs", [
    {"listed": ()},                                   # not on any vetted list
    {"listed": ("doaj",)},                            # DOAJ alone is not enough
    {"venue_type": "book series"},                    # not a journal/conference
    {"work_type": "editorial"},                       # not research
    {"retracted": True},                              # retracted
    {"has_concern": True},                            # expression of concern
    {"pub_types": ("editorial",)},                    # excluded publication type
    {"designs": ("Study Protocol",)},                 # protocol, no results
])
def test_gate_rejects(kwargs):
    assert vet_and_score([article(**kwargs)]) == ([], 1)


def test_gate_rejects_unverifiable_article():
    a = Article(title="t", url="u", synopsis="s", doi="10.1000/x", abstract="text")
    assert vet_and_score([a]) == ([], 1)


# ---------------------------------------------------------------- study design

@pytest.mark.parametrize("title, abstract, design, notes", [
    ("Effect of a drug", RCT_ABSTRACT, "Randomized controlled trial / experiment", ["blinded", "multi-site"]),
    ("Deep residual learning", "we evaluate on six benchmark datasets and outperform state-of-the-art "
     "methods; ablation studies confirm", "Empirical / benchmark evaluation", ["includes ablation analysis"]),
    ("A survey of graph neural networks", "this survey reviews methods", "Narrative review", []),
    ("Congestion pricing and traffic", "using a difference-in-differences design with city fixed effects",
     "Quasi-experimental study", ["adjusts for confounders"]),
    ("Wind loads on towers", "wind tunnel experiments were compared with field measurements",
     "Controlled / laboratory experiment", ["validated against real-world data"]),
    ("Traffic flow", "a microscopic simulation calibrated and validated against field data",
     "Simulation / modelling study", ["validated against real-world data", "calibrated model"]),
    ("On the convergence of SGD", "we prove a theorem giving closed-form bounds",
     "Theoretical / analytical study", []),
    ("Battery ageing", "we propose a novel data-driven method for capacity estimation",
     "Method / model development", []),
    ("A Single-Centre Detection Study", "we evaluate on benchmark datasets and outperform baselines; "
     "multicenter validation is needed", "Empirical / benchmark evaluation", ["single-site"]),
])
def test_design_classification(title, abstract, design, notes):
    bias = score(article(abstract=abstract, title=title))
    assert bias["design"] == design
    detail = bias["factors"][0]["detail"]
    for note in notes:
        assert note in detail
    if "single-site" in notes:
        assert "multi-site" not in detail


# ---------------------------------------------------------- conflicts of interest

@pytest.mark.parametrize("pubmed, work_kwargs, expected_risk, phrase", [
    ({"coi": "The authors declare no competing interests.", "agencies": []}, {}, 15, "declared no conflicts"),
    ({"coi": "None declared.", "agencies": ["NIH HHS"]}, {}, 10, "declared no conflicts"),
    ({"coi": "J.D. is an employee of Pfizer and holds stock.", "agencies": []}, {}, 70, "employment"),
    (None, {"funders": ("Pfizer",)}, 75, "funded by Pfizer"),
    (None, {"companies": ("Edge Case Research",)}, 70, "affiliated with Edge Case Research"),
    (None, {"funders": ("National Science Foundation",)}, 25, "public or non-profit"),
    (None, {"funders": ("Swiss Re",)}, 35, "funder type unclear"),
    ({"coi": "A.B. received grants from the National Science Foundation.", "agencies": []}, {}, 20,
     "only non-industry funding"),
    (None, {}, 50, "cannot be checked"),
])
def test_conflicts(pubmed, work_kwargs, expected_risk, phrase):
    f = factor(article(pubmed=pubmed, **work_kwargs), "Conflicts of interest")
    assert f["risk"] == expected_risk
    assert phrase in f["detail"]


# ------------------------------------------------------------------ sample size

@pytest.mark.parametrize("abstract, expected", [
    ("a prospective cohort of 10 904 participants", "10,904"),
    ("we analysed 1.2 million trips recorded by 250 vehicles in a cohort", "1,200,000"),
    ("a cohort of mice (n = 30 kg body weight) was studied prospectively", "30"),
])
def test_sample_size_parsing(abstract, expected):
    assert expected in factor(article(abstract=abstract), "Sample size / evidence base")["detail"]


def test_systematic_review_counts_included_not_screened_studies():
    f = factor(article(title="A systematic review of X",
                       abstract="of 1,200 articles identified, 9 met inclusion criteria."),
               "Sample size / evidence base")
    assert "9 studies" in f["detail"] and f["risk"] == 50


def test_sample_size_not_applied_to_theory():
    f = factor(article(title="Bounds", abstract="we prove a theorem with closed-form bounds"),
               "Sample size / evidence base")
    assert "Not applicable" in f["detail"]


# ------------------------------------------------------------- reporting quality

def test_reporting_flags_causal_claims_in_observational_designs():
    f = factor(article(abstract="in this prospective cohort, social media use led to depression."),
               "Reporting quality")
    assert "causal claims" in f["detail"] and f["risk"] > 40


def test_reporting_does_not_flag_causes_of_death():
    f = factor(article(abstract="a cohort study of leading causes of death, to determine whether rates fell."),
               "Reporting quality")
    assert "causal" not in f["detail"]


def test_reporting_flags_hype_and_rewards_limitations():
    hype = factor(article(abstract="our groundbreaking model dramatically outperforms all others"),
                  "Reporting quality")
    careful = factor(article(abstract="results may not generalize; limitations include a 95% CI overlap"),
                     "Reporting quality")
    assert "promotional language" in hype["detail"]
    assert hype["risk"] > careful["risk"]


# ----------------------------------------------------------------- transparency

@pytest.mark.parametrize("abstract, pubmed, open_access, risk", [
    ("trial registration: NCT01234567", None, False, 10),
    ("an ordinary abstract with nothing special", {"coi": "", "agencies": [], "registered": True}, False, 10),
    ("code is available at github.com/example/repo", None, False, 15),
    ("an ordinary abstract with nothing special", None, True, 35),
    ("an ordinary abstract with nothing special", None, False, 55),
])
def test_transparency(abstract, pubmed, open_access, risk):
    assert factor(article(abstract=abstract, pubmed=pubmed, open_access=open_access),
                  "Transparency")["risk"] == risk


# --------------------------------------------------------------- overall score

def test_score_is_weighted_sum_and_level_matches():
    bias = score(article(abstract=RCT_ABSTRACT, title="Trial"))
    weighted = sum(f["risk"] * f["weight"] / 100 for f in bias["factors"])
    assert bias["score"] == round(weighted)
    assert sum(f["weight"] for f in bias["factors"]) == 100
    expected = "Low" if bias["score"] < 30 else "Moderate" if bias["score"] < 50 else "High"
    assert bias["level"] == expected
