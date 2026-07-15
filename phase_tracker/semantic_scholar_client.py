"""Semantic Scholar connector via the Graph API paper search.

Free keyless tier (rate limited; a clear message is raised when throttled).
Adds what the other providers lack: citation counts and influence signals.
Pure module: stdlib only, no Qt. Results are external, non-authoritative
observations.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from .references import ConnectorError, ExternalQueryOutcome, ExternalReference

API_ENDPOINT = "https://api.semanticscholar.org/graph/v1/paper/search"
USER_AGENT = "orchestra-phase-tracker (research workspace; single interactive queries)"
DEFAULT_MAX_RESULTS = 25
REQUEST_TIMEOUT_SECONDS = 20

_FIELDS = ",".join(
    [
        "title", "abstract", "authors", "year", "venue", "externalIds",
        "url", "openAccessPdf", "publicationDate", "citationCount",
        "influentialCitationCount", "publicationTypes",
    ]
)


def build_request_url(query: str, max_results: int = DEFAULT_MAX_RESULTS) -> str:
    cleaned = " ".join(query.split())
    if not cleaned:
        raise ValueError("query must not be empty")
    params = {
        "query": cleaned,
        "limit": max(1, min(int(max_results), 100)),
        "fields": _FIELDS,
    }
    return f"{API_ENDPOINT}?{urllib.parse.urlencode(params)}"


def parse_payload(payload: str, query: str) -> ExternalQueryOutcome:
    try:
        message = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ConnectorError(
            f"Semantic Scholar returned malformed data: {error}"
        ) from error
    references = []
    for item in message.get("data") or []:
        external_ids = item.get("externalIds") or {}
        doi = (external_ids.get("DOI") or "").strip()
        open_access = item.get("openAccessPdf") or {}
        extra: list[tuple[str, str]] = []
        for key, value in (
            ("citations", item.get("citationCount")),
            ("influential_citations", item.get("influentialCitationCount")),
        ):
            if value is not None:
                extra.append((key, str(value)))
        arxiv_id = (external_ids.get("ArXiv") or "").strip()
        if arxiv_id:
            extra.append(("arxiv_id", arxiv_id))
        kinds = item.get("publicationTypes") or []
        if kinds:
            extra.append(("publication_types", ", ".join(kinds)))
        references.append(
            ExternalReference(
                provider="semanticscholar",
                ref_id=str(item.get("paperId") or ""),
                title=" ".join((item.get("title") or "").split()),
                authors=tuple(
                    (author.get("name") or "").strip()
                    for author in item.get("authors") or []
                    if (author.get("name") or "").strip()
                ),
                summary=" ".join((item.get("abstract") or "").split()),
                venue=(item.get("venue") or "").strip(),
                published=(
                    item.get("publicationDate") or str(item.get("year") or "")
                ).strip(),
                url=(item.get("url") or "").strip(),
                pdf_url=(open_access.get("url") or "").strip(),
                doi=doi,
                extra=tuple(extra),
            )
        )
    return ExternalQueryOutcome(
        provider="semanticscholar",
        query=query,
        total_available=int(message.get("total") or 0),
        references=tuple(references),
    )


def search(query: str, max_results: int = DEFAULT_MAX_RESULTS) -> ExternalQueryOutcome:
    url = build_request_url(query, max_results)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        if error.code == 429:
            raise ConnectorError(
                "Semantic Scholar rate limit reached (free tier) — wait a moment "
                "and try again."
            ) from error
        raise ConnectorError(f"Semantic Scholar request failed: {error}") from error
    except OSError as error:
        raise ConnectorError(f"Semantic Scholar request failed: {error}") from error
    return parse_payload(payload, query)
