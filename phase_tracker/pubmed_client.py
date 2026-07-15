"""PubMed connector via NCBI E-utilities.

Two-step keyless flow: esearch resolves the query to PMIDs and a total
count, efetch retrieves full records (title, abstract, authors, journal,
DOI). Pure module: stdlib only, no Qt. Results are external,
non-authoritative observations.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from .references import ConnectorError, ExternalQueryOutcome, ExternalReference

BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
USER_AGENT = "orchestra-phase-tracker (research workspace; single interactive queries)"
TOOL_NAME = "orchestra-phase-tracker"
DEFAULT_MAX_RESULTS = 25
REQUEST_TIMEOUT_SECONDS = 20

_MONTH_NUMBERS = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05",
    "jun": "06", "jul": "07", "aug": "08", "sep": "09", "oct": "10",
    "nov": "11", "dec": "12",
}


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return response.read()
    except OSError as error:
        raise ConnectorError(f"PubMed request failed: {error}") from error


def build_esearch_url(query: str, max_results: int = DEFAULT_MAX_RESULTS) -> str:
    cleaned = " ".join(query.split())
    if not cleaned:
        raise ValueError("query must not be empty")
    params = {
        "db": "pubmed",
        "term": cleaned,
        "retmax": max(1, min(int(max_results), 100)),
        "retmode": "json",
        "sort": "relevance",
        "tool": TOOL_NAME,
    }
    return f"{BASE_URL}esearch.fcgi?{urllib.parse.urlencode(params)}"


def build_efetch_url(pmids: list[str]) -> str:
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
        "tool": TOOL_NAME,
    }
    return f"{BASE_URL}efetch.fcgi?{urllib.parse.urlencode(params)}"


def parse_esearch(payload: str) -> tuple[list[str], int]:
    try:
        result = json.loads(payload)["esearchresult"]
        return list(result.get("idlist") or []), int(result.get("count") or 0)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise ConnectorError(f"PubMed esearch returned malformed data: {error}") from error


def _published(article: ET.Element) -> str:
    date = article.find(".//JournalIssue/PubDate")
    if date is None:
        return ""
    year = (date.findtext("Year") or "").strip()
    if not year:
        return " ".join((date.findtext("MedlineDate") or "").split())
    month_raw = (date.findtext("Month") or "").strip().lower()
    month = _MONTH_NUMBERS.get(month_raw[:3], month_raw if month_raw.isdigit() else "")
    if month:
        return f"{year}-{int(month):02d}"
    return year


def _abstract(article: ET.Element) -> str:
    pieces = []
    for section in article.findall(".//Abstract/AbstractText"):
        text = " ".join("".join(section.itertext()).split())
        label = section.get("Label")
        if label and text:
            text = f"{label}: {text}"
        if text:
            pieces.append(text)
    return " ".join(pieces)


def _authors(article: ET.Element) -> tuple[str, ...]:
    names = []
    for author in article.findall(".//AuthorList/Author"):
        collective = (author.findtext("CollectiveName") or "").strip()
        if collective:
            names.append(collective)
            continue
        last = (author.findtext("LastName") or "").strip()
        fore = (author.findtext("ForeName") or author.findtext("Initials") or "").strip()
        name = " ".join(piece for piece in (fore, last) if piece)
        if name:
            names.append(name)
    return tuple(names)


def parse_efetch(payload: bytes, query: str, total_available: int) -> ExternalQueryOutcome:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as error:
        raise ConnectorError(f"PubMed efetch returned malformed XML: {error}") from error
    references = []
    for article in root.findall(".//PubmedArticle"):
        pmid = (article.findtext(".//PMID") or "").strip()
        title_element = article.find(".//ArticleTitle")
        title = " ".join(
            "".join(title_element.itertext()).split()
        ) if title_element is not None else ""
        doi = ""
        for identifier in article.findall(".//ArticleIdList/ArticleId"):
            if identifier.get("IdType") == "doi":
                doi = (identifier.text or "").strip()
        extra: list[tuple[str, str]] = []
        issue = article.find(".//JournalIssue")
        if issue is not None:
            for key, tag in (("volume", "Volume"), ("issue", "Issue")):
                value = (issue.findtext(tag) or "").strip()
                if value:
                    extra.append((key, value))
        pages = (article.findtext(".//Pagination/MedlinePgn") or "").strip()
        if pages:
            extra.append(("pages", pages))
        references.append(
            ExternalReference(
                provider="pubmed",
                ref_id=pmid,
                title=title,
                authors=_authors(article),
                summary=_abstract(article),
                venue=" ".join((article.findtext(".//Journal/Title") or "").split()),
                published=_published(article),
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
                pdf_url="",
                doi=doi,
                extra=tuple(extra),
            )
        )
    return ExternalQueryOutcome(
        provider="pubmed",
        query=query,
        total_available=total_available,
        references=tuple(references),
    )


def search(query: str, max_results: int = DEFAULT_MAX_RESULTS) -> ExternalQueryOutcome:
    esearch_payload = _fetch(build_esearch_url(query, max_results)).decode("utf-8")
    pmids, total = parse_esearch(esearch_payload)
    if not pmids:
        return ExternalQueryOutcome(
            provider="pubmed", query=query, total_available=total, references=()
        )
    efetch_payload = _fetch(build_efetch_url(pmids))
    return parse_efetch(efetch_payload, query, total)
