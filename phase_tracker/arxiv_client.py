"""Minimal arXiv API client using only the standard library.

This module deliberately has no Qt and no third-party dependencies. It is a
thin, replaceable connector: a future provider-neutral connector layer can
supersede it without touching the GUI. Results from this module are external,
non-authoritative observations and are never written into the project index.
"""

from __future__ import annotations

import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

API_ENDPOINT = "https://export.arxiv.org/api/query"
USER_AGENT = "orchestra-phase-tracker (research workspace; single interactive queries)"
DEFAULT_MAX_RESULTS = 25
REQUEST_TIMEOUT_SECONDS = 20

_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"
_OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}"


@dataclass(frozen=True)
class ArxivResult:
    arxiv_id: str
    title: str
    summary: str
    authors: tuple[str, ...]
    categories: tuple[str, ...]
    primary_category: str
    published: str
    updated: str
    abs_url: str
    pdf_url: str
    comment: str = ""
    doi: str = ""
    journal_ref: str = ""


@dataclass(frozen=True)
class ArxivQueryOutcome:
    query: str
    total_available: int
    results: tuple[ArxivResult, ...] = field(default_factory=tuple)


class ArxivClientError(RuntimeError):
    """Raised when the arXiv API cannot be reached or returns malformed data."""


def build_request_url(query: str, max_results: int = DEFAULT_MAX_RESULTS) -> str:
    """Build the arXiv export API URL for a free-text query.

    Quoted phrases in the query are preserved: arXiv's `all:` field supports
    double-quoted exact phrases, so Orchestra's quoted-phrase convention
    carries over to arXiv queries unchanged.
    """
    cleaned = " ".join(query.split())
    if not cleaned:
        raise ValueError("query must not be empty")
    params = {
        "search_query": f"all:{cleaned}",
        "start": 0,
        "max_results": max(1, min(int(max_results), 100)),
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    return f"{API_ENDPOINT}?{urllib.parse.urlencode(params)}"


def parse_feed(feed_xml: str, query: str) -> ArxivQueryOutcome:
    """Parse an arXiv Atom feed into an ArxivQueryOutcome."""
    try:
        root = ET.fromstring(feed_xml)
    except ET.ParseError as error:
        raise ArxivClientError(f"arXiv returned malformed XML: {error}") from error

    total_text = root.findtext(f"{_OPENSEARCH}totalResults") or "0"
    try:
        total_available = int(total_text)
    except ValueError:
        total_available = 0

    results: list[ArxivResult] = []
    for entry in root.findall(f"{_ATOM}entry"):
        entry_id = (entry.findtext(f"{_ATOM}id") or "").strip()
        arxiv_id = entry_id.rsplit("/abs/", 1)[-1] if "/abs/" in entry_id else entry_id
        title = " ".join((entry.findtext(f"{_ATOM}title") or "").split())
        summary = " ".join((entry.findtext(f"{_ATOM}summary") or "").split())
        authors = tuple(
            (author.findtext(f"{_ATOM}name") or "").strip()
            for author in entry.findall(f"{_ATOM}author")
            if (author.findtext(f"{_ATOM}name") or "").strip()
        )
        categories = tuple(
            element.get("term", "")
            for element in entry.findall(f"{_ATOM}category")
            if element.get("term")
        )
        primary_element = entry.find(f"{_ARXIV}primary_category")
        primary_category = (
            primary_element.get("term", "") if primary_element is not None else ""
        )
        abs_url = entry_id
        pdf_url = ""
        for link in entry.findall(f"{_ATOM}link"):
            if link.get("title") == "pdf":
                pdf_url = link.get("href", "")
            elif link.get("rel") == "alternate":
                abs_url = link.get("href", abs_url)
        results.append(
            ArxivResult(
                arxiv_id=arxiv_id,
                title=title,
                summary=summary,
                authors=authors,
                categories=categories,
                primary_category=primary_category or (categories[0] if categories else ""),
                published=(entry.findtext(f"{_ATOM}published") or "").strip(),
                updated=(entry.findtext(f"{_ATOM}updated") or "").strip(),
                abs_url=abs_url,
                pdf_url=pdf_url,
                comment=" ".join((entry.findtext(f"{_ARXIV}comment") or "").split()),
                doi=(entry.findtext(f"{_ARXIV}doi") or "").strip(),
                journal_ref=" ".join(
                    (entry.findtext(f"{_ARXIV}journal_ref") or "").split()
                ),
            )
        )
    return ArxivQueryOutcome(
        query=query,
        total_available=total_available,
        results=tuple(results),
    )


def search(query: str, max_results: int = DEFAULT_MAX_RESULTS) -> ArxivQueryOutcome:
    """Run a live arXiv query. Network access happens only here."""
    url = build_request_url(query, max_results)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            feed_xml = response.read().decode("utf-8")
    except OSError as error:
        raise ArxivClientError(f"arXiv request failed: {error}") from error
    return parse_feed(feed_xml, query)
