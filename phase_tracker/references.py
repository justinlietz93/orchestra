"""Provider-agnostic external reference records.

Every external literature connector (arXiv, Crossref, PubMed, Semantic
Scholar) returns these records, so one dialog, one exporter, and one BibTeX
converter serve all providers. Records are frozen observations; nothing here
touches the project index, workflow state, or the workbench.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class ConnectorError(RuntimeError):
    """Raised when an external provider cannot be reached or returns bad data."""


@dataclass(frozen=True)
class ExternalReference:
    provider: str
    ref_id: str
    title: str
    authors: tuple[str, ...]
    summary: str
    venue: str
    published: str
    url: str
    pdf_url: str = ""
    doi: str = ""
    extra: tuple[tuple[str, str], ...] = ()

    def extra_dict(self) -> dict[str, str]:
        return dict(self.extra)


@dataclass(frozen=True)
class ExternalQueryOutcome:
    provider: str
    query: str
    total_available: int
    references: tuple[ExternalReference, ...] = field(default_factory=tuple)


PROVIDER_LABELS = {
    "arxiv": "arXiv",
    "crossref": "Crossref",
    "pubmed": "PubMed",
    "semanticscholar": "Semantic Scholar",
}

PROVIDER_ENDPOINTS = {
    "arxiv": "https://export.arxiv.org/api/query",
    "crossref": "https://api.crossref.org/works",
    "pubmed": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/",
    "semanticscholar": "https://api.semanticscholar.org/graph/v1/paper/search",
}


def provider_label(provider: str) -> str:
    return PROVIDER_LABELS.get(provider, provider)


def from_arxiv(outcome) -> ExternalQueryOutcome:
    """Adapt an arxiv_client.ArxivQueryOutcome to generic reference records."""
    references = []
    for result in outcome.results:
        extra: list[tuple[str, str]] = [
            ("primary_category", result.primary_category),
            ("categories", ", ".join(result.categories)),
        ]
        if result.comment:
            extra.append(("comment", result.comment))
        journal_ref = getattr(result, "journal_ref", "")
        if journal_ref:
            extra.append(("journal_ref", journal_ref))
        references.append(
            ExternalReference(
                provider="arxiv",
                ref_id=result.arxiv_id,
                title=result.title,
                authors=result.authors,
                summary=result.summary,
                venue=result.primary_category,
                published=result.published,
                url=result.abs_url,
                pdf_url=result.pdf_url,
                doi=result.doi,
                extra=tuple(extra),
            )
        )
    return ExternalQueryOutcome(
        provider="arxiv",
        query=outcome.query,
        total_available=outcome.total_available,
        references=tuple(references),
    )
