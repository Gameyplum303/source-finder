import pytest

from app.sources.pubmed import parse_pubmed_xml
from app.text import clean_text, make_synopsis, normalize_doi
from tests.conftest import pubmed_xml


@pytest.mark.parametrize("raw, expected", [
    ("https://doi.org/10.1000/ABC.def", "10.1000/abc.def"),
    ("doi:10.1234/xyz", "10.1234/xyz"),
    ("10.1/too-short-registrant", ""),
    ("not a doi", ""),
    (None, ""),
])
def test_normalize_doi(raw, expected):
    assert normalize_doi(raw) == expected


def test_clean_text_strips_markup_and_entities():
    assert clean_text("<i>Rats</i> &amp; <b>mice</b>\n\n done") == "Rats & mice done"
    assert clean_text(42) == ""


def test_synopsis_drops_section_labels():
    text = "BACKGROUND: Sleep matters for health and wellbeing in adolescents around the world today."
    assert make_synopsis(text).startswith("Sleep matters")


@pytest.mark.parametrize("text", [
    "Abstract not available for this article. CME J 2025; 4(2):76-81 and more words here",
    "Please create a username and password and log in to your CE Planner account to take the test.",
    "Too short.",
])
def test_synopsis_rejects_placeholders_and_boilerplate(text):
    assert make_synopsis(text) == ""


def test_synopsis_truncates_at_sentence_boundary():
    sentence = "This sentence is exactly about sixty characters long, roughly. "
    synopsis = make_synopsis(sentence * 20)
    assert 0 < len(synopsis) <= 420
    assert synopsis.endswith(".")


def test_parse_pubmed_xml_extracts_signals():
    records = parse_pubmed_xml(pubmed_xml({"123": {
        "coi": "None declared.", "types": ["Randomized Controlled Trial"],
        "agencies": ["Wellcome Trust"], "banks": ["ClinicalTrials.gov"],
        "corrections": ["RetractionIn"]}}))
    rec = records["123"]
    assert rec["coi"] == "None declared."
    assert rec["pub_types"] == ["Randomized Controlled Trial"]
    assert rec["agencies"] == ["Wellcome Trust"]
    assert rec["registered"] is True
    assert rec["concern"] is True


@pytest.mark.parametrize("payload", [
    # XXE: an external entity pointing at a local file.
    b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
    b'<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>1</PMID></MedlineCitation>'
    b'<CoiStatement>&x;</CoiStatement></PubmedArticle></PubmedArticleSet>',
    # "Billion laughs" entity expansion.
    b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;">]>'
    b'<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>1</PMID></MedlineCitation>'
    b'<CoiStatement>&b;</CoiStatement></PubmedArticle></PubmedArticleSet>',
])
def test_parse_pubmed_xml_blocks_entity_attacks(payload):
    from defusedxml import DefusedXmlException
    with pytest.raises(DefusedXmlException):
        parse_pubmed_xml(payload)
