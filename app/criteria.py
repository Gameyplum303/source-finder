"""Quality criteria shared by the OpenAlex search filter and the quality gate,
defined once so the two can never drift apart."""

# OpenAlex `listed_in` id -> (short badge label, full description). Each list is
# maintained by an expert committee that reviews a venue's peer review and
# editorial standards before admitting it.
VETTING_LISTS: dict[str, tuple[str, str]] = {
    "medline": ("MEDLINE", "Selected for MEDLINE by the U.S. National Library of Medicine's "
                           "expert review committee"),
    "cwts-core": ("CWTS Core", "Core international scientific venue (CWTS, Leiden University)"),
    "norway-2": ("Norway Level 2", "Leading venue in its field (Norwegian expert panels)"),
    "norway-1": ("Norway Level 1", "Approved scholarly peer-reviewed venue (Norwegian register)"),
    "jufo-3": ("JUFO 3", "Top-level venue (Finnish Publication Forum expert panels)"),
    "jufo-2": ("JUFO 2", "Leading venue (Finnish Publication Forum expert panels)"),
    "jufo-1": ("JUFO 1", "Approved scholarly peer-reviewed venue (Finnish Publication Forum)"),
}

# Peer-reviewed venue types. Rated conference proceedings are included because
# in fields such as computer science they are the main peer-reviewed outlet.
VENUE_TYPES = ("journal", "conference")

# Publication types that are not peer-reviewed research findings.
EXCLUDED_TYPES = frozenset({
    "editorial", "letter", "comment", "news", "published erratum", "erratum", "preprint",
    "retracted publication", "retraction of publication", "expression of concern",
    "study protocol", "dataset", "book", "book section",
})
