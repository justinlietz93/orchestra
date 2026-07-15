"""Crossref connector: published-literature metadata by free-text query.

Free, keyless JSON API. Uses the polite pool via a descriptive User-Agent.
Pure module: stdlib only, no Qt. Results are external, non-authoritative
observations.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

from .references import ConnectorError, ExternalQueryOutcome, ExternalReference

API_ENDPOINT = "https://api.crossref.org/works"
USER_AGENT = (
    "orchestra-phase-tracker (research workspace; single interactive queries; "
    "mailto:contact@neuroca.ai)"
)
DEFAULT_MAX_RESULTS = 25
REQUEST_TIMEOUT_SECONDS = 20

_JATS_TAG = re.compile(r"<[^>]+>")


def build_request_url(query: str, max_results: int = DEFAULT_MAX_RESULTS) -> str:
    cleaned = " ".join(query.split())
    if not cleaned:
        raise ValueError("query must not be empty")
    params = {
        "query": cleaned,
        "rows": max(1, min(int(max_results), 100)),
        "select": ",".join(
            [
                "DOI", "title", "author", "abstract", "container-title",
                "issued", "URL", "type", "volume", "issue", "page",
                "publisher", "link",
            ]
        ),
    }
    return f"{API_ENDPOINT}?{urllib.parse.urlencode(params)}"


def _issued_date(item: dict) -> str:
    parts = (item.get("issued") or {}).get("date-parts") or [[]]
    first = parts[0] if parts and isinstance(parts[0], list) else []
    pieces = [str(first[0])] if first else []
    if len(first) > 1:
        pieces.append(f"{int(first[1]):02d}")
    if len(first) > 2:
        pieces.append(f"{int(first[2]):02d}")
    return "-".join(pieces)


def _authors(item: dict) -> tuple[str, ...]:
    names = []
    for author in item.get("author") or []:
        given = (author.get("given") or "").strip()
        family = (author.get("family") or "").strip()
        name = " ".join(piece for piece in (given, family) if piece)
        if not name:
            name = (author.get("name") or "").strip()
        if name:
            names.append(name)
    return tuple(names)


def _pdf_link(item: dict) -> str:
    for link in item.get("link") or []:
        if link.get("content-type") == "application/pdf" and link.get("URL"):
            return link["URL"]
    return ""


def parse_payload(payload: str, query: str) -> ExternalQueryOutcome:
    try:
        message = json.loads(payload)["message"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise ConnectorError(f"Crossref returned malformed data: {error}") from error
    references = []
    for item in message.get("items") or []:
        titles = item.get("title") or []
        title = " ".join((titles[0] if titles else "").split())
        abstract = " ".join(_JATS_TAG.sub(" ", item.get("abstract") or "").split())
        containers = item.get("container-title") or []
        venue = (containers[0] if containers else "").strip()
        doi = (item.get("DOI") or "").strip()
        extra: list[tuple[str, str]] = [("type", item.get("type") or "")]
        for key in ("volume", "issue", "publisher"):
            value = (item.get(key) or "").strip()
            if value:
                extra.append((key, value))
        pages = (item.get("page") or "").strip()
        if pages:
            extra.append(("pages", pages))
        references.append(
            ExternalReference(
                provider="crossref",
                ref_id=doi or (item.get("URL") or ""),
                title=title,
                authors=_authors(item),
                summary=abstract,
                venue=venue,
                published=_issued_date(item),
                url=item.get("URL") or (f"https://doi.org/{doi}" if doi else ""),
                pdf_url=_pdf_link(item),
                doi=doi,
                extra=tuple(extra),
            )
        )
    return ExternalQueryOutcome(
        provider="crossref",
        query=query,
        total_available=int(message.get("total-results") or 0),
        references=tuple(references),
    )


def search(query: str, max_results: int = DEFAULT_MAX_RESULTS) -> ExternalQueryOutcome:
    url = build_request_url(query, max_results)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = response.read().decode("utf-8")
    except OSError as error:
        raise ConnectorError(f"Crossref request failed: {error}") from error
    return parse_payload(payload, query)
