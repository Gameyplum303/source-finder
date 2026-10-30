from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Article:
    title: str
    url: str
    synopsis: str
    authors: list[str] = field(default_factory=list)
    journal: str = ""
    year: int | None = None
    doi: str = ""
    citations: int | None = None
    open_access: bool = False
    source: str = ""
    # Legal free copy: {"url", "version", "license", "host"} or None.
    free_access: dict[str, Any] | None = None
    # Filled in by the quality package.
    quality: dict[str, Any] = field(default_factory=dict)
    bias: dict[str, Any] = field(default_factory=dict)
    # Internal signals used for vetting/scoring; never sent to the browser.
    abstract: str = ""
    pub_types: set[str] = field(default_factory=set)
    has_concern: bool = False
    retraction_checked: bool = False   # Crossref / Retraction Watch check succeeded
    pmid: str = ""
    openalex: dict[str, Any] | None = None
    pubmed: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """The public view of the article (an explicit allow-list of fields)."""
        return {
            "id": "doi:" + self.doi,
            "title": self.title, "url": self.url, "synopsis": self.synopsis,
            "authors": self.authors, "journal": self.journal, "year": self.year,
            "doi": self.doi, "citations": self.citations,
            "open_access": self.open_access, "source": self.source,
            "free_access": self.free_access,
            "quality": self.quality, "bias": self.bias,
        }
